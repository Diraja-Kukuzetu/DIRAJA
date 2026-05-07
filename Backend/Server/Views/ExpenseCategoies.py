from flask_restful import Resource
from flask import request, jsonify, make_response
from flask_jwt_extended import jwt_required, get_jwt_identity
from app import db
from Server.Models.Users import Users
from Server.Models.ExpenseCategory import ExpenseCategory, ExpenseItem
from functools import wraps


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


# ==================== EXPENSE CATEGORY RESOURCES ====================

class PostExpenseCategory(Resource):
    @jwt_required()
    @check_role('manager')
    def post(self):
        data = request.get_json()

        category_name = data.get('category_name')
        category_type = data.get('type')

        if not category_name or not category_type:
            return {"message": "Both category_name and type are required."}, 400

        # Check if category already exists
        existing = ExpenseCategory.query.filter_by(
            category_name=category_name, 
            type=category_type
        ).first()
        
        if existing:
            return {"message": "This expense category already exists."}, 409

        new_category = ExpenseCategory(
            category_name=category_name,
            type=category_type
        )

        db.session.add(new_category)
        db.session.commit()

        return {
            "message": "Expense category created successfully.",
            "expense_category": {
                "id": new_category.id,
                "category_name": new_category.category_name,
                "type": new_category.type
            }
        }, 201


class GetAllExpenseCategories(Resource):
    @jwt_required()
    def get(self):
        categories = ExpenseCategory.query.all()
        result = []

        for category in categories:
            result.append({
                "id": category.id,
                "category_name": category.category_name,
                "type": category.type,
                "items_count": len(category.items) if category.items else 0
            })

        return result, 200


class ExpenseCategoryResource(Resource):
    @jwt_required()
    @check_role('manager')
    def get(self, category_id=None):
        """Retrieve a single expense category by ID or all categories if no ID is provided."""
        if category_id:
            category = ExpenseCategory.query.get(category_id)
            
            if not category:
                return {"message": "Expense category not found."}, 404

            return {
                "id": category.id,
                "category_name": category.category_name,
                "type": category.type,
                "items": [
                    {
                        "id": item.id,
                        "item_name": item.item_name,
                        "description": item.description,
                        "created_at": item.created_at.isoformat() if item.created_at else None
                    }
                    for item in category.items
                ]
            }, 200

        # If no category_id provided, return all categories
        categories = ExpenseCategory.query.all()
        return [
            {
                "id": category.id,
                "category_name": category.category_name,
                "type": category.type,
                "items_count": len(category.items) if category.items else 0
            }
            for category in categories
        ], 200

    @jwt_required()
    @check_role('manager')
    def put(self, category_id):
        """Update an existing expense category by category_id."""
        data = request.get_json()
        category = ExpenseCategory.query.get(category_id)

        if not category:
            return {"message": "Expense category not found."}, 404

        category_name = data.get('category_name', category.category_name)
        category_type = data.get('type', category.type)

        if category_name != category.category_name:
            existing = ExpenseCategory.query.filter_by(
                category_name=category_name,
                type=category_type
            ).first()
            if existing:
                return {"message": "This expense category already exists."}, 409
            category.category_name = category_name

        if category_type != category.type:
            category.type = category_type

        db.session.commit()

        return {
            "message": "Expense category updated successfully.",
            "expense_category": {
                "id": category.id,
                "category_name": category.category_name,
                "type": category.type
            }
        }, 200

    @jwt_required()
    @check_role('manager')
    def delete(self, category_id):
        """Delete an expense category by category_id."""
        category = ExpenseCategory.query.get(category_id)

        if not category:
            return {"message": "Expense category not found."}, 404

        # Check if category has items
        if category.items:
            return {
                "message": "Cannot delete category with existing items. Delete or reassign items first.",
                "items_count": len(category.items)
            }, 400

        db.session.delete(category)
        db.session.commit()

        return {"message": "Expense category deleted successfully."}, 200


# ==================== EXPENSE ITEMS RESOURCES ====================

