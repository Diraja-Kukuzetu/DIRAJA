from flask_restful import Resource
from Server.Models.Supplier import Suppliers, SupplierHistory
from app import db
from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError


class AddSupplier(Resource):
    @jwt_required()
    def post(self):
        data = request.get_json()
        current_user_id = get_jwt_identity()

        required_fields = [
            'supplier_name',
            'supplier_location',
            'phone_number'
        ]

        missing_fields = [field for field in required_fields if field not in data]
        if missing_fields:
            return {
                'message': f"Missing fields: {', '.join(missing_fields)}"
            }, 400

        supplier_name = data.get('supplier_name')
        supplier_location = data.get('supplier_location')
        email = data.get('email')  # Optional
        phone_number = data.get('phone_number')  # Optional
        credit_amount = data.get('credit_amount', 0.0)  # Optional credit amount, default to 0

        new_supplier = Suppliers(
            supplier_name=supplier_name,
            supplier_location=supplier_location,
            email=email,
            phone_number=phone_number,
            credit_amount=float(credit_amount)  # Added credit_amount
        )

        db.session.add(new_supplier)

        try:
            db.session.commit()
            return {
                'message': 'Supplier added successfully',
                'supplier_id': new_supplier.supplier_id,
                'credit_amount': new_supplier.credit_amount
            }, 201
        except SQLAlchemyError as e:
            db.session.rollback()
            return {
                'error': 'An error occurred while adding the supplier',
                'details': str(e)
            }, 500


class GetAllSuppliers(Resource):
    @jwt_required()
    def get(self):
        try:
            suppliers = Suppliers.query.all()
            supplier_list = []

            for supplier in suppliers:
                supplier_list.append({
                    'supplier_id': supplier.supplier_id,
                    'supplier_name': supplier.supplier_name,
                    'supplier_location': supplier.supplier_location,
                    'total_amount_received': supplier.total_amount_received,
                    'credit_amount': supplier.credit_amount,  # Added credit_amount
                    'email': supplier.email,
                    'phone_number': supplier.phone_number,
                    'items_sold': supplier.items_sold if supplier.items_sold else []
                })

            return {'suppliers': supplier_list}, 200

        except Exception as e:
            return {
                'error': 'Failed to fetch suppliers',
                'details': str(e)
            }, 500


class GetSingleSupplier(Resource):
    @jwt_required()
    def get(self, supplier_id):
        try:
            supplier = Suppliers.query.filter_by(supplier_id=supplier_id).first()

            if not supplier:
                return {'message': 'Supplier not found'}, 404

            # Get supplier history
            histories = SupplierHistory.query.filter_by(supplier_id=supplier.supplier_id).order_by(
                SupplierHistory.transaction_date.desc()
            ).all()

            history_list = [{
                'history_id': h.history_id,
                'amount_received': h.amount_received,
                'item_bought': h.item_bought,
                'transaction_date': h.transaction_date.strftime("%Y-%m-%d %H:%M:%S")
            } for h in histories]

            supplier_data = {
                'supplier_id': supplier.supplier_id,
                'supplier_name': supplier.supplier_name,
                'supplier_location': supplier.supplier_location,
                'total_amount_received': supplier.total_amount_received,
                'credit_amount': supplier.credit_amount,  # Added credit_amount
                'email': supplier.email,
                'phone_number': supplier.phone_number,
                'items_sold': supplier.items_sold if supplier.items_sold else [],
                'history': history_list
            }

            return {'supplier': supplier_data}, 200

        except Exception as e:
            return {
                'error': 'Failed to fetch supplier details',
                'details': str(e)
            }, 500


class UpdateSupplier(Resource):
    @jwt_required()
    def put(self, supplier_id):
        try:
            supplier = Suppliers.query.filter_by(supplier_id=supplier_id).first()

            if not supplier:
                return {'message': 'Supplier not found'}, 404

            data = request.get_json()

            # Update fields if provided
            if 'supplier_name' in data:
                supplier.supplier_name = data['supplier_name']
            if 'supplier_location' in data:
                supplier.supplier_location = data['supplier_location']
            if 'email' in data:
                supplier.email = data['email']
            if 'phone_number' in data:
                supplier.phone_number = data['phone_number']
            if 'credit_amount' in data:  # Added credit_amount update
                supplier.credit_amount = float(data['credit_amount'])
            if 'items_sold' in data:
                supplier.items_sold = data['items_sold']

            db.session.commit()

            return {
                'message': 'Supplier updated successfully',
                'supplier': {
                    'supplier_id': supplier.supplier_id,
                    'supplier_name': supplier.supplier_name,
                    'supplier_location': supplier.supplier_location,
                    'total_amount_received': supplier.total_amount_received,
                    'credit_amount': supplier.credit_amount,  # Added credit_amount
                    'email': supplier.email,
                    'phone_number': supplier.phone_number,
                    'items_sold': supplier.items_sold if supplier.items_sold else []
                }
            }, 200

        except Exception as e:
            db.session.rollback()
            return {
                'error': 'Failed to update supplier',
                'details': str(e)
            }, 500


