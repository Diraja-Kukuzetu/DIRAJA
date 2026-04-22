from flask_restful import Resource, reqparse
from flask import request
from flask_jwt_extended import jwt_required
from datetime import datetime
from app import db
from Server.Models.Employees import Employees
from Server.Models.Users import Users
from Server.Models.MeritLedger import MeritLedger
from Server.Models.Meritpoints import MeritPoints
from functools import wraps
from sqlalchemy import desc
from flask_jwt_extended import jwt_required,get_jwt_identity
from flask import jsonify,request,make_response


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

class AssignMeritPoints(Resource):
    @jwt_required()
    @check_role('manager')  # or other permitted roles
    def post(self, employee_id):
        data = request.get_json()

        merit_id = data.get("merit_id")
        comment = data.get("comment", "")

        if not merit_id:
            return {"message": "'merit_id' is required."}, 400

        # Fetch employee
        employee = Employees.query.get(employee_id)
        if not employee:
            return {"message": "Employee not found."}, 404

        # Fetch merit reason
        merit = MeritPoints.query.filter_by(meritpoint_id=merit_id).first()
        if not merit:
            return {"message": "Merit point reason not found."}, 404

        # Update employee points
        employee.merit_points += merit.point
        employee.merit_points_updated_at = datetime.utcnow()

        # Save to ledger
        ledger_entry = MeritLedger(
            employee_id=employee.employee_id,
            merit_id=merit.meritpoint_id,
            comment=comment,
            resulting_points=employee.merit_points,
            date=datetime.utcnow()
        )

        db.session.add(ledger_entry)
        db.session.commit()

        return {
            "message": "Merit points assigned successfully.",
            "employee": {
                "id": employee.employee_id,
                "name": f"{employee.first_name} {employee.middle_name} {employee.surname}",
                "current_merit_points": employee.merit_points
            },
            "ledger": {
                "merit_id": merit.meritpoint_id,
                "reason": merit.reason,
                "point_change": merit.point,
                "comment": comment,
                "date": ledger_entry.date.isoformat() if ledger_entry.date else None,
                "resulting_points": ledger_entry.resulting_points
            }
        }, 200


class ResetAllMeritPoints(Resource):
    @jwt_required()
    @check_role('manager')
    def post(self):
        """Reset merit points to 100 for all employees (Monthly merit reset)"""
        
        data = request.get_json() or {}
        dry_run = data.get("dry_run", False)
        custom_comment = data.get("comment", "Monthly merit reset")
        
        # Get all employees
        employees = Employees.query.all()
        
        if not employees:
            return {"message": "No employees found."}, 404
        
        # Get current stats
        current_points = [e.merit_points for e in employees]
        
        if dry_run:
            return {
                "message": "Dry run - no changes made",
                "reset_type": "Monthly Merit Reset",
                "stats": {
                    "total_employees": len(employees),
                    "current_points_range": {
                        "min": min(current_points) if current_points else 0,
                        "max": max(current_points) if current_points else 0,
                        "average": sum(current_points) / len(current_points) if current_points else 0
                    },
                    "target_points": 100
                }
            }, 200
        
        # Perform the reset
        reset_count = 0
        reset_entries = []
        
        for employee in employees:
            old_points = employee.merit_points
            employee.merit_points = 100
            employee.merit_points_updated_at = datetime.utcnow()
            
            # Create ledger entry with NULL merit_id for monthly reset
            ledger_entry = MeritLedger(
                employee_id=employee.employee_id,
                merit_id=None,  # Nullable for system resets
                comment=f"Monthly merit reset: Points changed from {old_points} to 100. {custom_comment}",
                resulting_points=100,
                date=datetime.utcnow()
            )
            
            db.session.add(ledger_entry)
            reset_count += 1
            
            reset_entries.append({
                "employee_id": employee.employee_id,
                "employee_name": f"{employee.first_name} {employee.middle_name} {employee.surname}".strip(),
                "old_points": old_points,
                "new_points": 100
            })
        
        db.session.commit()
        
        return {
            "message": "Monthly merit points reset completed successfully.",
            "reset_type": "Monthly Merit Reset",
            "reset_count": reset_count,
            "target_points": 100,
            "comment": custom_comment,
            "affected_employees": reset_entries[:10],  # Show first 10 to avoid huge response
            "total_affected": len(reset_entries),
            "reset_date": datetime.utcnow().isoformat()
        }, 200


