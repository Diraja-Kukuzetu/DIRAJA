from flask_restful import Resource
from Server.Models.Expenses import Expenses, ExpenseDistribution
from Server.Models.Users import Users
from Server.Models.Accounting.ExpensesLedger import ExpensesLedger
from Server.Models.Shops import Shops
from Server.Models.ExpenseCategory import ExpenseCategory
from Server.Models.BankAccounts import BankAccount, BankingTransaction
from Server.Models.Expenses import CreditPayments           # ✅ Creditor removed
from app import db
from Server.Models.Supplier import SupplierHistory, Suppliers  # ✅ already there
from flask_jwt_extended import jwt_required, get_jwt_identity
from flask import jsonify, request, make_response
from datetime import datetime
from sqlalchemy import and_, or_, func
from math import ceil
from functools import wraps
from sqlalchemy.exc import SQLAlchemyError
import uuid
from Server.Views.Services.sasapay_service import SasaPayPaymentService
sasapay_service = SasaPayPaymentService()


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


def _recalc_supplier_totals(supplier):
    """Recalculate a supplier's total_amount_received and credit_amount
    from its linked expenses. Replaces the old Creditor.update_totals()."""
    if not supplier:
        return
    total_owed = db.session.query(func.sum(Expenses.totalPrice)).filter(
        Expenses.supplier_id == supplier.supplier_id
    ).scalar() or 0.0
    total_paid = db.session.query(func.sum(Expenses.amountPaid)).filter(
        Expenses.supplier_id == supplier.supplier_id
    ).scalar() or 0.0
    supplier.total_amount_received = total_paid
    supplier.credit_amount = max(0.0, total_owed - total_paid)