class PostExpenseItem(Resource):
    @jwt_required()
    @check_role('manager')
    def post(self):
        data = request.get_json()

        item_name = data.get('item_name')
        description = data.get('description')
        category_id = data.get('category_id')

        if not item_name or not category_id:
            return {"message": "Both item_name and category_id are required."}, 400

        # Check if category exists
        category = ExpenseCategory.query.get(category_id)
        if not category:
            return {"message": "Expense category not found."}, 404

        # Check if item already exists in this category
        existing = ExpenseItem.query.filter_by(
            item_name=item_name,
            category_id=category_id
        ).first()
        
        if existing:
            return {"message": "This expense item already exists in this category."}, 409

        new_item = ExpenseItem(
            item_name=item_name,
            description=description,
            category_id=category_id
        )

        db.session.add(new_item)
        db.session.commit()

        return {
            "message": "Expense item created successfully.",
            "expense_item": {
                "id": new_item.id,
                "item_name": new_item.item_name,
                "description": new_item.description,
                "category_id": new_item.category_id,
                "category_name": category.category_name,
                "created_at": new_item.created_at.isoformat() if new_item.created_at else None
            }
        }, 201


class GetAllExpenseItems(Resource):
    @jwt_required()
    def get(self):
        items = ExpenseItem.query.all()
        result = []

        for item in items:
            result.append({
                "id": item.id,
                "item_name": item.item_name,
                "description": item.description,
                "category_id": item.category_id,
                "category_name": item.category.category_name if item.category else None,
                "created_at": item.created_at.isoformat() if item.created_at else None
            })

        return result, 200


class ExpenseItemResource(Resource):
    @jwt_required()
    @check_role('manager')
    def get(self, item_id=None, category_id=None):
        """Retrieve expense items by ID, by category, or all items."""
        
        # Get specific item by ID
        if item_id:
            item = ExpenseItem.query.get(item_id)
            if not item:
                return {"message": "Expense item not found."}, 404
            
            return {
                "id": item.id,
                "item_name": item.item_name,
                "description": item.description,
                "category_id": item.category_id,
                "category_name": item.category.category_name if item.category else None,
                "created_at": item.created_at.isoformat() if item.created_at else None
            }, 200
        
        # Get items by category
        if category_id:
            category = ExpenseCategory.query.get(category_id)
            if not category:
                return {"message": "Expense category not found."}, 404
            
            return {
                "category_id": category.id,
                "category_name": category.category_name,
                "type": category.type,
                "items": [
                    {
                        "id": item.id,
                        "item_name": item.item_name,
                        "description": item.description,
                        "created_at": item.created_at.isoformat() if item.created_at else None
                    }
                    for item in category.items
                ]
            }, 200
        
        # Return all items if no specific parameters
        items = ExpenseItem.query.all()
        return [
            {
                "id": item.id,
                "item_name": item.item_name,
                "description": item.description,
                "category_id": item.category_id,
                "category_name": item.category.category_name if item.category else None
            }
            for item in items
        ], 200

    @jwt_required()
    @check_role('manager')
    def put(self, item_id):
        """Update an existing expense item."""
        data = request.get_json()
        item = ExpenseItem.query.get(item_id)

        if not item:
            return {"message": "Expense item not found."}, 404

        item_name = data.get('item_name', item.item_name)
        description = data.get('description', item.description)
        category_id = data.get('category_id', item.category_id)

        # If category_id is being changed, verify the new category exists
        if category_id != item.category_id:
            category = ExpenseCategory.query.get(category_id)
            if not category:
                return {"message": "New expense category not found."}, 404

        # Check if item name already exists in the category
        if item_name != item.item_name or category_id != item.category_id:
            existing = ExpenseItem.query.filter_by(
                item_name=item_name,
                category_id=category_id
            ).first()
            if existing and existing.id != item_id:
                return {"message": "An expense item with this name already exists in this category."}, 409

        item.item_name = item_name
        item.description = description
        item.category_id = category_id

        db.session.commit()

        return {
            "message": "Expense item updated successfully.",
            "expense_item": {
                "id": item.id,
                "item_name": item.item_name,
                "description": item.description,
                "category_id": item.category_id,
                "category_name": item.category.category_name if item.category else None
            }
        }, 200

    @jwt_required()
    @check_role('manager')
    def delete(self, item_id):
        """Delete an expense item by ID."""
        item = ExpenseItem.query.get(item_id)

        if not item:
            return {"message": "Expense item not found."}, 404

        db.session.delete(item)
        db.session.commit()

        return {"message": "Expense item deleted successfully."}, 200


# ==================== HELPER RESOURCES ====================

class CategoryWithItemsResource(Resource):
    @jwt_required()
    def get(self, category_id):
        """Get a complete category with all its items."""
        category = ExpenseCategory.query.get(category_id)
        
        if not category:
            return {"message": "Expense category not found."}, 404

        return {
            "id": category.id,
            "category_name": category.category_name,
            "type": category.type,
            "items": [
                {
                    "id": item.id,
                    "item_name": item.item_name,
                    "description": item.description
                }
                for item in category.items
            ]
        }, 200