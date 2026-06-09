from flask_restful import Resource, reqparse
from Server.Models.Permission import Permission
from app import db
from flask_jwt_extended import jwt_required, get_jwt_identity

class GetAllPermissions(Resource):
    @jwt_required()
    def get(self):
        try:
            # Check if current user has Settings permission
            current_user_id = get_jwt_identity()
            current_user_permissions = Permission.query.filter_by(user_id=current_user_id).first()
            
            # Only allow users with Settings permission to view all permissions
            if not current_user_permissions or not current_user_permissions.Settings:
                return {"status": "error", "message": "Unauthorized: You don't have permission to view all permissions"}, 403
            
            permissions = Permission.query.all()

            data = []
            for p in permissions:
                data.append({
                    "id": p.id,
                    "user_id": p.user_id,
                    "Dashboard": p.Dashboard,
                    "Stock": p.Stock,
                    "Sales": p.Sales,
                    "Sales_analytics": p.Sales_analytics,
                    "Expenses": p.Expenses,
                    "Mabanda_Farm": p.Mabanda_Farm,
                    "Shops": p.Shops,
                    "Employess": p.Employess,
                    "Suppliers": p.Suppliers,
                    "Creditors": p.Creditors,
                    "Task_manager": p.Task_manager,
                    "Accounting": p.Accounting,
                    "Settings": p.Settings
                })

            return {"status": "success", "permissions": data}, 200

        except Exception as e:
            return {"status": "error", "message": str(e)}, 500


class GetUserPermissions(Resource):
    @jwt_required()
    def get(self, user_id):
        try:
            current_user_id = get_jwt_identity()
            current_user_permissions = Permission.query.filter_by(user_id=current_user_id).first()
            
            # Users can only view their own permissions unless they have Settings permission
            if str(current_user_id) != str(user_id):
                if not current_user_permissions or not current_user_permissions.Settings:
                    return {"status": "error", "message": "Unauthorized: You can only view your own permissions"}, 403
            
            permission = Permission.query.filter_by(user_id=user_id).first()

            if not permission:
                return {"status": "error", "message": "Permissions not found for this user"}, 404

            data = {
                "id": permission.id,
                "user_id": permission.user_id,
                "Dashboard": permission.Dashboard,
                "Stock": permission.Stock,
                "Sales": permission.Sales,
                "Sales_analytics": permission.Sales_analytics,
                "Expenses": permission.Expenses,
                "Mabanda_Farm": permission.Mabanda_Farm,
                "Shops": permission.Shops,
                "Employess": permission.Employess,
                "Suppliers": permission.Suppliers,
                "Creditors": permission.Creditors,
                "Task_manager": permission.Task_manager,
                "Accounting": permission.Accounting,
                "Settings": permission.Settings
            }

            return {"status": "success", "permissions": data}, 200

        except Exception as e:
            return {"status": "error", "message": str(e)}, 500


class UpdateUserPermissions(Resource):
    @jwt_required()
    def put(self, user_id):
        try:
            current_user_id = get_jwt_identity()
            current_user_permissions = Permission.query.filter_by(user_id=current_user_id).first()
            
            # Only allow users with Settings permission to update permissions
            if not current_user_permissions or not current_user_permissions.Settings:
                return {"status": "error", "message": "Unauthorized: You don't have permission to update permissions"}, 403
            
            permission = Permission.query.filter_by(user_id=user_id).first()

            if not permission:
                return {"status": "error", "message": "Permissions not found for this user"}, 404

            # Parse JSON body
            parser = reqparse.RequestParser()
            parser.add_argument("Dashboard", type=bool, required=False, help="Dashboard permission must be a boolean")
            parser.add_argument("Stock", type=bool, required=False, help="Stock permission must be a boolean")
            parser.add_argument("Sales", type=bool, required=False, help="Sales permission must be a boolean")
            parser.add_argument("Sales_analytics", type=bool, required=False, help="Sales_analytics permission must be a boolean")
            parser.add_argument("Expenses", type=bool, required=False, help="Expenses permission must be a boolean")
            parser.add_argument("Mabanda_Farm", type=bool, required=False, help="Mabanda_Farm permission must be a boolean")
            parser.add_argument("Shops", type=bool, required=False, help="Shops permission must be a boolean")
            parser.add_argument("Employess", type=bool, required=False, help="Employess permission must be a boolean")
            parser.add_argument("Suppliers", type=bool, required=False, help="Suppliers permission must be a boolean")
            parser.add_argument("Creditors", type=bool, required=False, help="Creditors permission must be a boolean")
            parser.add_argument("Task_manager", type=bool, required=False, help="Task_manager permission must be a boolean")
            parser.add_argument("Accounting", type=bool, required=False, help="Accounting permission must be a boolean")
            parser.add_argument("Settings", type=bool, required=False, help="Settings permission must be a boolean")

            args = parser.parse_args()

            # Update only non-null values (fields sent in request)
            updated_fields = []
            for key, value in args.items():
                if value is not None:
                    setattr(permission, key, value)
                    updated_fields.append(key)

            if not updated_fields:
                return {"status": "error", "message": "No valid fields to update"}, 400

            db.session.commit()

            return {
                "status": "success",
                "message": "Permissions updated successfully",
                "updated_fields": updated_fields
            }, 200

        except Exception as e:
            db.session.rollback()
            return {"status": "error", "message": str(e)}, 500