class AddExpense(Resource):
    @jwt_required()
    @check_role('manager')
    def post(self):
        data = request.get_json()
        current_user_id = get_jwt_identity()

        shop_id = data.get('shop_id')
        supplier_id = data.get('supplier_id')  # ✅ replaced creditor_id

        # New supplier fields (if creating new supplier)
        supplier_name = data.get('supplier_name') or data.get('Suppliername')
        supplier_phone = data.get('supplier_phone') or data.get('phone_number')
        supplier_email = data.get('supplier_email') or data.get('email')
        supplier_location = data.get('supplier_location') or data.get('Supplier_location')

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

        distribute_to_shops = data.get('distribute_to_shops', [])
        is_distribution = data.get('is_distribution', False)

        # ===== Validations =====
        if not shop_id or not category or not source or not paymentRef:
            return {"message": "Missing required fields"}, 400

        if amountPaid > totalPrice:
            return {"message": "Amount paid cannot exceed total price"}, 400

        try:
            created_at = datetime.strptime(created_at_str, "%Y-%m-%d") if created_at_str else datetime.now()
        except:
            return {"message": "Invalid date format. Use YYYY-MM-DD."}, 400

        try:
            # ===== Step 1: Handle Supplier creation or validation =====
            supplier = None

            if supplier_id:
                supplier = Suppliers.query.get(supplier_id)
                if not supplier:
                    return {"message": f"Supplier with ID {supplier_id} not found"}, 404
            elif supplier_name:
                if not supplier_phone:
                    return {"message": "Phone number is required for new supplier"}, 400

                # Try find by name + location (same pattern as inventory)
                supplier = Suppliers.query.filter_by(
                    supplier_name=supplier_name,
                    supplier_location=supplier_location,
                    supplier_type='expenses'
                ).first()

                if not supplier:
                    supplier = Suppliers(
                        supplier_name=supplier_name,
                        supplier_location=supplier_location or "Unknown",
                        phone_number=supplier_phone,
                        email=supplier_email,
                        supplier_type='expenses',
                        credit_amount=0.0,
                        items_sold=[],
                    )
                    db.session.add(supplier)
                    db.session.flush()

            # ===== Step 2: Bank deduction =====
            if amountPaid > 0:
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

            # ===== Step 3: Payment status =====
            if amountPaid == 0:
                payment_status = 'pending'
            elif amountPaid >= totalPrice:
                payment_status = 'paid'
            else:
                payment_status = 'partial'

            # ===== Step 4: Create Expense =====
            new_expense = Expenses(
                shop_id=shop_id,
                supplier_id=supplier.supplier_id if supplier else None,  # ✅
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
                payment_status=payment_status,
                distribution_status='none'
            )
            db.session.add(new_expense)
            db.session.flush()

            # ===== Step 5: Initial payment record =====
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

            # ===== Step 6: Supplier history (mirrors inventory flow) =====
            if supplier:
                supplier_history = SupplierHistory(
                    supplier_id=supplier.supplier_id,
                    amount_received=amountPaid,
                    transaction_date=datetime.utcnow(),
                    item_bought=item or description or "Expense",
                    payment_status=payment_status,
                    credit_amount=max(0.0, totalPrice - amountPaid),
                    inventory_id=None,
                )
                db.session.add(supplier_history)
                _recalc_supplier_totals(supplier)

            # ===== Step 7: Distribution =====
            distribution_results = []
            if is_distribution and distribute_to_shops:
                total_distributed_qty = sum(d.get('quantity', 0) for d in distribute_to_shops)
                if total_distributed_qty > quantity:
                    db.session.rollback()
                    return {
                        "message": f"Total distribution quantity ({total_distributed_qty}) exceeds expense quantity ({quantity})"
                    }, 400

                per_unit_price = totalPrice / quantity if quantity > 0 else 0

                for dist in distribute_to_shops:
                    target_shop_id = dist.get('shop_id')
                    dist_quantity = dist.get('quantity', 0)
                    dist_notes = dist.get('notes', '')
                    if dist_quantity <= 0:
                        continue

                    dist_amount = dist_quantity * per_unit_price

                    distributed_expense = Expenses(
                        shop_id=target_shop_id,
                        supplier_id=supplier.supplier_id if supplier else None,  # ✅
                        item=item,
                        description=f"{description} (Distributed from Shop {shop_id})",
                        category=category,
                        quantity=dist_quantity,
                        totalPrice=dist_amount,
                        amountPaid=dist_amount,
                        paidTo=paidTo,
                        created_at=created_at,
                        user_id=current_user_id,
                        source=f"DISTRIBUTED_FROM_{new_expense.expense_id}",
                        paymentRef=paymentRef,
                        comments=f"Distributed from original expense #{new_expense.expense_id}. {dist_notes}" if dist_notes else f"Distributed from original expense #{new_expense.expense_id}",
                        payment_status='paid',
                        distribution_status='received'
                    )
                    db.session.add(distributed_expense)
                    db.session.flush()

                    distribution_record = ExpenseDistribution(
                        original_expense_id=new_expense.expense_id,
                        distributed_to_shop_id=target_shop_id,
                        distributed_quantity=dist_quantity,
                        distributed_amount=dist_amount,
                        original_quantity_before=quantity,
                        original_amount_before=totalPrice,
                        distributed_by=current_user_id,
                        notes=dist_notes
                    )
                    db.session.add(distribution_record)

                    distribution_results.append({
                        'to_shop_id': target_shop_id,
                        'quantity': dist_quantity,
                        'amount': dist_amount,
                        'new_expense_id': distributed_expense.expense_id,
                        'distribution_id': distribution_record.distribution_id
                    })

                if total_distributed_qty >= quantity - 0.001:
                    new_expense.distribution_status = 'fully_distributed'
                    new_expense.source = f"DISTRIBUTED_{new_expense.source}" if not new_expense.source.startswith('DISTRIBUTED_') else new_expense.source
                    new_expense.comments = f"[DISTRIBUTED] {new_expense.comments}" if new_expense.comments else "[DISTRIBUTED]"
                    new_expense.quantity = 0
                    new_expense.totalPrice = 0
                    new_expense.amountPaid = 0
                    new_expense.payment_status = 'distributed'
                else:
                    new_expense.distribution_status = 'partial'
                    new_expense.quantity = quantity - total_distributed_qty
                    new_expense.totalPrice = totalPrice - sum(d['amount'] for d in distribution_results)
                    if new_expense.amountPaid > new_expense.totalPrice:
                        new_expense.amountPaid = new_expense.totalPrice
                    new_expense.update_payment_status()

            # ===== Step 8: Recalc supplier totals =====
            if supplier:
                _recalc_supplier_totals(supplier)

            db.session.commit()

            # ===== Step 9: Journal =====
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

            response_data = {
                "message": "Expense and journal entry added successfully",
                "expense_id": new_expense.expense_id,
                "total_price": totalPrice,
                "amount_paid": amountPaid,
                "outstanding_balance": new_expense.outstanding_balance,
                "payment_status": payment_status,
                "journal_entry": journal_result
            }

            if is_distribution and distribution_results:
                response_data["distribution"] = {
                    "is_distribution": True,
                    "distributed_to": distribution_results,
                    "original_expense_updated": {
                        "remaining_quantity": new_expense.quantity,
                        "remaining_amount": new_expense.totalPrice
                    }
                }

            if supplier:
                response_data["supplier"] = {   # ✅ renamed from "creditor"
                    "supplier_id": supplier.supplier_id,
                    "supplier_name": supplier.supplier_name,
                    "phone_number": supplier.phone_number,
                    "supplier_type": supplier.supplier_type,
                    "outstanding_balance": max(0.0, supplier.credit_amount),
                    "is_new": not supplier_id
                }

            return response_data, 201

        except Exception as e:
            db.session.rollback()
            return {"message": "Error adding expense", "error": str(e)}, 500


