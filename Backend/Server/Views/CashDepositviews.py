from flask_restful import Resource
from flask import request, jsonify
from Server.Models.CashDeposit import CashDeposits
from Server.Models.Users import Users
from Server.Models.Shops import Shops
from app import db
from flask_jwt_extended import jwt_required,get_jwt_identity
from flask import jsonify,request,make_response
from functools import wraps
from datetime import datetime  # This is likely what you want
from sqlalchemy.exc import SQLAlchemyError
from Server.Models.Transactions import TranscationType
from Server.Models.BankAccounts import BankAccount

def check_role(required_role):
    def wrapper(fn):
        @wraps(fn)
        def decorator(*args, **kwargs):
            current_user_id = get_jwt_identity()
            user = Users.query.get(current_user_id)
            if user and user.role != required_role:
                 return make_response( jsonify({"error": "Unauthorized access"}), 403 )       
            return fn(*args, **kwargs)
        return decorator
    return wrapper

class AddCashDeposit(Resource):
    @jwt_required()
    def post(self):
        data = request.get_json()
        current_user_id = get_jwt_identity()

        try:
            amount = float(data.get('amount'))
        except (TypeError, ValueError):
            return {"message": "Amount must be a valid number."}, 400

        try:
            deductions = float(data.get('deductions', 0))
        except (TypeError, ValueError):
            return {"message": "Deductions must be a valid number."}, 400

        try:
            shop_id = int(data.get('shop_id'))
        except (TypeError, ValueError):
            return {"message": "Shop ID must be a valid integer."}, 400

        reason = data.get('reason')
        transaction_code = data.get('transaction_code')
        created_at = data.get('created_at')

        if amount <= 0:
            return {"message": "Amount must be greater than 0."}, 400
        if deductions < 0:
            return {"message": "Deductions cannot be negative."}, 400

        if created_at:
            try:
                created_at = datetime.strptime(created_at, "%Y-%m-%d")
            except ValueError:
                return {"message": "Invalid date format. Use YYYY-MM-DD."}, 400
        else:
            created_at = datetime.utcnow()

        deposit = CashDeposits(
            user_id=current_user_id,
            shop_id=shop_id,
            amount=amount,
            deductions=deductions,
            reason=reason,
            transaction_code=transaction_code,
            created_at=created_at
        )

        try:
            db.session.add(deposit)

            # ===== BANK MAPPING =====
            shop_to_bank_mapping = {
                1: 12, 2: 3, 3: 6, 4: 2, 5: 5, 6: 17,
                7: 15, 8: 9, 10: 18, 11: 8, 12: 7,
                14: 14, 16: 13, 19: 22, 20: 23
            }

            net_amount = amount - deductions

            # Get corresponding bank ID
            bank_id = shop_to_bank_mapping.get(shop_id)
            if not bank_id:
                return {"message": f"No bank mapping found for shop ID {shop_id}"}, 400

            # Update the bank account balance
            bank_account = BankAccount.query.get(bank_id)
            if not bank_account:
                return {"message": f"No bank account found with ID {bank_id}"}, 400

            previous_balance = bank_account.Account_Balance
            bank_account.Account_Balance += net_amount
            db.session.add(bank_account)

            # Log transaction
            transaction = TranscationType(
                Transaction_type="Debit",
                Transaction_amount=net_amount,
                From_account=f"Cash Deposit #{deposit.deposit_id}",
                To_account=bank_account.Account_name,
                created_at=created_at
            )
            db.session.add(transaction)

            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            return {"message": "Database error", "details": str(e)}, 500

        return {
            "message": "Cash deposit recorded successfully",
            "deposit_id": deposit.deposit_id,
            "net_deposited": net_amount,
            "bank_account": bank_account.Account_name,
            "previous_balance": previous_balance,
            "new_balance": bank_account.Account_Balance
        }, 201




