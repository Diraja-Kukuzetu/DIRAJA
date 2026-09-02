from flask_restful import Resource
from Server.Models.Customers import Customers,LoyaltyTransaction
from Server.Models.Users import Users
from app import db
from functools import wraps
from flask import request, make_response, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func


class AddCustomer(Resource):
    @jwt_required()
    def post(self):
        data = request.get_json()
        current_user_id = get_jwt_identity()

        required_fields = [
            'customer_name',
            'customer_number',
            'shop_id',
            'item',
            'amount_paid',
            'payment_method'
        ]

        missing_fields = [field for field in required_fields if field not in data]
        if missing_fields:
            return {
                'message': f"Missing fields: {', '.join(missing_fields)}"
            }, 400

        customer_name = data.get('customer_name')
        customer_number = data.get('customer_number')
        shop_id = data.get('shop_id')
        item = data.get('item')
        amount_paid = data.get('amount_paid')
        payment_method = data.get('payment_method')
        
        # Convert the 'created_at' String to a datetime object
        created_at = data.get('created_at')
        if created_at:
            created_at = datetime.strptime(created_at, '%Y-%m-%d')

        # Check if customer wants to register for loyalty program
        register_for_loyalty = data.get('register_for_loyalty', False)

        new_customer = Customers(
            customer_name=customer_name,
            customer_number=customer_number,
            shop_id=shop_id,
            user_id=current_user_id,
            item=item,
            amount_paid=amount_paid,
            payment_method=payment_method,
            created_at=created_at,
            is_loyalty_registered=register_for_loyalty
        )

        db.session.add(new_customer)

        try:
            db.session.commit()
            
            # If customer registered for loyalty, add welcome bonus
            if register_for_loyalty:
                new_customer.register_for_loyalty()
                db.session.commit()
                
                return {
                    'message': 'Customer added successfully and registered for loyalty program',
                    'customer_id': new_customer.customer_id,
                    'loyalty_points': new_customer.loyalty_points,
                    'loyalty_tier': new_customer.loyalty_tier,
                    'welcome_bonus': 50  # Welcome bonus points
                }, 201
            
            return {
                'message': 'Customer added successfully',
                'customer_id': new_customer.customer_id
            }, 201
            
        except SQLAlchemyError as e:
            db.session.rollback()
            return {
                'error': 'An error occurred while adding the customer',
                'details': str(e)
            }, 500


class GetCustomersByShop(Resource):
    @jwt_required()
    def get(self, shop_id):
        try:
            # Query the Customers table for customers related to the given shop_id
            customers = Customers.query.filter_by(shop_id=shop_id).all()

            # Prepare the list of customer data
            customer_list = []
            for customer in customers:
                # Get last earned points (from the most recent earned transaction)
                last_earned = db.session.query(
                    LoyaltyTransaction.points_earned,
                    LoyaltyTransaction.created_at
                ).filter_by(
                    customer_id=customer.customer_id,
                    transaction_type='earned'
                ).order_by(
                    LoyaltyTransaction.created_at.desc()
                ).first()
                
                customer_data = {
                    "customer_id": customer.customer_id,
                    "customer_name": customer.customer_name,
                    "customer_number": customer.customer_number,
                    "shop_id": customer.shop_id,
                    "user_id": customer.user_id,
                    "item": customer.item,
                    "amount_paid": customer.amount_paid,
                    "payment_method": customer.payment_method,
                    "created_at": customer.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                    # Loyalty Points Information
                    "loyalty_points": customer.loyalty_points,
                    "total_spent": customer.total_spent,
                    "points_earned_total": customer.points_earned_total,
                    "points_redeemed_total": customer.points_redeemed_total,
                    "loyalty_tier": customer.loyalty_tier,
                    "is_loyalty_registered": customer.is_loyalty_registered,
                    "last_earned_points": last_earned.points_earned if last_earned else 0,
                    "last_earned_date": last_earned.created_at.strftime('%Y-%m-%d %H:%M:%S') if last_earned and last_earned.created_at else None,
                    "available_discount": customer.get_available_discount() if customer.is_loyalty_registered else 0
                }
                customer_list.append(customer_data)

            # If no customers found for the shop
            if not customer_list:
                return jsonify({"message": "No customers found for this shop"}), 404

            return make_response(jsonify(customer_list), 200)

        except SQLAlchemyError as e:
            db.session.rollback()
            return jsonify({"error": "An error occurred while fetching customers"}), 500


