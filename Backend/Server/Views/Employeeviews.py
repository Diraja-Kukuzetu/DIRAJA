from flask_restful import Resource
from Server.Models.Employees import Employees
from Server.Models.Users import Users
from Server.Models.Sales import Sales
from Server.Models.Paymnetmethods import SalesPaymentMethods
from Server.Models.SoldItems import SoldItem
from app import db
from flask_jwt_extended import jwt_required,get_jwt_identity
from flask import jsonify,request,make_response
from datetime import datetime
from functools import wraps
from datetime import datetime, timedelta
from sqlalchemy import case, func
from sqlalchemy.exc import SQLAlchemyError

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

from werkzeug.security import generate_password_hash

class AddNewemployee(Resource):
    @jwt_required()
    def post(self):
        current_user_id = get_jwt_identity()
        current_user = Users.query.get(current_user_id)

        if not current_user:
            return {"error": "Current user not found."}, 404

        # current_user_role = current_user.role

        data = request.get_json()

        # Restrict manager/procurement creation
        # if data.get('role') in ['manager', 'procurement'] and current_user_role != 'super_admin':
        #     return {
        #         "error": "Only users with the role 'super_admin' can add an employee with the role 'manager' or 'procurement'."
        #     }, 403

        # List of fields that are nullable
        nullable_fields = [
            'national_id_number', 'kra_pin', 'payment_method', 'bank_account_number',
            'bank_name', 'department', 'date_of_birth', 'contract_termination_date',
            'contract_renewal_date', 'created_at'
        ]

        for field in nullable_fields:
            if field in data and data[field] == '':
                data[field] = None

        # Parse dates safely
        starting_date = self.parse_date(data.get('starting_date'))
        contract_termination_date = self.parse_date(data.get('contract_termination_date'))
        contract_renewal_date = self.parse_date(data.get('contract_renewal_date'))
        date_of_birth = self.parse_date(data.get('date_of_birth'))

        # Parse and sanitize salary
        salary_raw = data.get('monthly_gross_salary')
        if salary_raw == '' or salary_raw is None:
            monthly_salary = None
        else:
            try:
                monthly_salary = float(salary_raw)
            except ValueError:
                return {"error": "Invalid salary format."}, 400

        # Get password from request payload
        # If password is not provided, use default password
        user_password = data.get('password')
        
        # Validate password if provided
        if user_password:
            # Password validation rules
            if len(user_password) < 8:
                return {"error": "Password must be at least 8 characters long"}, 400
            if not any(char.isupper() for char in user_password):
                return {"error": "Password must contain at least one uppercase letter"}, 400
            if not any(char.islower() for char in user_password):
                return {"error": "Password must contain at least one lowercase letter"}, 400
            if not any(char.isdigit() for char in user_password):
                return {"error": "Password must contain at least one number"}, 400
            if not any(char in "!@#$%^&*(),.?\":{}|<>" for char in user_password):
                return {"error": "Password must contain at least one special character"}, 400
            
            # Hash the password before storing
            hashed_password = generate_password_hash(user_password)
        else:
            # Use default password (also hash it)
            default_password = 'defaultPassword123'
            hashed_password = generate_password_hash(default_password)

        # Create Employee record
        new_employee = Employees(
            first_name=data.get('first_name'),
            middle_name=data.get('middle_name'),
            surname=data.get('surname'),
            phone_number=data.get('phone_number'),
            work_email=data.get('work_email'),
            account_status=data.get('account_status'),
            shop_id=data.get('shop_id'),
            role=data.get('role'),
            personal_email=data.get('personal_email'),
            designation=data.get('designation'),
            date_of_birth=date_of_birth,
            national_id_number=data.get('national_id_number'),
            kra_pin=data.get('kra_pin'),
            monthly_gross_salary=monthly_salary,
            payment_method=data.get('payment_method'),
            bank_account_number=data.get('bank_account_number'),
            bank_name=data.get('bank_name'),
            department=data.get('department'),
            starting_date=starting_date,
            contract_termination_date=contract_termination_date,
            contract_renewal_date=contract_renewal_date,
            created_at=datetime.now(),
            merit_points=100,  # ✅ Set default merit points to 100
            merit_points_updated_at=None
        )

        db.session.add(new_employee)
        db.session.commit()

        # Create corresponding user record with the hashed password
        new_user = Users(
            username=data.get('first_name'),
            email=data.get('work_email'),
            role=data.get('role') if data.get('role') else 'clerk',  # Default role for new users
            password=hashed_password,  # Store the hashed password
            employee_id=new_employee.employee_id
        )

        db.session.add(new_user)
        db.session.commit()

        return {"message": "Employee and user added successfully"}, 201

    def parse_date(self, date_str):
        """
        Helper to parse a string to a date object.
        Accepts format: 'YYYY-MM-DD'
        """
        if date_str:
            try:
                return datetime.strptime(date_str, '%Y-%m-%d')
            except ValueError:
                return None
        return None


