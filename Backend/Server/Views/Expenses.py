from flask_restful import Resource
from Server.Models.Expenses import Expenses
from Server.Models.Users import Users
from Server.Models.Accounting.ExpensesLedger import ExpensesLedger
from Server.Models.Shops import Shops
from Server.Models.ExpenseCategory import ExpenseCategory
from Server.Models.BankAccounts import BankAccount, BankingTransaction
from Server.Models.Expenses import CreditPayments, Creditor
from app import db
from flask_jwt_extended import jwt_required, get_jwt_identity
from flask import jsonify, request, make_response
from datetime import datetime
from sqlalchemy import and_
from math import ceil
from functools import wraps
from sqlalchemy.exc import SQLAlchemyError

def check_role(required_role):
    def wrapper(fn):
        @wraps(fn)
        def decorator(*args, **kwargs):
            current_user_id = get_jwt_identity()
            user = Users.query.get(current_user_id)
            if user and user.role != required_role:
                 return make_response(jsonify({"error": "Unauthorized access"}), 403)       
            return fn(*args, **kwargs)
        return decorator
    return wrapper


class AddExpense(Resource):
    @jwt_required()
    @check_role('manager')
    def post(self):
        data = request.get_json()
        current_user_id = get_jwt_identity()

        shop_id = data.get('shop_id')
        creditor_id = data.get('creditor_id')
        
        # New creditor fields (if creating new creditor)
        creditor_name = data.get('creditor_name')
        creditor_phone = data.get('creditor_phone')
        creditor_email = data.get('creditor_email')
        creditor_address = data.get('creditor_address')
        
        item = data.get('item')
        description = data.get('description')
        quantity = data.get('quantity')
        category = data.get('category')
        totalPrice = data.get('totalPrice')
        amountPaid = data.get('amountPaid', 0)
        paidTo = data.get('paidTo')
        source = data.get('source')
        paymentRef = data.get('paymentRef')
        comments = data.get('comments')
        created_at_str = data.get('created_at')
      

        # ===== Validations =====
        if not shop_id or not category or not source or not paymentRef:
            return {"message": "Missing required fields"}, 400

        # Validate amountPaid doesn't exceed totalPrice
        if amountPaid > totalPrice:
            return {"message": "Amount paid cannot exceed total price"}, 400

        try:
            created_at = datetime.strptime(created_at_str, "%Y-%m-%d")
        except:
            return {"message": "Invalid date format. Use YYYY-MM-DD."}, 400

        try:
            # ===== Step 1: Handle Creditor Creation or Validation =====
            creditor = None
            
            # If creditor_id is provided, use existing creditor
            if creditor_id:
                creditor = Creditor.query.get(creditor_id)
                if not creditor:
                    return {"message": f"Creditor with ID {creditor_id} not found"}, 404
            # If creditor_name is provided, create new creditor
            elif creditor_name:
                # Validate required fields for new creditor
                if not creditor_phone:
                    return {"message": "Phone number is required for new creditor"}, 400
                
                # Check if creditor with same name and phone already exists
                existing_creditor = Creditor.query.filter(
                    Creditor.name == creditor_name,
                    Creditor.phone_number == creditor_phone
                ).first()
                
                if existing_creditor:
                    # Use existing creditor instead of creating duplicate
                    creditor = existing_creditor
                else:
                    # Create new creditor
                    creditor = Creditor(
                        name=creditor_name,
                        phone_number=creditor_phone,
                        email=creditor_email,
                        address=creditor_address,
                        user_id=current_user_id,
                        is_active=True
                    )
                    db.session.add(creditor)
                    db.session.flush()  # Get creditor_id

            # ===== Step 2: Handle Bank Deduction for amount paid =====
            if amountPaid > 0:
                # Handle external funding separately (no bank account deduction)
                if source not in ["External funding", "Cash"]:
                    account = BankAccount.query.filter_by(Account_name=source).first()
                    if not account:
                        return {"message": f"Bank account '{source}' not found"}, 404

                    if account.Account_Balance < amountPaid:
                        return {"message": f"Insufficient balance in account '{source}'"}, 400

                    account.Account_Balance -= amountPaid
                    db.session.add(account)

                    transaction = BankingTransaction(
                        account_id=account.id,
                        Transaction_type_debit=amountPaid,
                        Transaction_type_credit=None,
                    )
                    db.session.add(transaction)

            # ===== Step 3: Determine payment status =====
            if amountPaid == 0:
                payment_status = 'pending'
            elif amountPaid >= totalPrice:
                payment_status = 'paid'
            else:
                payment_status = 'partial'

            # ===== Step 4: Create Expense =====
            new_expense = Expenses(
                shop_id=shop_id,
                creditor_id=creditor.creditor_id if creditor else None,
                item=item,
                description=description,
                quantity=quantity,
                category=category,
                totalPrice=totalPrice,
                amountPaid=amountPaid,
                paidTo=paidTo,
                created_at=created_at,
                user_id=current_user_id,
                source=source,
                paymentRef=paymentRef,
                comments=comments,
                payment_status=payment_status
            )

            db.session.add(new_expense)
            db.session.flush()  # Get expense_id without committing

            # ===== Step 5: Record initial payment if any =====
            if amountPaid > 0:
                credit_payment = CreditPayments(
                    expense_id=new_expense.expense_id,
                    amount=amountPaid,
                    payment_ref=paymentRef,
                    source=source,
                    notes="Initial payment",
                    created_by=current_user_id
                )
                db.session.add(credit_payment)

            # ===== Step 6: Update creditor totals if creditor exists =====
            if creditor:
                creditor.update_totals()

            db.session.commit()  # Commit everything

            # ===== Step 7: Post Journal Entry =====
            from Server.Views.Services.journal_service import ExpensesJournalService

            try:
                journal_result = ExpensesJournalService.post_expense_journal(new_expense)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                return {
                    "message": "Expense saved but journal posting failed",
                    "error": str(e),
                    "expense_id": new_expense.expense_id
                }, 500

            # Prepare response
            response_data = {
                "message": "Expense and journal entry added successfully",
                "expense_id": new_expense.expense_id,
                "total_price": totalPrice,
                "amount_paid": amountPaid,
                "outstanding_balance": new_expense.outstanding_balance,
                "payment_status": payment_status,
                "journal_entry": journal_result
            }

            if creditor:
                response_data["creditor"] = {
                    "id": creditor.creditor_id,
                    "name": creditor.name,
                    "phone_number": creditor.phone_number,
                    "outstanding_balance": creditor.outstanding_balance,
                    "is_new": not creditor_id
                }

            return response_data, 201

        except Exception as e:
            db.session.rollback()
            return {"message": "Error adding expense", "error": str(e)}, 500