class AllExpenses(Resource):
    @jwt_required()
    @check_role('manager')
    def get(self):
        page = request.args.get('page', 1, type=int)
        per_page = int(request.args.get('per_page', request.args.get('limit', 50)))
        search_query = request.args.get('searchQuery', '')
        category = request.args.get('category', type=str)
        shopname = request.args.get('shopname', type=str)
        supplier_id = request.args.get('supplier_id', type=int)  # ✅
        payment_status = request.args.get('payment_status', type=str)
        paymentRef = request.args.get('paymentRef', type=str)
        start_date = request.args.get('start_date', type=str)
        end_date = request.args.get('end_date', type=str)

        query = Expenses.query

        if search_query:
            query = Expenses.query.filter(
                or_(
                    Expenses.category.ilike(f"%{search_query}%"),
                    Expenses.item.ilike(f"%{search_query}%"),
                    Expenses.paidTo.ilike(f"%{search_query}%"),
                    Expenses.source.ilike(f"%{search_query}%"),
                    Expenses.paymentRef.ilike(f"%{search_query}%")
                )
            )

        filters = []
        if category:
            filters.append(Expenses.category.ilike(f"%{category}%"))

        if supplier_id:
            filters.append(Expenses.supplier_id == supplier_id)  # ✅

        if payment_status:
            filters.append(Expenses.payment_status == payment_status)

        if paymentRef:
            filters.append(Expenses.paymentRef == paymentRef)

        if shopname:
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

        all_filtered_expenses = query.all()

        total_amount_paid_all = sum(expense.amountPaid for expense in all_filtered_expenses) if all_filtered_expenses else 0
        total_outstanding_all = sum(expense.outstanding_balance or 0 for expense in all_filtered_expenses) if all_filtered_expenses else 0
        total_count_all = len(all_filtered_expenses)
        avg_expense_all = total_amount_paid_all / total_count_all if total_count_all > 0 else 0

        query = query.order_by(Expenses.created_at.desc())
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        expenses = pagination.items

        all_expenses = []
        for expense in expenses:
            user = Users.query.filter_by(users_id=expense.user_id).first()
            shop = Shops.query.filter_by(shops_id=expense.shop_id).first()
            supplier = Suppliers.query.get(expense.supplier_id) if expense.supplier_id else None  # ✅

            payments = CreditPayments.query.filter_by(expense_id=expense.expense_id).all()
            total_payments = len(payments)
            total_paid_from_payments = sum(p.amount for p in payments)

            username = user.username if user else "Unknown User"
            shop_name = shop.shopname if shop else "Unknown Shop"
            supplier_name = supplier.supplier_name if supplier else None  # ✅

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
                "supplier_id": expense.supplier_id,       # ✅
                "supplier_name": supplier_name,           # ✅
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
                "distribution_status": expense.distribution_status,
                "payment_summary": {
                    "total_payments": total_payments,
                    "total_paid": total_paid_from_payments,
                    "sources": list(set(p.source for p in payments if p.source))
                }
            })

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
            "pagination": pagination_info,
            "total_amount_paid_all_expenses": total_amount_paid_all,
            "total_outstanding_all_expenses": total_outstanding_all,
            "total_count_all_expenses": total_count_all,
            "average_expense_all": avg_expense_all
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
            "supplier_id": expense.supplier_id,   # ✅
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
            "distribution_status": expense.distribution_status,
            "created_at": expense.created_at.strftime('%Y-%m-%d %H:%M:%S') if expense.created_at else None
        } for expense in shopExpenses]

        return make_response(jsonify(expensesForShop), 200)