class GetAllCustomers(Resource):
    @jwt_required()
    def get(self):
        try:
            # Get pagination parameters from query string
            page = request.args.get('page', 1, type=int)
            per_page = request.args.get('per_page', 10, type=int)
            
            # Get filter parameters
            loyalty_registered = request.args.get('loyalty_registered', None)
            loyalty_tier = request.args.get('loyalty_tier', None)
            min_points = request.args.get('min_points', None, type=int)
            
            # Validate pagination parameters
            if page < 1:
                return {"error": "Page must be greater than 0"}, 400
            if per_page < 1 or per_page > 100:
                return {"error": "per_page must be between 1 and 100"}, 400
            
            # Build query with filters
            query = Customers.query
            
            # Apply filters if provided
            if loyalty_registered is not None:
                if loyalty_registered.lower() == 'true':
                    query = query.filter_by(is_loyalty_registered=True)
                elif loyalty_registered.lower() == 'false':
                    query = query.filter_by(is_loyalty_registered=False)
            
            if loyalty_tier:
                query = query.filter_by(loyalty_tier=loyalty_tier)
            
            if min_points is not None:
                query = query.filter(Customers.loyalty_points >= min_points)
            
            # Get total count
            total_customers = query.count()
            
            # Calculate offset
            offset = (page - 1) * per_page
            
            # Get paginated customers
            customers = query \
                .order_by(Customers.created_at.desc()) \
                .limit(per_page) \
                .offset(offset) \
                .all()
            
            customer_list = []
            for customer in customers:
                # Get last earned points for this customer
                last_earned = db.session.query(
                    LoyaltyTransaction.points_earned,
                    LoyaltyTransaction.created_at
                ).filter_by(
                    customer_id=customer.customer_id,
                    transaction_type='earned'
                ).order_by(
                    LoyaltyTransaction.created_at.desc()
                ).first()
                
                # Get last redeemed points
                last_redeemed = db.session.query(
                    LoyaltyTransaction.points_redeemed,
                    LoyaltyTransaction.created_at
                ).filter_by(
                    customer_id=customer.customer_id,
                    transaction_type='redeemed'
                ).order_by(
                    LoyaltyTransaction.created_at.desc()
                ).first()
                
                customer_data = {
                    "customer_id": customer.customer_id,
                    "customer_name": customer.customer_name,
                    "customer_number": customer.customer_number,
                    "shop_id": customer.shop_id,
                    "user_id": customer.user_id,
                    "item": customer.item,
                    "amount_paid": customer.amount_paid,
                    "payment_method": customer.payment_method,
                    "created_at": customer.created_at.isoformat() if customer.created_at else None,
                    # Loyalty Points Information
                    "loyalty_points": customer.loyalty_points,
                    "total_spent": customer.total_spent,
                    "points_earned_total": customer.points_earned_total,
                    "points_redeemed_total": customer.points_redeemed_total,
                    "loyalty_tier": customer.loyalty_tier,
                    "is_loyalty_registered": customer.is_loyalty_registered,
                    "loyalty_registration_date": customer.loyalty_registration_date.isoformat() if customer.loyalty_registration_date else None,
                    "last_purchase_date": customer.last_purchase_date.isoformat() if customer.last_purchase_date else None,
                    # Last earned points details
                    "last_earned_points": last_earned.points_earned if last_earned else 0,
                    "last_earned_date": last_earned.created_at.isoformat() if last_earned and last_earned.created_at else None,
                    # Last redeemed points details
                    "last_redeemed_points": last_redeemed.points_redeemed if last_redeemed else 0,
                    "last_redeemed_date": last_redeemed.created_at.isoformat() if last_redeemed and last_redeemed.created_at else None,
                    # Available discount
                    "available_discount": customer.get_available_discount() if customer.is_loyalty_registered else 0,
                    "points_multiplier": customer.get_points_multiplier() if customer.is_loyalty_registered else 0
                }
                customer_list.append(customer_data)
            
            # Return simple paginated response
            return {
                "customers": customer_list,
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total_items": total_customers,
                    "total_pages": (total_customers + per_page - 1) // per_page,
                    "has_next": page * per_page < total_customers,
                    "has_prev": page > 1
                },
                "filters_applied": {
                    "loyalty_registered": loyalty_registered,
                    "loyalty_tier": loyalty_tier,
                    "min_points": min_points
                }
            }, 200

        except SQLAlchemyError as e:
            db.session.rollback()
            print(f"Database error: {str(e)}")
            return {"error": "An error occurred while fetching customers"}, 500
        except Exception as e:
            print(f"Unexpected error: {str(e)}")
            return {"error": "An unexpected error occurred"}, 500