class DeleteSupplier(Resource):
    @jwt_required()
    def delete(self, supplier_id):
        try:
            supplier = Suppliers.query.filter_by(supplier_id=supplier_id).first()

            if not supplier:
                return {'message': 'Supplier not found'}, 404

            # Check if supplier has any history records
            history_count = SupplierHistory.query.filter_by(supplier_id=supplier_id).count()
            if history_count > 0:
                return {
                    'message': 'Cannot delete supplier with existing transaction history',
                    'history_count': history_count
                }, 400

            db.session.delete(supplier)
            db.session.commit()

            return {
                'message': 'Supplier deleted successfully',
                'supplier_id': supplier_id
            }, 200

        except Exception as e:
            db.session.rollback()
            return {
                'error': 'Failed to delete supplier',
                'details': str(e)
            }, 500


class AddSupplierHistory(Resource):
    @jwt_required()
    def post(self):
        data = request.get_json()
        current_user_id = get_jwt_identity()

        required_fields = ['supplier_id', 'amount_received', 'item_bought']
        missing_fields = [field for field in required_fields if field not in data]
        
        if missing_fields:
            return {
                'message': f"Missing fields: {', '.join(missing_fields)}"
            }, 400

        try:
            supplier_id = data['supplier_id']
            amount_received = float(data['amount_received'])
            item_bought = data['item_bought']
            transaction_date = data.get('transaction_date')
            
            if transaction_date:
                transaction_date = datetime.strptime(transaction_date, "%Y-%m-%d %H:%M:%S")
            else:
                transaction_date = datetime.utcnow()

            supplier = Suppliers.query.filter_by(supplier_id=supplier_id).first()
            if not supplier:
                return {'message': 'Supplier not found'}, 404

            # Update supplier's total amount received
            supplier.total_amount_received += amount_received

            # Update credit amount if this is a credit payment
            is_credit_payment = data.get('is_credit_payment', False)
            if is_credit_payment:
                supplier.credit_amount = max(0, supplier.credit_amount - amount_received)

            # Add to history
            new_history = SupplierHistory(
                supplier_id=supplier_id,
                amount_received=amount_received,
                item_bought=item_bought,
                transaction_date=transaction_date
            )

            db.session.add(new_history)
            db.session.commit()

            return {
                'message': 'Supplier history added successfully',
                'history_id': new_history.history_id,
                'supplier': {
                    'supplier_id': supplier.supplier_id,
                    'total_amount_received': supplier.total_amount_received,
                    'credit_amount': supplier.credit_amount  # Added credit_amount
                }
            }, 201

        except SQLAlchemyError as e:
            db.session.rollback()
            return {
                'error': 'An error occurred while adding supplier history',
                'details': str(e)
            }, 500
        except ValueError as e:
            return {
                'error': 'Invalid amount format',
                'details': str(e)
            }, 400


class GetSupplierHistory(Resource):
    @jwt_required()
    def get(self, supplier_id):
        try:
            supplier = Suppliers.query.filter_by(supplier_id=supplier_id).first()
            if not supplier:
                return {'message': 'Supplier not found'}, 404

            histories = SupplierHistory.query.filter_by(supplier_id=supplier_id).order_by(
                SupplierHistory.transaction_date.desc()
            ).all()

            history_list = [{
                'history_id': h.history_id,
                'amount_received': h.amount_received,
                'item_bought': h.item_bought,
                'transaction_date': h.transaction_date.strftime("%Y-%m-%d %H:%M:%S")
            } for h in histories]

            return {
                'supplier_id': supplier_id,
                'supplier_name': supplier.supplier_name,
                'total_amount_received': supplier.total_amount_received,
                'credit_amount': supplier.credit_amount,  # Added credit_amount
                'history': history_list
            }, 200

        except Exception as e:
            return {
                'error': 'Failed to fetch supplier history',
                'details': str(e)
            }, 500