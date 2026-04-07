from  flask_restful import Resource
from Server.Models.Users import Users
from Server.Models.Shops import Shops
from Server.Models.Employees import Employees
from Server.Models.StockReport import StockReport
from app import db
import bcrypt
from flask_jwt_extended import create_access_token, create_refresh_token
from flask import jsonify,request,make_response
from functools import wraps
from flask_jwt_extended import jwt_required,get_jwt_identity
import re
from Server.Models.ShopReport import ShopReport
from sqlalchemy import func
from datetime import datetime, date


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


class CountUsers(Resource):
    @jwt_required()
    def get(self):
        countUsers = Users.query.count()
        return {"total users": countUsers}, 200

class Addusers(Resource):   
    
    def post (self):
        data = request.get_json()

        if 'username' not in data or 'email' not in data or 'password' not in data:
            return {'message': 'Missing username, email, or password'}, 400

        username = data.get('username')
        email = data.get('email')
        role = data.get('role')
        password = data.get('password')
        status = data.get('status')

        # Check if user already exists
        if Users.query.filter_by(email=email).first():
            return {'message': 'User already exists'}, 400

        user = Users(username=username, email=email, password=password, role=role , status=status)
        db.session.add(user)
        db.session.commit()


        return {'message': 'User added successfully'}, 201



class UserLogin(Resource):
    def post(self):
        email = request.json.get("email", None)
        password = request.json.get("password", None)

        # Validate input
        if not email or not password:
            return make_response(jsonify({"error": "Email and password are required"}), 400)

        # Fetch the user based on email
        user = Users.query.filter_by(email=email).one_or_none()

        if not user:
            return make_response(jsonify({"error": "User not found. Please check your email."}), 404)

        # Check if user is active
        if user.status != "active":
            return make_response(jsonify({
                "error": "Account is not active. Please contact administrator.",
                "status": user.status
            }), 403)

        # Validate the password
        if not bcrypt.checkpw(password.encode('utf-8'), user.password.encode('utf-8')):
            return make_response(jsonify({"error": "Wrong password"}), 401)

        # Prepare base response
        username = user.username
        user_role = user.role

        # Create access token with additional claims including status
        access_token = create_access_token(
            identity=user.users_id, 
            additional_claims={
                'roles': [user_role],
                'username': username,
                'email': user.email,
                'status': user.status
            }
        )
        
        refresh_token = create_refresh_token(identity=user.users_id)

        response_data = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "username": username,
            "users_id": user.users_id,
            "email": user.email,
            "role": user_role,
            "status": user.status
        }

        # Additional logic for clerks
        if user_role == "clerk":
            employee = Employees.query.filter_by(work_email=email).one_or_none()
            if employee:
                shop_id = employee.shop_id
                response_data["shop_id"] = shop_id
                response_data["designation"] = employee.designation
                response_data["employee_id"] = employee.employee_id

                # Fetch report_status directly from the Shops model
                shop = Shops.query.filter_by(shops_id=shop_id).first()
                if shop:
                    response_data["report_status"] = shop.report_status
                else:
                    response_data["report_status"] = None  # In case shop record is missing
                    
                # Fetch shop details
                if shop:
                    response_data["shopname"] = shop.shopname

        # Additional logic for managers (optional)
        elif user_role == "manager":
            # You can add manager-specific data here if needed
            pass

        return make_response(jsonify(response_data), 200)