class GetCustomerById(Resource):
    
    @jwt_required()
    def get(self, customer_id):
        try:
            customer = Customers.query.get(customer_id)
            if not customer:
                return {"error": f"Customer with ID {customer_id} not found"}, 404

            # Get last earned points
            last_earned = db.session.query(
                LoyaltyTransaction.points_earned,
                LoyaltyTransaction.created_at
            ).filter_by(
                customer_id=customer.customer_id,
                transaction_type='earned'
            ).order_by(
                LoyaltyTransaction.created_at.desc()
            ).first()
            
            # Get last redeemed points
            last_redeemed = db.session.query(
                LoyaltyTransaction.points_redeemed,
                LoyaltyTransaction.created_at
            ).filter_by(
                customer_id=customer.customer_id,
                transaction_type='redeemed'
            ).order_by(
                LoyaltyTransaction.created_at.desc()
            ).first()
            
            # Get all loyalty transactions
            transactions = LoyaltyTransaction.query.filter_by(
                customer_id=customer.customer_id
            ).order_by(
                LoyaltyTransaction.created_at.desc()
            ).limit(10).all()  # Get last 10 transactions
            
            transaction_list = []
            for transaction in transactions:
                transaction_list.append({
                    "transaction_id": transaction.transaction_id,
                    "points_earned": transaction.points_earned,
                    "points_redeemed": transaction.points_redeemed,
                    "transaction_type": transaction.transaction_type,
                    "amount_spent": transaction.amount_spent,
                    "description": transaction.description,
                    "created_at": transaction.created_at.isoformat() if transaction.created_at else None
                })

            customer_data = {
                "customer_id": customer.customer_id,
                "customer_name": customer.customer_name,
                "customer_number": customer.customer_number,
                "shop_id": customer.shop_id,
                "user_id": customer.user_id,
                "item": customer.item,
                "amount_paid": customer.amount_paid,
                "payment_method": customer.payment_method,
                "created_at": customer.created_at.isoformat() if customer.created_at else None,
                # Loyalty Points Information
                "loyalty_points": customer.loyalty_points,
                "total_spent": customer.total_spent,
                "points_earned_total": customer.points_earned_total,
                "points_redeemed_total": customer.points_redeemed_total,
                "loyalty_tier": customer.loyalty_tier,
                "is_loyalty_registered": customer.is_loyalty_registered,
                "loyalty_registration_date": customer.loyalty_registration_date.isoformat() if customer.loyalty_registration_date else None,
                "last_purchase_date": customer.last_purchase_date.isoformat() if customer.last_purchase_date else None,
                # Last transaction details
                "last_earned_points": last_earned.points_earned if last_earned else 0,
                "last_earned_date": last_earned.created_at.isoformat() if last_earned and last_earned.created_at else None,
                "last_redeemed_points": last_redeemed.points_redeemed if last_redeemed else 0,
                "last_redeemed_date": last_redeemed.created_at.isoformat() if last_redeemed and last_redeemed.created_at else None,
                # Available discount
                "available_discount": customer.get_available_discount() if customer.is_loyalty_registered else 0,
                "points_multiplier": customer.get_points_multiplier() if customer.is_loyalty_registered else 0,
                # Recent transactions
                "recent_transactions": transaction_list
            }

            return make_response(jsonify(customer_data), 200)

        except SQLAlchemyError as e:
            db.session.rollback()
            return {"error": "An error occurred while fetching the customer"}, 500

    @jwt_required()
    def put(self, customer_id):
        try:
            # Get the existing customer
            customer = Customers.query.get(customer_id)
            if not customer:
                return {"error": f"Customer with ID {customer_id} not found"}, 404

            # Parse the JSON data from the request
            data = request.get_json()

            # Update the customer properties with new data
            customer.customer_name = data.get('customer_name', customer.customer_name)
            customer.customer_number = data.get('customer_number', customer.customer_number)
            customer.shop_id = data.get('shop_id', customer.shop_id)
            customer.user_id = data.get('user_id', customer.user_id)
            customer.item = data.get('item', customer.item)
            customer.amount_paid = data.get('amount_paid', customer.amount_paid)
            customer.payment_method = data.get('payment_method', customer.payment_method)
            
            # Handle loyalty registration status update
            register_loyalty = data.get('register_for_loyalty')
            if register_loyalty is not None:
                if register_loyalty and not customer.is_loyalty_registered:
                    customer.register_for_loyalty()
                elif not register_loyalty and customer.is_loyalty_registered:
                    customer.unregister_from_loyalty()

            # Commit the changes to the database
            db.session.commit()

            return make_response(jsonify({
                "message": "Customer updated successfully",
                "loyalty_points": customer.loyalty_points,
                "loyalty_tier": customer.loyalty_tier,
                "is_loyalty_registered": customer.is_loyalty_registered
            }), 200)

        except SQLAlchemyError as e:
            db.session.rollback()
            return {"error": "An error occurred while updating the customer"}, 500

    @jwt_required()
    def delete(self, customer_id):
        try:
            customer = Customers.query.get(customer_id)
            if not customer:
                return {"error": f"Customer with ID {customer_id} not found"}, 404

            # Delete the customer from the database
            db.session.delete(customer)
            db.session.commit()

            return make_response(jsonify({"message": "Customer deleted successfully"}), 200)

        except SQLAlchemyError as e:
            db.session.rollback()
            return {"error": "An error occurred while deleting the customer"}, 500