class GetAllemployees(Resource):
    @jwt_required() 
    @check_role('manager')
    def get(self):
        employees = Employees.query.all()

        all_employees = [{
            'employee_id': employee.employee_id,
            'first_name': employee.first_name,
            'middle_name': employee.middle_name,
            'surname': employee.surname,
            'phone_number': employee.phone_number,
            'work_email': employee.work_email,
            'account_status': employee.account_status,
            'shop_id': employee.shop_id,
            'shop_name': employee.shops.shopname if employee.shops else None,  # Fetching shop name
            'role': employee.role,
            'personal_email': employee.personal_email,
            'designation': employee.designation,
            'date_of_birth': employee.date_of_birth,
            'national_id_number': employee.national_id_number,
            'kra_pin': employee.kra_pin,
            'monthly_gross_salary': employee.monthly_gross_salary,
            'payment_method': employee.payment_method,
            'bank_account_number': employee.bank_account_number,
            'bank_name': employee.bank_name,
            'department': employee.department,
            'starting_date': employee.starting_date,
            'contract_termination_date': employee.contract_termination_date,
            'contract_renewal_date': employee.contract_renewal_date,
            "merit_points": employee.merit_points,
            "merit_points_updated_at": employee.merit_points_updated_at,
            "created_at": employee.created_at
        } for employee in employees]

        return make_response(jsonify(all_employees), 200) 



class Employeeresource(Resource):
    @jwt_required()
    @check_role('manager')
    def get(self, employee_id):
        """Get employee details by employee_id"""
        employee = Employees.query.get(employee_id)

        if not employee:
            return {"error": "Employee not found"}, 404

        employee_data = {
            'employee_id': employee.employee_id,
            'first_name': employee.first_name,
            'middle_name': employee.middle_name,
            'surname': employee.surname,
            'phone_number': employee.phone_number,
            'work_email': employee.work_email,
            'account_status': employee.account_status,
            'shop_id': employee.shop_id,
            'role': employee.role,
            'personal_email': employee.personal_email,
            'designation': employee.designation,
            'date_of_birth': employee.date_of_birth,
            'national_id_number': employee.national_id_number,
            'kra_pin': employee.kra_pin,
            'monthly_gross_salary': employee.monthly_gross_salary,
            'payment_method': employee.payment_method,
            'bank_account_number': employee.bank_account_number,
            'bank_name': employee.bank_name,
            'department': employee.department,
            'starting_date': employee.starting_date,
            "merit_points": employee.merit_points,
            'contract_termination_date': employee.contract_termination_date,
            'contract_renewal_date': employee.contract_renewal_date
        }

        return make_response(jsonify(employee_data), 200)
    
    @jwt_required()
    @check_role('manager')
    def put(self, employee_id):
        """Update employee details by employee_id"""
        data = request.get_json()

        employee = Employees.query.get(employee_id)
        if not employee:
            return {"error": "Employee not found"}, 404

        # Update fields with the provided data
        employee.first_name = data.get('first_name', employee.first_name)
        employee.middle_name = data.get('middle_name', employee.middle_name)
        employee.surname = data.get('surname', employee.surname)
        employee.phone_number = data.get('phone_number', employee.phone_number)
        employee.work_email = data.get('work_email', employee.work_email)
        employee.account_status = data.get('account_status', employee.account_status)
        employee.shop_id = data.get('shop_id', employee.shop_id)
        employee.role = data.get('role', employee.role)
        employee.personal_email = data.get('personal_email', employee.personal_email)
        employee.designation = data.get('designation', employee.designation)
        employee.date_of_birth = self.parse_date(data.get('date_of_birth'), employee.date_of_birth)
        employee.national_id_number = data.get('national_id_number', employee.national_id_number)
        employee.kra_pin = data.get('kra_pin', employee.kra_pin)
        employee.monthly_gross_salary = data.get('monthly_gross_salary', employee.monthly_gross_salary)
        employee.payment_method = data.get('payment_method', employee.payment_method)
        employee.bank_account_number = data.get('bank_account_number', employee.bank_account_number)
        employee.bank_name = data.get('bank_name', employee.bank_name)
        employee.department = data.get('department', employee.department)
        employee.starting_date = self.parse_date(data.get('starting_date'), employee.starting_date)
        employee.contract_termination_date = self.parse_date(data.get('contract_termination_date'), employee.contract_termination_date)
        employee.contract_renewal_date = self.parse_date(data.get('contract_renewal_date'), employee.contract_renewal_date)

        db.session.commit()

        return {"message": "Employee updated successfully"}, 200
    
    @jwt_required()
    @check_role('manager')
    def delete(self, employee_id):
        """Delete an employee by employee_id"""
        employee = Employees.query.get(employee_id)
        if not employee:
            return {"error": "Employee not found"}, 404

        db.session.delete(employee)
        db.session.commit()

        return {"message": "Employee deleted successfully"}, 200

    def parse_date(self, date_str, original_date):
        """Helper method to parse a date String into a datetime object"""
        if date_str:
            try:
                return datetime.strptime(date_str, '%Y-%m-%d')
            except ValueError:
                try:
                    return datetime.strptime(date_str, '%Y-%m-%d')
                except ValueError:
                    return original_date  # Return the original date if parsing fails
        return original_date  # Return the original date if no new date is provided