class CashDepositResource(Resource):
    @jwt_required()
    @check_role('manager')
    def post(self):
        data = request.get_json()
        current_user_id = get_jwt_identity()

        shop_id = data.get('shop_id')
        amount = data.get('amount')
        deductions = data.get('deductions', 0)
        transaction_code = data.get('transaction_code')
        reason = data.get('reason')

        # Validate required fields
        if not shop_id:
            return {"message": "Shop ID is required."}, 400
        if amount is None or amount <= 0:
            return {"message": "Amount must be a number greater than 0."}, 400
        if deductions is None:
            deductions = 0
        if reason is None or reason.strip() == "":
            return {"message": "Reason is required."}, 400
        if transaction_code is None or transaction_code.strip() == "":
            return {"message": "Transaction code is required."}, 400


        created_at_str = data.get('created_at')
        created_at = None
        if created_at_str:
            try:
                created_at = datetime.datetime.strptime(created_at_str, '%Y-%m-%d')
            except ValueError:
                return {"message": "Invalid date format. Use YYYY-MM-DD."}, 400

        new_deposit = CashDeposits(
            user_id=current_user_id,
            shop_id=shop_id,
            amount=amount,
            deductions=deductions,
            reason=reason,
            transaction_code=transaction_code,
            created_at=created_at or datetime.datetime.utcnow()
        )

        db.session.add(new_deposit)
        db.session.commit()

        return {"message": "Cash deposit added successfully.", "deposit_id": new_deposit.deposit_id}, 201

    @jwt_required()
    @check_role('manager')
    def get(self):
        deposits = CashDeposits.query.order_by(CashDeposits.created_at.desc()).all()
        all_deposits = []

        for deposit in deposits:
            user = Users.query.filter_by(users_id=deposit.user_id).first()
            shop = Shops.query.filter_by(shops_id=deposit.shop_id).first()

            username = user.username if user else "Unknown User"
            shopname = shop.shopname if shop else "Unknown Shop"

            # Simplified datetime handling
            created_at = deposit.created_at.strftime('%Y-%m-%d %H:%M:%S') if deposit.created_at else None

            all_deposits.append({
                "deposit_id": deposit.deposit_id,
                "user_id": deposit.user_id,
                "username": username,
                "shop_id": deposit.shop_id,
                "shop_name": shopname,
                "amount": float(deposit.amount),  # Ensure numeric values are serializable
                "deductions": float(deposit.deductions) if deposit.deductions is not None else None,
                "reason": deposit.reason,
                "transaction_code": deposit.transaction_code,
                "created_at": created_at
            })

        return make_response(jsonify(all_deposits), 200)

    @jwt_required()
    @check_role('manager')
    def put(self, deposit_id):
        deposit = CashDeposits.query.filter_by(deposit_id=deposit_id).first()
        if not deposit:
            return {"message": "Deposit not found."}, 404

        data = request.get_json()

        shop_id = data.get('shop_id')
        amount = data.get('amount')
        deductions = data.get('deductions')
        reason = data.get('reason')
        transaction_code = data.get('transaction_code')
        created_at_str = data.get('created_at')

        if shop_id:
            deposit.shop_id = shop_id
        if amount is not None:
            if amount <= 0:
                return {"message": "Amount must be greater than 0."}, 400
            deposit.amount = amount
        if deductions is not None:
            deposit.deductions = deductions
        if reason:
            deposit.reason = reason
        if transaction_code:
            deposit.transaction_code = transaction_code
        if created_at_str:
            try:
                deposit.created_at = datetime.datetime.strptime(created_at_str, '%Y-%m-%d')
            except ValueError:
                return {"message": "Invalid date format. Use YYYY-MM-DD."}, 400

        db.session.commit()

        return {"message": "Cash deposit updated successfully."}, 200

    @jwt_required()
    @check_role('manager')
    def delete(self, deposit_id):
        deposit = CashDeposits.query.filter_by(deposit_id=deposit_id).first()
        if not deposit:
            return {"message": "Deposit not found."}, 404

        db.session.delete(deposit)
        db.session.commit()

        return {"message": "Cash deposit deleted successfully."}, 200