# New Resource for Loyalty Points Management
class CustomerLoyaltyPoints(Resource):
    @jwt_required()
    def post(self, customer_id):
        """Add loyalty points to a customer"""
        try:
            customer = Customers.query.get(customer_id)
            if not customer:
                return {"error": f"Customer with ID {customer_id} not found"}, 404
            
            data = request.get_json()
            amount_spent = data.get('amount_spent')
            
            if not amount_spent or amount_spent <= 0:
                return {"error": "Valid amount_spent is required"}, 400
            
            # Get points multiplier based on tier
            multiplier = customer.get_points_multiplier()
            
            # Add points
            points_earned = customer.add_loyalty_points(amount_spent, multiplier)
            db.session.commit()
            
            return {
                "message": "Loyalty points added successfully",
                "customer_id": customer.customer_id,
                "customer_name": customer.customer_name,
                "points_earned": points_earned,
                "total_points": customer.loyalty_points,
                "loyalty_tier": customer.loyalty_tier,
                "points_multiplier": multiplier
            }, 200
            
        except ValueError as e:
            return {"error": str(e)}, 400
        except SQLAlchemyError as e:
            db.session.rollback()
            return {"error": "An error occurred while adding points"}, 500

    @jwt_required()
    def put(self, customer_id):
        """Redeem loyalty points"""
        try:
            customer = Customers.query.get(customer_id)
            if not customer:
                return {"error": f"Customer with ID {customer_id} not found"}, 404
            
            data = request.get_json()
            points_to_redeem = data.get('points_to_redeem')
            
            if not points_to_redeem or points_to_redeem <= 0:
                return {"error": "Valid points_to_redeem is required"}, 400
            
            # Redeem points
            discount = customer.redeem_points(points_to_redeem)
            db.session.commit()
            
            return {
                "message": "Points redeemed successfully",
                "customer_id": customer.customer_id,
                "customer_name": customer.customer_name,
                "points_redeemed": points_to_redeem,
                "discount_amount": discount,
                "remaining_points": customer.loyalty_points,
                "loyalty_tier": customer.loyalty_tier
            }, 200
            
        except ValueError as e:
            return {"error": str(e)}, 400
        except SQLAlchemyError as e:
            db.session.rollback()
            return {"error": "An error occurred while redeeming points"}, 500


class GetLoyaltyTransactions(Resource):
    @jwt_required()
    def get(self, customer_id):
        """Get all loyalty transactions for a customer"""
        try:
            customer = Customers.query.get(customer_id)
            if not customer:
                return {"error": f"Customer with ID {customer_id} not found"}, 404
            
            # Get pagination parameters
            page = request.args.get('page', 1, type=int)
            per_page = request.args.get('per_page', 20, type=int)
            
            # Get filter by transaction type
            transaction_type = request.args.get('transaction_type', None)
            
            query = LoyaltyTransaction.query.filter_by(customer_id=customer_id)
            if transaction_type:
                query = query.filter_by(transaction_type=transaction_type)
            
            # Get total count
            total_transactions = query.count()
            
            # Calculate offset
            offset = (page - 1) * per_page
            
            # Get paginated transactions
            transactions = query.order_by(
                LoyaltyTransaction.created_at.desc()
            ).limit(per_page).offset(offset).all()
            
            transaction_list = []
            for transaction in transactions:
                transaction_list.append({
                    "transaction_id": transaction.transaction_id,
                    "points_earned": transaction.points_earned,
                    "points_redeemed": transaction.points_redeemed,
                    "transaction_type": transaction.transaction_type,
                    "amount_spent": transaction.amount_spent,
                    "description": transaction.description,
                    "created_at": transaction.created_at.isoformat() if transaction.created_at else None
                })
            
            return {
                "customer_id": customer_id,
                "customer_name": customer.customer_name,
                "current_points": customer.loyalty_points,
                "transactions": transaction_list,
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total_items": total_transactions,
                    "total_pages": (total_transactions + per_page - 1) // per_page,
                    "has_next": page * per_page < total_transactions,
                    "has_prev": page > 1
                }
            }, 200
            
        except SQLAlchemyError as e:
            return {"error": "An error occurred while fetching transactions"}, 500
        