class ExpensesResources(Resource):
    @jwt_required()
    @check_role('manager')
    def get(self, expense_id):
        expense = Expenses.query.get(expense_id)

        if expense:
            supplier = Suppliers.query.get(expense.supplier_id) if expense.supplier_id else None  # ✅

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

            distributions = ExpenseDistribution.query.filter_by(original_expense_id=expense_id).all()
            distribution_history = [
                {
                    "distribution_id": d.distribution_id,
                    "to_shop_id": d.distributed_to_shop_id,
                    "to_shop_name": Shops.query.get(d.distributed_to_shop_id).shopname if Shops.query.get(d.distributed_to_shop_id) else "Unknown",
                    "quantity": d.distributed_quantity,
                    "amount": d.distributed_amount,
                    "distributed_date": d.distributed_date.strftime('%Y-%m-%d %H:%M:%S'),
                    "notes": d.notes
                } for d in distributions
            ]

            return {
                "expense_id": expense.expense_id,
                "user_id": expense.user_id,
                "shop_id": expense.shop_id,
                "supplier_id": expense.supplier_id,       # ✅
                "supplier_name": supplier.supplier_name if supplier else None,  # ✅
                "item": expense.item,
                "description": expense.description,
                "category": expense.category,
                "quantity": expense.quantity,
                "totalPrice": expense.totalPrice,
                "paidTo": expense.paidTo,
                "amountPaid": expense.amountPaid,
                "outstanding_balance": expense.outstanding_balance,
                "payment_status": expense.payment_status,
                "distribution_status": expense.distribution_status,
                "source": expense.source,
                "paymentRef": expense.paymentRef,
                "comments": expense.comments,
                "created_at": expense.created_at.strftime('%Y-%m-%d %H:%M:%S') if expense.created_at else None,
                "payment_history": payment_history,
                "distribution_history": distribution_history,
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

        old_amount = expense.totalPrice
        old_category = expense.category
        old_date = expense.created_at
        old_supplier_id = expense.supplier_id   # ✅

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
        expense.supplier_id = data.get('supplier_id', expense.supplier_id)  # ✅

        expense.update_payment_status()

        if 'created_at' in data:
            try:
                expense.created_at = datetime.strptime(data['created_at'], '%Y-%m-%d %H:%M:%S')
            except ValueError:
                expense.created_at = datetime.strptime(data['created_at'], '%Y-%m-%d')

        ledger_entries = ExpensesLedger.query.filter_by(expense_id=expense_id).all()
        for ledger in ledger_entries:
            if expense.totalPrice != old_amount:
                ledger.amount = expense.totalPrice
            if expense.created_at != old_date:
                ledger.created_at = expense.created_at
            if expense.category != old_category:
                category_obj = ExpenseCategory.query.filter_by(name=expense.category).first()
                if category_obj:
                    ledger.category_id = category_obj.id
                    ledger.debit_account_id = category_obj.debit_account_id
                    ledger.credit_account_id = category_obj.credit_account_id

        # ✅ replace Creditor.update_totals
        if expense.supplier_id != old_supplier_id:
            if old_supplier_id:
                _recalc_supplier_totals(Suppliers.query.get(old_supplier_id))
            if expense.supplier_id:
                _recalc_supplier_totals(Suppliers.query.get(expense.supplier_id))

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

        supplier_id = expense.supplier_id  # ✅

        CreditPayments.query.filter_by(expense_id=expense_id).delete()
        ExpensesLedger.query.filter_by(expense_id=expense_id).delete()
        ExpenseDistribution.query.filter_by(original_expense_id=expense_id).delete()

        db.session.delete(expense)

        if supplier_id:
            _recalc_supplier_totals(Suppliers.query.get(supplier_id))  # ✅

        db.session.commit()

        return {"message": "Expense and related records deleted successfully"}, 200


class TotalBalance(Resource):
    @jwt_required()
    @check_role('manager')
    def get(self):
        try:
            start_date_str = request.args.get('start_date')
            end_date_str = request.args.get('end_date')
            supplier_id = request.args.get('supplier_id', type=int)  # ✅

            start_date = datetime.strptime(start_date_str.strip(), '%Y-%m-%d') if start_date_str else None
            end_date = datetime.strptime(end_date_str.strip(), '%Y-%m-%d') if end_date_str else None

            query = Expenses.query
            if start_date:
                query = query.filter(Expenses.created_at >= start_date)
            if end_date:
                query = query.filter(Expenses.created_at <= end_date)
            if supplier_id:
                query = query.filter(Expenses.supplier_id == supplier_id)  # ✅

            expenses = query.all()

            total_balance = sum(expense.outstanding_balance for expense in expenses)

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
        data = request.get_json()
        current_user_id = get_jwt_identity()

        expense = Expenses.query.get(expense_id)
        if not expense:
            return {"error": "Expense not found"}, 404

        amount = data.get('amount')
        payment_ref = data.get('payment_ref')
        payment_method = data.get('payment_method', 'Cash')
        notes = data.get('notes')
        source = data.get('source')

        if not amount or amount <= 0:
            return {"error": "Invalid payment amount"}, 400
        if not payment_ref:
            return {"error": "Payment reference is required"}, 400
        if not source:
            return {"error": "Payment source is required"}, 400
        if amount > expense.outstanding_balance:
            return {"error": f"Payment amount exceeds outstanding balance of {expense.outstanding_balance}"}, 400

        try:
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

            expense.amountPaid += amount
            expense.update_payment_status()

            if expense.supplier_id:   # ✅
                _recalc_supplier_totals(Suppliers.query.get(expense.supplier_id))

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


class DistributeExpense(Resource):
    @jwt_required()
    @check_role('manager')
    def post(self, expense_id):
        data = request.get_json()
        current_user_id = get_jwt_identity()

        original_expense = Expenses.query.get(expense_id)
        if not original_expense:
            return {"error": "Expense not found"}, 404

        distribute_to_shops = data.get('distribute_to_shops', [])
        if not distribute_to_shops:
            return {"error": "No distribution targets provided"}, 400

        total_distributed_qty = sum(d.get('quantity', 0) for d in distribute_to_shops)
        if total_distributed_qty > original_expense.quantity:
            return {
                "error": f"Total distribution quantity ({total_distributed_qty}) exceeds expense quantity ({original_expense.quantity})"
            }, 400

        try:
            per_unit_price = original_expense.totalPrice / original_expense.quantity if original_expense.quantity > 0 else 0
            distribution_results = []

            for dist in distribute_to_shops:
                target_shop_id = dist.get('shop_id')
                dist_quantity = dist.get('quantity', 0)
                dist_notes = dist.get('notes', '')
                if dist_quantity <= 0:
                    continue

                dist_amount = dist_quantity * per_unit_price

                distributed_expense = Expenses(
                    shop_id=target_shop_id,
                    supplier_id=original_expense.supplier_id,   # ✅
                    item=original_expense.item,
                    description=f"{original_expense.description} (Distributed from Shop {original_expense.shop_id})",
                    category=original_expense.category,
                    quantity=dist_quantity,
                    totalPrice=dist_amount,
                    amountPaid=dist_amount,
                    paidTo=original_expense.paidTo,
                    created_at=datetime.now(),
                    user_id=current_user_id,
                    source=f"DISTRIBUTED_FROM_{expense_id}",
                    paymentRef=original_expense.paymentRef,
                    comments=f"Distributed from original expense #{expense_id}. {dist_notes}" if dist_notes else f"Distributed from original expense #{expense_id}",
                    payment_status='paid',
                    distribution_status='received'
                )
                db.session.add(distributed_expense)
                db.session.flush()

                distribution_record = ExpenseDistribution(
                    original_expense_id=expense_id,
                    distributed_to_shop_id=target_shop_id,
                    distributed_quantity=dist_quantity,
                    distributed_amount=dist_amount,
                    original_quantity_before=original_expense.quantity,
                    original_amount_before=original_expense.totalPrice,
                    distributed_by=current_user_id,
                    notes=dist_notes
                )
                db.session.add(distribution_record)

                distribution_results.append({
                    'to_shop_id': target_shop_id,
                    'quantity': dist_quantity,
                    'amount': dist_amount,
                    'new_expense_id': distributed_expense.expense_id,
                    'distribution_id': distribution_record.distribution_id
                })

            remaining_quantity = original_expense.quantity - total_distributed_qty
            remaining_amount = original_expense.totalPrice - sum(d['amount'] for d in distribution_results)

            if remaining_quantity <= 0.001:
                original_expense.distribution_status = 'fully_distributed'
                original_expense.quantity = 0
                original_expense.totalPrice = 0
                original_expense.amountPaid = 0
                original_expense.payment_status = 'distributed'
            else:
                original_expense.distribution_status = 'partial'
                original_expense.quantity = remaining_quantity
                original_expense.totalPrice = remaining_amount
                if original_expense.amountPaid > remaining_amount:
                    original_expense.amountPaid = remaining_amount
                original_expense.update_payment_status()

            db.session.commit()

            return {
                "message": "Expense distributed successfully",
                "original_expense_id": expense_id,
                "original_expense_updated": {
                    "remaining_quantity": original_expense.quantity,
                    "remaining_amount": original_expense.totalPrice,
                    "distribution_status": original_expense.distribution_status
                },
                "distributions": distribution_results
            }, 200

        except Exception as e:
            db.session.rollback()
            return {"error": f"Failed to distribute expense: {str(e)}"}, 500


class GetExpenseDistributions(Resource):
    @jwt_required()
    @check_role('manager')
    def get(self, expense_id):
        try:
            expense = Expenses.query.get(expense_id)
            if not expense:
                return {"error": "Expense not found"}, 404

            distributions = ExpenseDistribution.query.filter_by(original_expense_id=expense_id).all()

            distribution_list = []
            for dist in distributions:
                target_shop = Shops.query.get(dist.distributed_to_shop_id)
                distributor = Users.query.get(dist.distributed_by)

                distribution_list.append({
                    "distribution_id": dist.distribution_id,
                    "to_shop_id": dist.distributed_to_shop_id,
                    "to_shop_name": target_shop.shopname if target_shop else "Unknown",
                    "quantity": dist.distributed_quantity,
                    "amount": dist.distributed_amount,
                    "distributed_date": dist.distributed_date.strftime('%Y-%m-%d %H:%M:%S'),
                    "distributed_by": distributor.username if distributor else "Unknown",
                    "original_quantity_before": dist.original_quantity_before,
                    "original_amount_before": dist.original_amount_before,
                    "notes": dist.notes
                })

            return {
                "expense_id": expense_id,
                "original_expense": {
                    "shop_id": expense.shop_id,
                    "shop_name": Shops.query.get(expense.shop_id).shopname if Shops.query.get(expense.shop_id) else "Unknown",
                    "item": expense.item,
                    "original_quantity": expense.quantity + sum(d.distributed_quantity for d in distributions),
                    "current_quantity": expense.quantity,
                    "distribution_status": expense.distribution_status
                },
                "distributions": distribution_list,
                "total_distributed": len(distribution_list)
            }, 200

        except Exception as e:
            return {"error": str(e)}, 500


class GetShopReceivedDistributions(Resource):
    @jwt_required()
    @check_role('manager')
    def get(self, shop_id):
        try:
            shop = Shops.query.get(shop_id)
            if not shop:
                return {"error": "Shop not found"}, 404

            received_expenses = Expenses.query.filter_by(
                shop_id=shop_id,
                distribution_status='received'
            ).filter(Expenses.source.like('DISTRIBUTED_FROM_%')).all()

            received_list = []
            for expense in received_expenses:
                original_id = expense.source.replace('DISTRIBUTED_FROM_', '')
                distribution = ExpenseDistribution.query.filter_by(
                    original_expense_id=original_id,
                    distributed_to_shop_id=shop_id
                ).first()

                original_expense = Expenses.query.get(int(original_id)) if original_id.isdigit() else None
                source_shop = Shops.query.get(original_expense.shop_id) if original_expense else None

                received_list.append({
                    "expense_id": expense.expense_id,
                    "original_expense_id": original_id,
                    "source_shop_name": source_shop.shopname if source_shop else "Unknown",
                    "item": expense.item,
                    "quantity": expense.quantity,
                    "amount": expense.totalPrice,
                    "received_date": expense.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                    "distribution_notes": distribution.notes if distribution else None
                })

            return {
                "shop_id": shop_id,
                "shop_name": shop.shopname,
                "received_distributions": received_list,
                "total_received": len(received_list)
            }, 200

        except Exception as e:
            return {"error": str(e)}, 500


# ============================================================
# Creditor endpoints → Supplier-based replacements
# ============================================================

class GetExpenseSuppliers(Resource):
    """Replaces GetCreditors. Returns only expense suppliers."""
    @jwt_required()
    def get(self):
        try:
            suppliers = Suppliers.query.filter_by(supplier_type='expenses').all()

            suppliers_list = [{
                "supplier_id": s.supplier_id,
                "supplier_name": s.supplier_name,
                "phone_number": s.phone_number,
                "email": s.email,
                "supplier_location": s.supplier_location,
                "total_amount_received": s.total_amount_received,
                "credit_amount": s.credit_amount,
                "items_sold": s.items_sold or [],
            } for s in suppliers]

            return make_response(jsonify({
                "status": "success",
                "suppliers": suppliers_list,
                "total_suppliers": len(suppliers_list)
            }), 200)

        except Exception as e:
            return make_response(jsonify({"status": "error", "message": str(e)}), 500)


class GetExpenseSupplierDetails(Resource):
    """Replaces GetCreditorDetails."""
    @jwt_required()
    def get(self, supplier_id):
        try:
            supplier = Suppliers.query.filter_by(
                supplier_id=supplier_id,
                supplier_type='expenses'
            ).first()

            if not supplier:
                return make_response(jsonify({"status": "error", "message": "Supplier not found"}), 404)

            expenses = Expenses.query.filter_by(supplier_id=supplier_id).all()

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
                "supplier": {
                    "supplier_id": supplier.supplier_id,
                    "supplier_name": supplier.supplier_name,
                    "phone_number": supplier.phone_number,
                    "email": supplier.email,
                    "supplier_location": supplier.supplier_location,
                    "total_amount_received": supplier.total_amount_received,
                    "credit_amount": supplier.credit_amount,
                    "items_sold": supplier.items_sold or [],
                },
                "expenses": expenses_list,
                "total_expenses": len(expenses_list)
            }), 200)

        except Exception as e:
            return make_response(jsonify({"status": "error", "message": str(e)}), 500)