class UsersResourceById(Resource):

    @jwt_required()
    @check_role('manager')
    def get(self, users_id):
        user = Users.query.get(users_id)

        if user:
            return {
                "users_id": user.users_id,
                "username": user.username,
                "email": user.email,
                "password": user.password,  # Consider if you really want to return the password hash
                "role": user.role,
                "status": user.status  # Added status
            }, 200
        else:
            return {"error": "User not found"}, 404
    
    @jwt_required()
    @check_role('manager')
    def delete(self, users_id):
        user = Users.query.get(users_id)

        if user:
            # Instead of hard delete, consider soft delete by updating status
            # Uncomment the lines below for soft delete
            # user.status = "former employee"
            # db.session.commit()
            # return {"message": f"User with id {users_id} marked as former employee"}, 200
            
            # Hard delete (original)
            db.session.delete(user)
            db.session.commit()

            return {"message": f"User with id {users_id} deleted successfully"}, 200
        else:
            return {"error": "User not found"}, 404

    @jwt_required()
    @check_role('manager')
    def put(self, users_id):
        user = Users.query.get(users_id)

        if not user:
            return {"error": "User not found"}, 404

        data = request.get_json()

        # Validate input data
        username = data.get("username")
        email = data.get("email")
        password = data.get("password")
        role = data.get("role")
        status = data.get("status")  # Fixed: was incorrectly using data.status()

        # Validate status if provided
        if status:
            valid_statuses = ['active', 'inactive', 'former employee']
            if status not in valid_statuses:
                return {
                    "error": f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
                }, 400

        # Validate role if provided
        if role:
            valid_roles = ['manager', 'clerk', 'super_admin', 'procurement']
            if role not in valid_roles:
                return {
                    "error": f"Invalid role. Must be one of: {', '.join(valid_roles)}"
                }, 400

        # Validate password (if provided)
        if password:
            error_messages = []
            
            if len(password) < 8:
                error_messages.append("Password must be at least 8 characters long.")
            
            if not re.search(r'[A-Z]', password):
                error_messages.append("Password must contain at least one capital letter.")
            
            if not re.search(r'\d', password):
                error_messages.append("Password must contain at least one number.")
            
            if error_messages:
                return {"error": " ".join(error_messages)}, 400
            
            # Hash the password before saving
            salt = bcrypt.gensalt()
            hashed_password = bcrypt.hashpw(password.encode('utf-8'), salt)
            user.password = hashed_password.decode('utf-8')

        # Update fields if provided
        if username:
            user.username = username
        if email:
            # Validate email format
            if '@' not in email or '.' not in email.split('@')[-1]:
                return {"error": "Invalid email format"}, 400
            user.email = email
        if role:
            user.role = role
        if status:
            user.status = status

        # Save changes to the database
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return {"error": f"Failed to update user: {str(e)}"}, 500

        return {
            "message": f"User with id {users_id} updated successfully",
            "user": {
                "users_id": user.users_id,
                "username": user.username,
                "email": user.email,
                "role": user.role,
                "status": user.status,
            }
        }, 200

   
class GetAllUsers(Resource):

    @jwt_required()
    
    def get(self):
        users = Users.query.all()

        all_users = [{

            "user_id": user.users_id,
            "username": user.username,
            "email": user.email,
            "password": user.password,
            "role" : user.role,
            "status" : user.status,
            
        } for user in users]

        return make_response(jsonify(all_users), 200)
    

class PostShopReport(Resource):

    @jwt_required()
    def post(self):
        user_id = get_jwt_identity()
        data = request.get_json() or {}

        shop_id = data.get("shop_id")
        latitude = data.get("latitude")
        longitude = data.get("longitude")
        location = data.get("location")
        note = data.get("note")

        # ---- Validation ----
        if not shop_id:
            return {"message": "shop_id is required"}, 400

        try:
            shop_id = int(shop_id)
        except (ValueError, TypeError):
            return {"message": "shop_id must be an integer"}, 400

        user = Users.query.get(user_id)
        if not user:
            return {"message": "User not found"}, 404

        # ---- Prevent multiple reports per day (per user per shop) ----
        today = date.today()

        existing_report = ShopReport.query.filter(
            ShopReport.shop_id == shop_id,
            ShopReport.user_id == user.users_id,
            func.date(ShopReport.reported_at) == today
        ).first()

        if existing_report:
            return {
                "message": "You have already submitted a report for this shop today"
            }, 409

        # ---- Create report ----
        report = ShopReport(
            user_id=user.users_id,
            username=user.username,
            shop_id=shop_id,
            latitude=latitude,
            longitude=longitude,
            location=location,
            note=note,
            reported_at=datetime.utcnow()
        )

        db.session.add(report)
        db.session.commit()

        return {
            "message": "Shop report submitted successfully",
            "report": {
                "id": report.id,
                "shop_id": report.shop_id,
                "user_id": report.user_id,
                "username": report.username,
                "reported_at": report.reported_at.isoformat(),
                "location": report.location,
                "latitude": report.latitude,
                "longitude": report.longitude
            }
        }, 201