class GetCustomerByNumber(Resource):
    @jwt_required()
    def get(self):
        """
        Get customer loyalty points and tier by customer number.
        Query params:
            - customer_number: Phone number of the customer
        """
        try:
            customer_number = request.args.get('customer_number')
            
            if not customer_number:
                return {
                    "error": "customer_number is required",
                    "status": "error"
                }, 400
            
            # Clean phone number (remove spaces, special characters)
            clean_number = ''.join(filter(str.isdigit, str(customer_number)))
            
            # Find customer by phone number
            customer = Customers.query.filter(
                func.replace(Customers.customer_number, ' ', '') == clean_number
            ).first()
            
            if not customer:
                return {
                    "status": "not_found",
                    "message": "Customer not found",
                    "customer_number": customer_number,
                    "exists": False
                }, 200
            
            # Get last earned points
            last_earned = db.session.query(
                LoyaltyTransaction.points_earned,
                LoyaltyTransaction.created_at
            ).filter_by(
                customer_id=customer.customer_id,
                transaction_type='earned'
            ).order_by(
                LoyaltyTransaction.created_at.desc()
            ).first()
            
            # Get last redeemed points
            last_redeemed = db.session.query(
                LoyaltyTransaction.points_redeemed,
                LoyaltyTransaction.created_at
            ).filter_by(
                customer_id=customer.customer_id,
                transaction_type='redeemed'
            ).order_by(
                LoyaltyTransaction.created_at.desc()
            ).first()
            
            # Calculate points needed for next tier
            next_tier = None
            points_needed = 0
            
            if customer.is_loyalty_registered:
                tier_thresholds = {
                    "Bronze": 0,
                    "Silver": 1000,
                    "Gold": 5000,
                    "Platinum": 10000
                }
                
                tier_order = ["Bronze", "Silver", "Gold", "Platinum"]
                current_tier_index = tier_order.index(customer.loyalty_tier) if customer.loyalty_tier in tier_order else 0
                
                # Check if there's a next tier
                if current_tier_index < len(tier_order) - 1:
                    next_tier = tier_order[current_tier_index + 1]
                    next_threshold = tier_thresholds[next_tier]
                    points_needed = max(0, next_threshold - customer.loyalty_points)
            
            # Build response
            response_data = {
                "status": "found",
                "exists": True,
                "customer_id": customer.customer_id,
                "customer_name": customer.customer_name,
                "customer_number": customer.customer_number,
                "shop_id": customer.shop_id,
                "is_loyalty_registered": customer.is_loyalty_registered,
                "loyalty_points": customer.loyalty_points,
                "loyalty_tier": customer.loyalty_tier,
                "total_spent": customer.total_spent,
                "points_earned_total": customer.points_earned_total,
                "points_redeemed_total": customer.points_redeemed_total,
                "available_discount": customer.get_available_discount() if customer.is_loyalty_registered else 0,
                "points_multiplier": customer.get_points_multiplier() if customer.is_loyalty_registered else 0,
                "last_purchase_date": customer.last_purchase_date.isoformat() if customer.last_purchase_date else None,
                "last_earned_points": last_earned.points_earned if last_earned else 0,
                "last_earned_date": last_earned.created_at.isoformat() if last_earned and last_earned.created_at else None,
                "last_redeemed_points": last_redeemed.points_redeemed if last_redeemed else 0,
                "last_redeemed_date": last_redeemed.created_at.isoformat() if last_redeemed and last_redeemed.created_at else None,
                "loyalty_registration_date": customer.loyalty_registration_date.isoformat() if customer.loyalty_registration_date else None,
                "next_tier": next_tier,
                "points_needed_for_next_tier": points_needed
            }
            
            return make_response(jsonify(response_data), 200)
            
        except SQLAlchemyError as e:
            db.session.rollback()
            print(f"Database error in GetCustomerByNumber: {str(e)}")
            return {
                "error": "An error occurred while fetching customer data",
                "status": "error"
            }, 500
        except Exception as e:
            print(f"Unexpected error in GetCustomerByNumber: {str(e)}")
            return {
                "error": "An unexpected error occurred",
                "status": "error"
            }, 500