class CreateExpenseSupplier(Resource):
    """Replaces CreateExpenseCreditor."""
    @jwt_required()
    def post(self):
        try:
            data = request.get_json()

            if not data.get('supplier_name'):
                return make_response(jsonify({"status": "error", "message": "supplier_name is required"}), 400)
            if not data.get('phone_number'):
                return make_response(jsonify({"status": "error", "message": "phone_number is required"}), 400)

            existing = Suppliers.query.filter_by(
                supplier_name=data['supplier_name'],
                phone_number=data['phone_number'],
                supplier_type='expenses'
            ).first()

            if existing:
                return make_response(jsonify({
                    "status": "error",
                    "message": f"Expense supplier with name '{data['supplier_name']}' and phone '{data['phone_number']}' already exists"
                }), 400)

            new_supplier = Suppliers(
                supplier_name=data['supplier_name'],
                supplier_location=data.get('supplier_location', 'Unknown'),
                phone_number=data['phone_number'],
                email=data.get('email'),
                supplier_type='expenses',
                items_sold=data.get('items_sold', []),
            )
            db.session.add(new_supplier)
            db.session.commit()

            return make_response(jsonify({
                "status": "success",
                "message": "Supplier created successfully",
                "supplier": {
                    "supplier_id": new_supplier.supplier_id,
                    "supplier_name": new_supplier.supplier_name,
                    "phone_number": new_supplier.phone_number,
                    "email": new_supplier.email,
                    "supplier_location": new_supplier.supplier_location,
                }
            }), 201)

        except Exception as e:
            db.session.rollback()
            return make_response(jsonify({"status": "error", "message": str(e)}), 500)