class CountEmployees(Resource):
    @jwt_required()
    @check_role('superadmin')
    @check_role('manager')
    def get(self):
        countEmployees = Employees.query.count()
        return {"total employees": countEmployees}, 200 
    



class UpdateEmployeeShop(Resource):
    @jwt_required()
    @check_role('manager')
    def put(self, employee_id):
        data = request.get_json()
        new_shop_id = data.get('shop_id')
        
        if not new_shop_id:
            return make_response(jsonify({'error': 'shop_id is required'}), 400)
        
        employee = Employees.query.get(employee_id)
        if not employee:
            return make_response(jsonify({'error': 'Employee not found'}), 404)
        
        employee.shop_id = new_shop_id
        db.session.commit()
        
        return make_response(jsonify({'message': 'Shop ID updated successfully'}), 200)



# class GetEmployeeLeaderboard(Resource):
#     @jwt_required()
#     def get(self):
#         try:
#             # Join Sales and SoldItem tables to ensure aggregation works correctly
#             sales = db.session.query(
#                 Sales.user_id,
#                 db.func.count(Sales.sales_id).label('total_sales'),
#                 db.func.sum(SoldItem.total_price).label('total_amount')
#             ).join(SoldItem, Sales.sales_id == SoldItem.sales_id) \
#              .group_by(Sales.user_id) \
#              .order_by(db.func.sum(SoldItem.total_price).desc()) \
#              .all()

#             if not sales:
#                 return {"message": "No sales found"}, 404

#             leaderboard = []

#             for sale in sales:
#                 user = Users.query.filter_by(users_id=sale.user_id).first()
#                 employee_name = user.username if user else "Unknown Employee"

#                 leaderboard.append({
#                     "employee_name": employee_name,
#                     "total_sales": f"{sale.total_sales:,}",
#                     "total_amount": f"{sale.total_amount:,.2f}" if sale.total_amount else "0.00"
#                 })

#             return make_response(jsonify(leaderboard), 200)

#         except Exception as e:
#             return {"error": str(e)}, 500


class GetEmployeeLeaderboard(Resource):
    @jwt_required()
    def get(self):
        try:
            start_date = datetime(2025, 10, 1)

            # Pagination params
            page = request.args.get("page", 1, type=int)
            per_page = request.args.get("per_page", 10, type=int)

            # Subquery: total amount paid per sale
            payments_subq = (
                db.session.query(
                    SalesPaymentMethods.sale_id,
                    func.coalesce(func.sum(SalesPaymentMethods.amount_paid), 0).label("amount_paid")
                )
                .group_by(SalesPaymentMethods.sale_id)
                .subquery()
            )

            # Expression: choose based on sale status
            total_amount_expr = case(
                (Sales.status == "paid", func.coalesce(payments_subq.c.amount_paid, 0)),
                (Sales.status == "unpaid", func.coalesce(Sales.balance, 0)),
                (
                    Sales.status == "partially_paid",
                    func.coalesce(payments_subq.c.amount_paid, 0) + func.coalesce(Sales.balance, 0)
                ),
                else_=0
            )

            # Base query (aggregated per employee)
            base_query = (
                db.session.query(
                    Sales.user_id,
                    func.count(Sales.sales_id).label("total_sales"),
                    func.coalesce(func.sum(total_amount_expr), 0).label("total_amount")
                )
                .join(SoldItem, Sales.sales_id == SoldItem.sales_id)
                .outerjoin(payments_subq, Sales.sales_id == payments_subq.c.sale_id)
                .filter(Sales.created_at >= start_date)
                .group_by(Sales.user_id)
                .order_by(func.sum(total_amount_expr).desc())
            )

            # Total employees (for pagination)
            total_records = base_query.count()
            total_pages = (total_records + per_page - 1) // per_page

            # Apply pagination
            sales = (
                base_query
                .offset((page - 1) * per_page)
                .limit(per_page)
                .all()
            )

            if not sales:
                return make_response(jsonify({
                    "data": [],
                    "pagination": {
                        "total": total_records,
                        "pages": total_pages,
                        "current_page": page,
                        "per_page": per_page
                    }
                }), 200)

            leaderboard = []
            for sale in sales:
                user = Users.query.filter_by(users_id=sale.user_id).first()
                employee_name = user.username if user else "Unknown Employee"

                leaderboard.append({
                    "employee_name": employee_name,
                    "total_sales": f"{sale.total_sales:,}",
                    "total_amount": f"{sale.total_amount:,.2f}" if sale.total_amount else "0.00"
                })

            return make_response(jsonify({
                "data": leaderboard,
                "pagination": {
                    "total": total_records,
                    "pages": total_pages,
                    "current_page": page,
                    "per_page": per_page,
                    "has_next": page < total_pages,
                    "has_prev": page > 1
                }
            }), 200)

        except Exception as e:
            return {"error": str(e)}, 500