class GetMeritLedger(Resource):
    def get(self):
        # Get pagination parameters from query string
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)  # Default 20 items per page
        
        # Get sorting parameters
        sort_by = request.args.get('sort_by', 'date')
        sort_order = request.args.get('sort_order', 'desc')  # Default descending (newest first)
        
        # Get filter parameters
        employee_id = request.args.get('employee_id', type=int)
        merit_type = request.args.get('type')  # 'merit' or 'demerit'
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        search = request.args.get('search', '')
        
        # Base query
        query = MeritLedger.query
        
        # Apply filters
        if employee_id:
            query = query.filter(MeritLedger.employee_id == employee_id)
        
        if merit_type:
            if merit_type == 'merit':
                query = query.filter(MeritLedger.merit_reason.has(point__gt=0))
            elif merit_type == 'demerit':
                query = query.filter(MeritLedger.merit_reason.has(point__lt=0))
        
        if start_date:
            query = query.filter(MeritLedger.date >= start_date)
        
        if end_date:
            query = query.filter(MeritLedger.date <= end_date)
        
        
        # Apply sorting
        sort_mapping = {
            'date': MeritLedger.date,
            'employee': MeritLedger.employee_id,
            'points': MeritLedger.merit_id,
            'resulting_points': MeritLedger.resulting_points
        }
        
        sort_column = sort_mapping.get(sort_by, MeritLedger.date)
        if sort_order == 'desc':
            query = query.order_by(desc(sort_column))
        else:
            query = query.order_by(sort_column)
        
        # Get paginated results
        paginated = query.paginate(page=page, per_page=per_page, error_out=False)
        
        # Prepare response data
        result = []
        for entry in paginated.items:
            result.append({
                'meritledger_id': entry.meritledger_id,
                'employee_id': entry.employee_id,
                'employee_name': f"{entry.employee.first_name} {entry.employee.surname}" if entry.employee else None,
                'employee_first_name': entry.employee.first_name if entry.employee else None,
                'employee_last_name': entry.employee.surname if entry.employee else None,
                'employee_department': entry.employee.department if entry.employee else None,
                'employee_designation': entry.employee.designation if entry.employee else None,
                'merit_id': entry.merit_id,
                'merit_reason': entry.merit_reason.reason if entry.merit_reason else None,
                'merit_point': entry.merit_reason.point if entry.merit_reason else None,
                'comment': entry.comment,
                'date': entry.date.strftime('%Y-%m-%d %H:%M:%S'),
                'created_at': entry.date.strftime('%Y-%m-%d %H:%M:%S'),  # For backward compatibility
                'resulting_points': entry.resulting_points
            })
        
        # Return paginated response
        return {
            'merit_ledger': result,
            'pagination': {
                'page': paginated.page,
                'per_page': paginated.per_page,
                'total_pages': paginated.pages,
                'total_items': paginated.total,
                'has_next': paginated.has_next,
                'has_prev': paginated.has_prev,
                'next_page': paginated.next_num if paginated.has_next else None,
                'prev_page': paginated.prev_num if paginated.has_prev else None
            }
        }, 200
    

class GetEmployeeMeritLedger(Resource):
    @jwt_required()
    def get(self, user_id):
        # 1. Get user first
        user = Users.query.get(user_id)
        if not user:
            return {"message": "User not found."}, 404
        
        # 2. Check if user has an employee attached
        if not user.employee_id:
            return {"message": "This user has no linked employee."}, 400

        employee = Employees.query.get(user.employee_id)
        if not employee:
            return {"message": "Employee not found."}, 404

        # 3. Load merit ledger for that employee
        ledger_entries = MeritLedger.query.filter_by(employee_id=user.employee_id)\
                                          .order_by(MeritLedger.date.desc())\
                                          .all()

        # 4. Build ledger history with null checks
        ledger_history = []
        for entry in ledger_entries:
            # Handle cases where merit_reason might be None (e.g., system resets)
            if entry.merit_reason:
                reason = entry.merit_reason.reason
                point_value = entry.merit_reason.point
            else:
                reason = "System Reset"  # Default reason for system resets
                point_value = 0  # Default point value for system resets
            
            ledger_history.append({
                "ledger_id": entry.meritledger_id,
                "merit_id": entry.merit_id if entry.merit_id else None,
                "reason": reason,
                "point_value": point_value,
                "comment": entry.comment if entry.comment else "No comment",
                "date": entry.date.isoformat() if entry.date else None,
                "resulting_points": entry.resulting_points
            })

        return {
            "employee": {
                "id": employee.employee_id,
                "name": f"{employee.first_name} {employee.middle_name or ''} {employee.surname}".strip(),
                "current_merit_points": employee.merit_points,
            },
            "ledger_history": ledger_history
        }, 200