class AllExpenses(Resource):
    @jwt_required()
    @check_role('manager')
    def get(self):
        # Query parameters
        page = request.args.get('page', 1, type=int)
        per_page = 50
        category = request.args.get('category', type=str)
        shopname = request.args.get('shopname', type=str)
        creditor_id = request.args.get('creditor_id', type=int)
        payment_status = request.args.get('payment_status', type=str)
        start_date = request.args.get('start_date', type=str)
        end_date = request.args.get('end_date', type=str)

        # Base query
        query = Expenses.query

        # Apply filters if provided
        filters = []
        if category:
            filters.append(Expenses.category.ilike(f"%{category}%"))

        if creditor_id:
            filters.append(Expenses.creditor_id == creditor_id)

        if payment_status:
            filters.append(Expenses.payment_status == payment_status)

        if shopname:
            # Join with Shops table to filter by shopname
            query = query.join(Shops, Expenses.shop_id == Shops.shops_id)
            filters.append(Shops.shopname.ilike(f"%{shopname}%"))

        if start_date and end_date:
            try:
                start = datetime.strptime(start_date, '%Y-%m-%d')
                end = datetime.strptime(end_date, '%Y-%m-%d')
                filters.append(Expenses.created_at.between(start, end))
            except ValueError:
                return make_response(jsonify({"error": "Invalid date format. Use YYYY-MM-DD."}), 400)

        if filters:
            query = query.filter(and_(*filters))

        # Order by latest
        query = query.order_by(Expenses.created_at.desc())

        # Pagination
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        expenses = pagination.items

        all_expenses = []
        for expense in expenses:
            user = Users.query.filter_by(users_id=expense.user_id).first()
            shop = Shops.query.filter_by(shops_id=expense.shop_id).first()
            creditor = Creditor.query.get(expense.creditor_id) if expense.creditor_id else None
            
            # Get payment summary
            payments = CreditPayments.query.filter_by(expense_id=expense.expense_id).all()
            total_payments = len(payments)
            total_paid_from_payments = sum(p.amount for p in payments)

            username = user.username if user else "Unknown User"
            shop_name = shop.shopname if shop else "Unknown Shop"
            creditor_name = creditor.name if creditor else None

            # Format created_at
            created_at = None
            if expense.created_at:
                if isinstance(expense.created_at, str):
                    try:
                        created_at = datetime.strptime(expense.created_at, '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        created_at = expense.created_at
                elif isinstance(expense.created_at, datetime):
                    created_at = expense.created_at.strftime('%Y-%m-%d %H:%M:%S')

            all_expenses.append({
                "expense_id": expense.expense_id,
                "user_id": expense.user_id,
                "username": username,
                "shop_id": expense.shop_id,
                "shop_name": shop_name,
                "creditor_id": expense.creditor_id,
                "creditor_name": creditor_name,
                "item": expense.item,
                "description": expense.description,
                "quantity": expense.quantity,
                "category": expense.category,
                "totalPrice": expense.totalPrice,
                "amountPaid": expense.amountPaid,
                "outstanding_balance": expense.outstanding_balance,
                "payment_status": expense.payment_status,
                "paidTo": expense.paidTo,
                "created_at": created_at,
                "source": expense.source,
                "paymentRef": expense.paymentRef,
                "comments": expense.comments,
                "payment_summary": {
                    "total_payments": total_payments,
                    "total_paid": total_paid_from_payments,
                    "sources": list(set(p.source for p in payments if p.source))
                }
            })

        # Pagination metadata
        pagination_info = {
            "page": page,
            "per_page": per_page,
            "total_items": pagination.total,
            "total_pages": ceil(pagination.total / per_page),
            "has_next": pagination.has_next,
            "has_prev": pagination.has_prev,
        }

        return make_response(jsonify({
            "expenses": all_expenses,
            "pagination": pagination_info
        }), 200)


class GetShopExpenses(Resource):
    @jwt_required()
    @check_role('manager')
    def get(self, shop_id):
        shopExpenses = Expenses.query.filter_by(shop_id=shop_id).all()

        expensesForShop = [{
            "expense_id": expense.expense_id,
            "user_id": expense.user_id,
            "shop_id": expense.shop_id,
            "creditor_id": expense.creditor_id,
            "item": expense.item,
            "description": expense.description,
            "category": expense.category,
            "quantity": expense.quantity,
            "totalPrice": expense.totalPrice,
            "amountPaid": expense.amountPaid,
            "outstanding_balance": expense.outstanding_balance,
            "payment_status": expense.payment_status,
            "paidTo": expense.paidTo,
            "source": expense.source,
            "paymentRef": expense.paymentRef,
            "comments": expense.comments,
            "created_at": expense.created_at.strftime('%Y-%m-%d %H:%M:%S') if expense.created_at else None
        } for expense in shopExpenses]

        return make_response(jsonify(expensesForShop), 200)


class ExpensesResources(Resource):
    @jwt_required()
    @check_role('manager')
    def get(self, expense_id):
        # Fetch the specific expense by ID
        expense = Expenses.query.get(expense_id)

        if expense:
            creditor = Creditor.query.get(expense.creditor_id) if expense.creditor_id else None
            
            # Get payment history
            payments = CreditPayments.query.filter_by(expense_id=expense_id).order_by(CreditPayments.payment_date).all()
            payment_history = [
                {
                    "payment_id": p.payment_id,
                    "amount": p.amount,
                    "payment_date": p.payment_date.strftime('%Y-%m-%d %H:%M:%S'),
                    "payment_ref": p.payment_ref,
                    "payment_method": p.payment_method,
                    "source": p.source,
                    "notes": p.notes
                } for p in payments
            ]
            
            return {
                "expense_id": expense.expense_id,
                "user_id": expense.user_id,
                "shop_id": expense.shop_id,
                "creditor_id": expense.creditor_id,
                "creditor_name": creditor.name if creditor else None,
                "item": expense.item,
                "description": expense.description,
                "category": expense.category,
                "quantity": expense.quantity,
                "totalPrice": expense.totalPrice,
                "paidTo": expense.paidTo,
                "amountPaid": expense.amountPaid,
                "outstanding_balance": expense.outstanding_balance,
                "payment_status": expense.payment_status,
                "source": expense.source,
                "paymentRef": expense.paymentRef,
                "comments": expense.comments,
                "created_at": expense.created_at.strftime('%Y-%m-%d %H:%M:%S') if expense.created_at else None,
                "payment_history": payment_history,
                "payment_summary": {
                    "total_payments": len(payments),
                    "total_amount_paid": sum(p.amount for p in payments),
                    "sources": list(set(p.source for p in payments if p.source))
                }
            }, 200
        else:
            return {"error": "Expense not found"}, 404

    @jwt_required()
    @check_role('manager')
    def put(self, expense_id):
        data = request.get_json()
        expense = Expenses.query.get(expense_id)

        if not expense:
            return {"error": "Expense not found"}, 404

        # Store old values for comparison
        old_amount = expense.totalPrice
        old_category = expense.category
        old_date = expense.created_at
        old_creditor_id = expense.creditor_id

        # ------------------------
        # Update Expense Fields
        # ------------------------
        expense.item = data.get('item', expense.item)
        expense.description = data.get('description', expense.description)
        expense.category = data.get('category', expense.category)
        expense.quantity = data.get('quantity', expense.quantity)
        expense.totalPrice = data.get('totalPrice', expense.totalPrice)
        expense.amountPaid = data.get('amountPaid', expense.amountPaid)
        expense.paidTo = data.get('paidTo', expense.paidTo)
        expense.source = data.get('source', expense.source)
        expense.paymentRef = data.get('paymentRef', expense.paymentRef)
        expense.comments = data.get('comments', expense.comments)
        expense.creditor_id = data.get('creditor_id', expense.creditor_id)

        # Update payment status
        expense.update_payment_status()

        # Handle date update
        if 'created_at' in data:
            try:
                expense.created_at = datetime.strptime(
                    data['created_at'], '%Y-%m-%d %H:%M:%S'
                )
            except ValueError:
                expense.created_at = datetime.strptime(
                    data['created_at'], '%Y-%m-%d'
                )

        # -----------------------------------
        # Update Related Ledger Entries
        # -----------------------------------
        ledger_entries = ExpensesLedger.query.filter_by(
            expense_id=expense_id
        ).all()

        for ledger in ledger_entries:
            # Update amount if changed
            if expense.totalPrice != old_amount:
                ledger.amount = expense.totalPrice

            # Update date if changed
            if expense.created_at != old_date:
                ledger.created_at = expense.created_at

            # Update category if changed
            if expense.category != old_category:
                category_obj = ExpenseCategory.query.filter_by(
                    name=expense.category
                ).first()
                if category_obj:
                    ledger.category_id = category_obj.id
                    ledger.debit_account_id = category_obj.debit_account_id
                    ledger.credit_account_id = category_obj.credit_account_id

        # Update creditor totals if creditor changed
        if expense.creditor_id != old_creditor_id:
            if old_creditor_id:
                old_creditor = Creditor.query.get(old_creditor_id)
                if old_creditor:
                    old_creditor.update_totals()
            if expense.creditor_id:
                new_creditor = Creditor.query.get(expense.creditor_id)
                if new_creditor:
                    new_creditor.update_totals()

        db.session.commit()

        return {
            "message": "Expense and ledger updated successfully",
            "expense_id": expense.expense_id,
            "payment_status": expense.payment_status,
            "outstanding_balance": expense.outstanding_balance
        }, 200

    @jwt_required()
    @check_role('manager')
    def delete(self, expense_id):
        expense = Expenses.query.get(expense_id)

        if not expense:
            return {"error": "Expense not found"}, 404

        creditor_id = expense.creditor_id

        # Delete related credit payments
        CreditPayments.query.filter_by(expense_id=expense_id).delete()

        # Delete related ledger entries
        ExpensesLedger.query.filter_by(expense_id=expense_id).delete()

        # Delete expense
        db.session.delete(expense)
        
        # Update creditor totals if creditor exists
        if creditor_id:
            creditor = Creditor.query.get(creditor_id)
            if creditor:
                creditor.update_totals()

        db.session.commit()

        return {"message": "Expense and related records deleted successfully"}, 200


class TotalBalance(Resource):
    @jwt_required()
    @check_role('manager')
    def get(self):
        try:
            # Get start_date and end_date from query parameters
            start_date_str = request.args.get('start_date')
            end_date_str = request.args.get('end_date')
            creditor_id = request.args.get('creditor_id', type=int)

            # Convert date strings to datetime objects if provided
            start_date = datetime.strptime(start_date_str.strip(), '%Y-%m-%d') if start_date_str else None
            end_date = datetime.strptime(end_date_str.strip(), '%Y-%m-%d') if end_date_str else None

            # Query expenses, possibly filtering by date range using created_at
            query = Expenses.query
            if start_date:
                query = query.filter(Expenses.created_at >= start_date)
            if end_date:
                query = query.filter(Expenses.created_at <= end_date)
            if creditor_id:
                query = query.filter(Expenses.creditor_id == creditor_id)

            expenses = query.all()

            # Calculate the total balance (outstanding)
            total_balance = sum(expense.outstanding_balance for expense in expenses)

            # Additional statistics
            stats = {
                "total_outstanding": total_balance,
                "total_expenses": len(expenses),
                "fully_paid": sum(1 for e in expenses if e.payment_status == 'paid'),
                "partial": sum(1 for e in expenses if e.payment_status == 'partial'),
                "pending": sum(1 for e in expenses if e.payment_status == 'pending')
            }

            return make_response(jsonify(stats), 200)

        except SQLAlchemyError as e:
            db.session.rollback()
            return make_response(jsonify({"error": "Database error occurred", "details": str(e)}), 500)
        except Exception as e:
            return make_response(jsonify({"error": "An unexpected error occurred", "details": str(e)}), 500)


class CreditPaymentResource(Resource):
    @jwt_required()
    @check_role('manager')
    def post(self, expense_id):
        """Record a payment towards an expense with outstanding balance"""
        data = request.get_json()
        current_user_id = get_jwt_identity()

        expense = Expenses.query.get(expense_id)
        if not expense:
            return {"error": "Expense not found"}, 404

        amount = data.get('amount')
        payment_ref = data.get('payment_ref')
        payment_method = data.get('payment_method', 'Cash', 'Source')
        notes = data.get('notes')                                   
        source = data.get('source')

        # Validations
        if not amount or amount <= 0:
            return {"error": "Invalid payment amount"}, 400

        if not payment_ref:
            return {"error": "Payment reference is required"}, 400

        if not source:
            return {"error": "Payment source is required"}, 400

        if amount > expense.outstanding_balance:
            return {"error": f"Payment amount exceeds outstanding balance of {expense.outstanding_balance}"}, 400

        try:
            # Handle bank deduction if payment is from bank account
            if source not in ["External funding", "Cash"]:
                account = BankAccount.query.filter_by(Account_name=source).first()
                if not account:
                    return {"error": f"Bank account '{source}' not found"}, 404

                if account.Account_Balance < amount:
                    return {"error": f"Insufficient balance in account '{source}'"}, 400

                account.Account_Balance -= amount
                db.session.add(account)

                transaction = BankingTransaction(
                    account_id=account.id,
                    Transaction_type_debit=amount,
                    Transaction_type_credit=None,
                    description=f"Credit payment for expense {expense_id}",
                    reference=payment_ref
                )
                db.session.add(transaction)

            # Record payment with source
            payment = CreditPayments(
                expense_id=expense_id,
                amount=amount,
                payment_ref=payment_ref,
                payment_method=payment_method,
                source=source,
                notes=notes,
                created_by=current_user_id
            )
            db.session.add(payment)

            # Update expense
            expense.amountPaid += amount
            expense.update_payment_status()
            
            # Update creditor totals if expense has creditor
            if expense.creditor_id:
                creditor = Creditor.query.get(expense.creditor_id)
                if creditor:
                    creditor.update_totals()

            db.session.commit()

            return {
                "message": "Credit payment recorded successfully",
                "payment_id": payment.payment_id,
                "expense_id": expense_id,
                "amount_paid": amount,
                "source": source,
                "remaining_outstanding": expense.outstanding_balance,
                "payment_status": expense.payment_status
            }, 200

        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 500

    @jwt_required()
    @check_role('manager')
    def get(self, expense_id):
        """Get payment history for an expense"""
        payments = CreditPayments.query.filter_by(expense_id=expense_id).order_by(CreditPayments.payment_date.desc()).all()
        
        payment_history = [{
            "payment_id": p.payment_id,
            "amount": p.amount,
            "payment_date": p.payment_date.strftime('%Y-%m-%d %H:%M:%S'),
            "payment_ref": p.payment_ref,
            "payment_method": p.payment_method,
            "source": p.source,
            "notes": p.notes
        } for p in payments]
        
        return make_response(jsonify({
            "expense_id": expense_id,
            "total_payments": len(payments),
            "total_amount_paid": sum(p.amount for p in payments),
            "payment_history": payment_history
        }), 200)




class GetCreditors(Resource):
    @jwt_required()
    def get(self):
        try:
            # Get current user
            current_user_id = get_jwt_identity()
            
            # Get all active creditors
            creditors = Creditor.query.filter_by(is_active=True).all()
            
            # Format the response
            creditors_list = [{
                "creditor_id": creditor.creditor_id,
                "name": creditor.name,
                "phone_number": creditor.phone_number,
                "email": creditor.email,
                "address": creditor.address,
                "total_amount_owed": creditor.total_amount_owed,
                "total_amount_paid": creditor.total_amount_paid,
                "outstanding_balance": creditor.outstanding_balance,
                "payment_status": creditor.payment_status,
                "created_at": creditor.created_at.strftime('%Y-%m-%d %H:%M:%S') if creditor.created_at else None,
                "updated_at": creditor.updated_at.strftime('%Y-%m-%d %H:%M:%S') if creditor.updated_at else None,
                "notes": creditor.notes,
                "is_active": creditor.is_active
            } for creditor in creditors]
            
            return make_response(jsonify({
                "status": "success",
                "creditors": creditors_list,
                "total_creditors": len(creditors_list)
            }), 200)
            
        except Exception as e:
            return make_response(jsonify({
                "status": "error",
                "message": str(e)
            }), 500)


class GetCreditorDetails(Resource):
    @jwt_required()
    def get(self, creditor_id):
        try:
            creditor = Creditor.query.filter_by(
                creditor_id=creditor_id, 
                is_active=True
            ).first()
            
            if not creditor:
                return make_response(jsonify({
                    "status": "error",
                    "message": "Creditor not found"
                }), 404)
            
            # Get all expenses for this creditor
            expenses = Expenses.query.filter_by(creditor_id=creditor_id).all()
            
            expenses_list = [{
                "expense_id": expense.expense_id,
                "item": expense.item,
                "category": expense.category,
                "totalPrice": expense.totalPrice,
                "amountPaid": expense.amountPaid,
                "outstanding_balance": expense.outstanding_balance,
                "payment_status": expense.payment_status,
                "created_at": expense.created_at.strftime('%Y-%m-%d %H:%M:%S') if expense.created_at else None
            } for expense in expenses]
            
            return make_response(jsonify({
                "status": "success",
                "creditor": {
                    "creditor_id": creditor.creditor_id,
                    "name": creditor.name,
                    "phone_number": creditor.phone_number,
                    "email": creditor.email,
                    "address": creditor.address,
                    "total_amount_owed": creditor.total_amount_owed,
                    "total_amount_paid": creditor.total_amount_paid,
                    "outstanding_balance": creditor.outstanding_balance,
                    "payment_status": creditor.payment_status,
                    "notes": creditor.notes,
                    "created_at": creditor.created_at.strftime('%Y-%m-%d %H:%M:%S') if creditor.created_at else None
                },
                "expenses": expenses_list,
                "total_expenses": len(expenses_list)
            }), 200)
            
        except Exception as e:
            return make_response(jsonify({
                "status": "error",
                "message": str(e)
            }), 500)


class CreateExpenseCreditor(Resource):
    @jwt_required()
    def post(self):
        try:
            data = request.get_json()
            
            # Validate required fields
            if not data.get('name'):
                return make_response(jsonify({
                    "status": "error",
                    "message": "Creditor name is required"
                }), 400)
            
            if not data.get('phone_number'):
                return make_response(jsonify({
                    "status": "error",
                    "message": "Phone number is required"
                }), 400)
            
            # Check if creditor already exists
            existing_creditor = Creditor.query.filter_by(
                name=data['name'],
                phone_number=data['phone_number'],
                is_active=True
            ).first()
            
            if existing_creditor:
                return make_response(jsonify({
                    "status": "error",
                    "message": f"Creditor with name '{data['name']}' and phone '{data['phone_number']}' already exists"
                }), 400)
            
            # Get current user
            current_user_id = get_jwt_identity()
            
            # Create new creditor
            new_creditor = Creditor(
                name=data['name'],
                phone_number=data['phone_number'],
                email=data.get('email'),
                address=data.get('address'),
                notes=data.get('notes'),
                user_id=current_user_id,
                is_active=True
            )
            
            db.session.add(new_creditor)
            db.session.commit()
            
            return make_response(jsonify({
                "status": "success",
                "message": "Creditor created successfully",
                "creditor": {
                    "creditor_id": new_creditor.creditor_id,
                    "name": new_creditor.name,
                    "phone_number": new_creditor.phone_number,
                    "email": new_creditor.email,
                    "address": new_creditor.address,
                    "notes": new_creditor.notes
                }
            }), 201)
            
        except Exception as e:
            db.session.rollback()
            return make_response(jsonify({
                "status": "error",
                "message": str(e)
            }), 500)


class UpdateCreditor(Resource):
    @jwt_required()
    def put(self, creditor_id):
        try:
            creditor = Creditor.query.filter_by(
                creditor_id=creditor_id,
                is_active=True
            ).first()
            
            if not creditor:
                return make_response(jsonify({
                    "status": "error",
                    "message": "Creditor not found"
                }), 404)
            
            data = request.get_json()
            
            # Update fields if provided
            if 'name' in data:
                creditor.name = data['name']
            if 'phone_number' in data:
                creditor.phone_number = data['phone_number']
            if 'email' in data:
                creditor.email = data['email']
            if 'address' in data:
                creditor.address = data['address']
            if 'notes' in data:
                creditor.notes = data['notes']
            if 'is_active' in data:
                creditor.is_active = data['is_active']
            
            creditor.updated_at = datetime.datetime.utcnow()
            db.session.commit()
            
            return make_response(jsonify({
                "status": "success",
                "message": "Creditor updated successfully",
                "creditor": {
                    "creditor_id": creditor.creditor_id,
                    "name": creditor.name,
                    "phone_number": creditor.phone_number,
                    "email": creditor.email,
                    "address": creditor.address,
                    "notes": creditor.notes,
                    "is_active": creditor.is_active
                }
            }), 200)
            
        except Exception as e:
            db.session.rollback()
            return make_response(jsonify({
                "status": "error",
                "message": str(e)
            }), 500)


class DeleteCreditor(Resource):
    @jwt_required()
    def delete(self, creditor_id):
        try:
            creditor = Creditor.query.filter_by(creditor_id=creditor_id).first()
            
            if not creditor:
                return make_response(jsonify({
                    "status": "error",
                    "message": "Creditor not found"
                }), 404)
            
            # Soft delete - just mark as inactive
            creditor.is_active = False
            creditor.updated_at = datetime.datetime.utcnow()
            db.session.commit()
            
            return make_response(jsonify({
                "status": "success",
                "message": "Creditor deleted successfully"
            }), 200)
            
        except Exception as e:
            db.session.rollback()
            return make_response(jsonify({
                "status": "error",
                "message": str(e)
            }), 500)