class UpdateExpenseSupplier(Resource):
    """Replaces UpdateCreditor."""
    @jwt_required()
    def put(self, supplier_id):
        try:
            supplier = Suppliers.query.filter_by(
                supplier_id=supplier_id,
                supplier_type='expenses'
            ).first()

            if not supplier:
                return make_response(jsonify({"status": "error", "message": "Supplier not found"}), 404)

            data = request.get_json()
            if 'supplier_name' in data:
                supplier.supplier_name = data['supplier_name']
            if 'phone_number' in data:
                supplier.phone_number = data['phone_number']
            if 'email' in data:
                supplier.email = data['email']
            if 'supplier_location' in data:
                supplier.supplier_location = data['supplier_location']
            if 'items_sold' in data:
                supplier.items_sold = data['items_sold']

            db.session.commit()

            return make_response(jsonify({
                "status": "success",
                "message": "Supplier updated successfully",
                "supplier": {
                    "supplier_id": supplier.supplier_id,
                    "supplier_name": supplier.supplier_name,
                    "phone_number": supplier.phone_number,
                    "email": supplier.email,
                    "supplier_location": supplier.supplier_location,
                    "items_sold": supplier.items_sold or [],
                }
            }), 200)

        except Exception as e:
            db.session.rollback()
            return make_response(jsonify({"status": "error", "message": str(e)}), 500)