class GetCashDepositsByUser(Resource):
    @jwt_required()
    def get(self, user_id):
        try:
            # Optional deposit_id query parameter
            deposit_id = request.args.get('deposit_id', type=int)

            # Filter deposits by user_id
            query = CashDeposits.query.filter_by(user_id=user_id)

            # If deposit_id is provided, filter by both IDs
            if deposit_id is not None:
                query = query.filter_by(deposit_id=deposit_id)

            deposits = query.order_by(
                CashDeposits.created_at.desc()
            ).all()

            if not deposits:
                return make_response(jsonify({
                    "message": "No cash deposits found for the specified user and deposit ID."
                    if deposit_id is not None
                    else "No cash deposits found for the specified user.",
                    "user_id": user_id,
                    "deposit_id": deposit_id
                }), 404)

            all_deposits = []

            for deposit in deposits:
                user = Users.query.filter_by(
                    users_id=deposit.user_id
                ).first()

                shop = Shops.query.filter_by(
                    shops_id=deposit.shop_id
                ).first()

                username = user.username if user else "Unknown User"
                shopname = shop.shopname if shop else "Unknown Shop"

                created_at = (
                    deposit.created_at.strftime('%Y-%m-%d %H:%M:%S')
                    if deposit.created_at else None
                )

                all_deposits.append({
                    "deposit_id": deposit.deposit_id,
                    "user_id": deposit.user_id,
                    "username": username,
                    "shop_id": deposit.shop_id,
                    "shop_name": shopname,
                    "amount": float(deposit.amount),
                    "deductions": (
                        float(deposit.deductions)
                        if deposit.deductions is not None
                        else None
                    ),
                    "reason": deposit.reason,
                    "transaction_code": deposit.transaction_code,
                    "created_at": created_at
                })

            # Return a single object when deposit_id is specified
            if deposit_id is not None:
                return make_response(jsonify(all_deposits[0]), 200)

            # Otherwise, return all deposits for the user
            return make_response(jsonify(all_deposits), 200)

        except Exception as e:
            return make_response(jsonify({
                "error": f"An error occurred: {str(e)}"
            }), 500)
            
    @jwt_required()
    def put(self, user_id):
        try:
            # deposit_id is required for updating a specific deposit
            deposit_id = request.args.get('deposit_id', type=int)

            if deposit_id is None:
                return make_response(jsonify({
                    "error": "deposit_id is required as a query parameter."
                }), 400)

            # Find the deposit belonging to this user
            deposit = CashDeposits.query.filter_by(
                user_id=user_id,
                deposit_id=deposit_id
            ).first()

            if not deposit:
                return make_response(jsonify({
                    "message": "Cash deposit not found for the specified user.",
                    "user_id": user_id,
                    "deposit_id": deposit_id
                }), 404)

            data = request.get_json(silent=True)

            if not isinstance(data, dict) or not data:
                return make_response(jsonify({
                    "error": "A valid, non-empty JSON object is required."
                }), 400)

            allowed_fields = {
                "amount",
                "deductions",
                "reason",
                "transaction_code"
            }

            invalid_fields = set(data.keys()) - allowed_fields

            if invalid_fields:
                return make_response(jsonify({
                    "error": "One or more fields cannot be updated.",
                    "invalid_fields": sorted(invalid_fields),
                    "allowed_fields": sorted(allowed_fields)
                }), 400)

            # Validate and update amount
            if "amount" in data:
                try:
                    amount = float(data["amount"])

                    if amount < 0:
                        raise ValueError()

                    deposit.amount = amount

                except (TypeError, ValueError):
                    return make_response(jsonify({
                        "error": "amount must be a valid non-negative number."
                    }), 400)

            # Validate and update deductions
            if "deductions" in data:
                if data["deductions"] is None:
                    deposit.deductions = None
                else:
                    try:
                        deductions = float(data["deductions"])

                        if deductions < 0:
                            raise ValueError()

                        deposit.deductions = deductions

                    except (TypeError, ValueError):
                        return make_response(jsonify({
                            "error": "deductions must be a non-negative number or null."
                        }), 400)

            # Update reason
            if "reason" in data:
                if data["reason"] is not None and not isinstance(
                    data["reason"], str
                ):
                    return make_response(jsonify({
                        "error": "reason must be a string or null."
                    }), 400)

                deposit.reason = data["reason"]

            # Update transaction code
            if "transaction_code" in data:
                transaction_code = data["transaction_code"]

                if transaction_code is not None and not isinstance(
                    transaction_code, str
                ):
                    return make_response(jsonify({
                        "error": "transaction_code must be a string or null."
                    }), 400)

                deposit.transaction_code = transaction_code

            db.session.commit()

            # Fetch related user and shop
            user = Users.query.filter_by(
                users_id=deposit.user_id
            ).first()

            shop = Shops.query.filter_by(
                shops_id=deposit.shop_id
            ).first()

            updated_deposit = {
                "message": "Cash deposit updated successfully.",
                "deposit_id": deposit.deposit_id,
                "user_id": deposit.user_id,
                "username": user.username if user else "Unknown User",
                "shop_id": deposit.shop_id,
                "shop_name": shop.shopname if shop else "Unknown Shop",
                "amount": float(deposit.amount),
                "deductions": (
                    float(deposit.deductions)
                    if deposit.deductions is not None else None
                ),
                "reason": deposit.reason,
                "transaction_code": deposit.transaction_code,
                "created_at": (
                    deposit.created_at.strftime('%Y-%m-%d %H:%M:%S')
                    if deposit.created_at else None
                )
            }

            return make_response(jsonify(updated_deposit), 200)

        except Exception as e:
            db.session.rollback()

            return make_response(jsonify({
                "error": f"An error occurred: {str(e)}"
            }), 500)