class DeleteExpenseSupplier(Resource):
    """Replaces DeleteCreditor. Refuses to delete a supplier that has expenses linked."""
    @jwt_required()
    def delete(self, supplier_id):
        try:
            supplier = Suppliers.query.filter_by(
                supplier_id=supplier_id,
                supplier_type='expenses'
            ).first()

            if not supplier:
                return make_response(jsonify({"status": "error", "message": "Supplier not found"}), 404)

            expense_count = Expenses.query.filter_by(supplier_id=supplier_id).count()
            if expense_count > 0:
                return make_response(jsonify({
                    "status": "error",
                    "message": f"Cannot delete supplier with {expense_count} linked expense(s). "
                               "Reassign or delete those expenses first."
                }), 400)

            db.session.delete(supplier)
            db.session.commit()

            return make_response(jsonify({
                "status": "success",
                "message": "Supplier deleted successfully"
            }), 200)

        except Exception as e:
            db.session.rollback()
            return make_response(jsonify({"status": "error", "message": str(e)}), 500)


# SasaPayProcessExpensePayment class — unchanged from your current version;
# it already uses supplier_id. Leave it as-is.
        

class SasaPayProcessExpensePayment(Resource):
    """
    Pays a supplier's outstanding EXPENSE balance via SasaPay, using the
    supplier's stored payment_method (till / paybill / send_money) instead
    of a manual bank entry. On success, the SasaPay request ID becomes the
    payment_reference.

    Mirror of SasaPayProcessPayment (inventory), but:
        - Uses Expenses instead of InventoryV2
        - Uses expense.supplier_id directly (no name+location lookup)
        - Writes a CreditPayments record (that's what the expense flow uses
          to track partial payments) instead of an InventoryPayment record
        - Updates expense.amountPaid / payment_status instead of inventory.ballance

    Channel routing:
        - till        -> B2C to supplier.till_number    (channel = supplier.bank_code)
        - paybill     -> B2C to supplier.paybill_number (channel = supplier.bank_code)
        - send_money  -> B2C to supplier.mobile_number  (channel = supplier.bank_code)

    The channel (network) is ALWAYS taken from the supplier's stored
    bank_name / bank_code. No channel is hardcoded in this endpoint.
    """

    @jwt_required()
    def post(self):
        data = request.get_json()

        required_fields = [
            'expense_id', 'amount_paid', 'source_account', 'sasapay_merchant_code'
        ]
        if not all(field in data for field in required_fields):
            return {'message': 'Missing required fields'}, 400

        expense_id = data.get('expense_id')
        amount_paid = float(data.get('amount_paid'))
        source_account = data.get('source_account')
        sasapay_merchant_code = data.get('sasapay_merchant_code')
        notes = data.get('notes', '')
        current_user_id = get_jwt_identity()

        try:
            # ---- Validate expense ----
            expense = Expenses.query.get(expense_id)
            if not expense:
                return {'message': 'Expense not found'}, 404

            if expense.supplier_id is None:
                return {
                    'message': 'This expense is not linked to a supplier. '
                               'Only supplier-linked expenses can be paid via SasaPay.'
                }, 400

            if expense.outstanding_balance <= 0:
                return {'message': 'This expense has no outstanding balance'}, 400

            if amount_paid <= 0:
                return {'message': 'Payment amount must be greater than 0'}, 400

            if amount_paid > expense.outstanding_balance:
                return {
                    'message': f'Payment amount exceeds outstanding balance '
                               f'of {expense.outstanding_balance}'
                }, 400

            # ---- Get supplier + their SasaPay payment details ----
            supplier = Suppliers.query.get(expense.supplier_id)
            if not supplier:
                return {'message': 'Supplier not found'}, 404

            # ---- Get bank account (funds still tracked against your books) ----
            account = BankAccount.query.filter_by(Account_name=source_account).first()
            if not account:
                return {'message': f'Bank account "{source_account}" not found'}, 404

            if account.Account_Balance < amount_paid:
                return {'message': f'Insufficient balance in account "{source_account}"'}, 400

            # ---- Build our own transaction reference before calling SasaPay ----
            our_reference = f"SUP{supplier.supplier_id}-EXP{expense_id}-{uuid.uuid4().hex[:8]}"

            # ---- Route based on supplier's stored payment_method ----
            raw_method = (supplier.payment_method or '').strip().lower()
            method = 'send_money' if raw_method == 'mobile' else raw_method

            # ---- Channel (network) comes from supplier's bank_name / bank_code ----
            channel_code = (supplier.bank_code or '').strip()
            channel_name = (supplier.bank_name or '').strip()

            if not channel_code and not channel_name:
                return {
                    'message': 'Supplier missing provider details. '
                               'Please set the supplier\'s bank_name and bank_code before paying.'
                }, 400

            if not channel_code:
                return {
                    'message': 'Supplier missing provider bank_code. '
                               'Please set the supplier\'s bank_code before paying.'
                }, 400

            if not channel_name:
                return {
                    'message': 'Supplier missing provider bank_name. '
                               'Please set the supplier\'s bank_name before paying.'
                }, 400

            if method not in ('till', 'paybill', 'send_money'):
                return {
                    'message': f'Supplier has no valid payment_method configured '
                               f'(got "{supplier.payment_method}"). '
                               f'Expected one of: till, paybill, send_money.'
                }, 400

            # ---- Dispatch to SasaPay ----
            if method == 'till':
                if not supplier.till_number:
                    return {'message': 'Supplier has no till_number configured'}, 400

                sasapay_result = sasapay_service.pay_till(
                    sender_merchant_code=sasapay_merchant_code,
                    transaction_reference=our_reference,
                    amount=amount_paid,
                    till_number=supplier.till_number,
                    account_reference=supplier.supplier_name,
                    reason=f"Payment for {expense.item}",
                    channel=channel_code
                )

            elif method == 'paybill':
                if not supplier.paybill_number:
                    return {'message': 'Supplier has no paybill_number configured'}, 400

                sasapay_result = sasapay_service.pay_paybill(
                    sender_merchant_code=sasapay_merchant_code,
                    transaction_reference=our_reference,
                    amount=amount_paid,
                    paybill_number=supplier.paybill_number,
                    account_reference=supplier.paybill_account or supplier.supplier_name,
                    reason=f"Payment for {expense.item}",
                    channel=channel_code
                )

            elif method == 'send_money':
                if not supplier.mobile_number:
                    return {'message': 'Supplier has no mobile_number configured'}, 400

                sasapay_result = sasapay_service.initiate_b2c_payment(
                    sender_merchant_code=sasapay_merchant_code,
                    transaction_reference=our_reference,
                    amount=amount_paid,
                    receiver_number=supplier.mobile_number,
                    reason=f"Payment for {expense.item}",
                    channel=channel_code
                )

            # ---- Bail out if SasaPay rejected the request outright ----
            if not sasapay_result.get('status'):
                return {
                    'message': 'SasaPay payment request failed',
                    'sasapay_response': sasapay_result
                }, 502

            sasapay_data = sasapay_result.get('data', {})
            payment_reference = (
                sasapay_data.get('B2BRequestID')
                or sasapay_data.get('B2CRequestID')
                or sasapay_data.get('ConversationID')
                or our_reference
            )

            # ---- NOTE: SasaPay has only ACCEPTED the request. Final success/  ----
            # ---- failure arrives later via your callback endpoint. We commit  ----
            # ---- here to mirror SasaPayProcessPayment (inventory). If you want  ----
            # ---- to only finalize on callback, move this block into the       ----
            # ---- callback keyed on payment_reference.                          ----

            # Deduct from bank
            account.Account_Balance -= amount_paid

            # Update expense
            expense.amountPaid += amount_paid
            expense.update_payment_status()

            # Track payment reference chain
            if expense.paymentRef:
                expense.paymentRef = f"{expense.paymentRef}, {payment_reference}"
            else:
                expense.paymentRef = payment_reference

            if source_account not in ["Unknown", "External funding"]:
                expense.source = source_account

            # Record the payment (this is the equivalent of InventoryPayment
            # for the expense flow — CreditPayments is your expense ledger of payments)
            credit_payment = CreditPayments(
                expense_id=expense.expense_id,
                amount=amount_paid,
                payment_ref=payment_reference,
                payment_method=method,
                source=source_account,
                notes=notes or f"SasaPay payment for {expense.item}",
                created_by=current_user_id
            )
            db.session.add(credit_payment)

            # Update supplier totals
            supplier.total_amount_received = (
                (supplier.total_amount_received or 0) + amount_paid
            )
            if supplier.credit_amount:
                supplier.credit_amount = max(0.0, supplier.credit_amount - amount_paid)

            # Bank transaction
            transaction = BankingTransaction(
                account_id=account.id,
                Transaction_type_debit=amount_paid,
                Transaction_type_credit=None,
            )
            db.session.add(transaction)

            # Supplier history (not yet confirmed by SasaPay callback)
            supplier_history = SupplierHistory(
                supplier_id=supplier.supplier_id,
                amount_received=amount_paid,
                transaction_date=datetime.utcnow(),
                item_bought=expense.item,
                payment_status='processing',
                credit_amount=0,
                inventory_id=None,
            )
            db.session.add(supplier_history)

            db.session.commit()

            return {
                'message': 'SasaPay expense payment initiated successfully',
                'expense_id': expense_id,
                'supplier_id': supplier.supplier_id,
                'payment_method': method,
                'channel_code': channel_code,
                'channel_name': channel_name,
                'amount_paid': amount_paid,
                'new_outstanding_balance': expense.outstanding_balance,
                'payment_status': expense.payment_status,
                'payment_reference': payment_reference,
                'credit_payment_id': credit_payment.payment_id,
                'updated_source': expense.source,
                'updated_payment_ref': expense.paymentRef,
                'sasapay_response': sasapay_data
            }, 200

        except Exception as e:
            db.session.rollback()
            return {
                'message': 'Error processing SasaPay expense payment',
                'error': str(e)
            }, 500