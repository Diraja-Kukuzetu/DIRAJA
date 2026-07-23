from flask_restful import Resource
from flask import request, jsonify, make_response
from flask_jwt_extended import jwt_required, get_jwt_identity
from app import db
from Server.Models.Users import Users
from Server.Models.StockItems import StockItems, EtimsItem
from Server.Views.Services.etims_services import etims_service
from functools import wraps
import logging

logger = logging.getLogger(__name__)


def check_role(required_role):
    def wrapper(fn):
        @wraps(fn)
        def decorator(*args, **kwargs):
            current_user_id = get_jwt_identity()
            user = Users.query.get(current_user_id)
            if user and user.role != required_role:
                return make_response(jsonify({"error": "Unauthorized access"})), 403
            return fn(*args, **kwargs)
        return decorator
    return wrapper


class PostStockItem(Resource):
    @jwt_required()
    @check_role('manager')
    def post(self):
        """
        POST /api/diraja/add-stock-items
        Create a new stock item and sync to eTims
        """
        data = request.get_json()

        # Validate required fields
        item_name = data.get('item_name')
        if not item_name:
            return {"message": "item_name is required."}, 400

        # Check if item already exists
        existing = StockItems.query.filter_by(item_name=item_name).first()
        if existing:
            return {"message": "This item already exists."}, 409

        # Validate stock_type
        stock_type = data.get('stock_type', 'Product')
        if stock_type not in ['Service', 'Product']:
            return {"message": "stock_type must be either 'Service' or 'Product'"}, 400

        # Prepare data for service
        stock_item_data = {
            'item_name': item_name,
            'item_code': data.get('item_code'),
            'unit_price': data.get('unit_price'),
            'pack_price': data.get('pack_price'),
            'pack_quantity': data.get('pack_quantity'),
            'category': data.get('category'),
            'stock_item_type': stock_type,  # Changed from 'stock_type' to 'stock_item_type'
            # eTims fields
            'org_country_code': data.get('org_country_code', 'KE'),
            'item_type_code': data.get('item_type_code', '1'),
            'tax_code': data.get('tax_code', 'A'),
            'qty_unit_code': data.get('qty_unit_code', 'U'),
            'pkg_unit_code': data.get('pkg_unit_code', 'CT'),
            'item_class_code': data.get('item_class_code', '99000000'),
            'initial_stock': data.get('initial_stock', 0)
        }

        # Use eTims service to create and sync
        success, result = etims_service.create_and_sync_item(stock_item_data)

        if not success:
            return {"message": result.get('error', 'Failed to create item')}, 400

        return result, 201


class GetAllStockItems(Resource):
    @jwt_required()
    def get(self):
        """
        GET /stock-items
        Get all stock items with eTims sync status
        
        Query Parameters:
        - type: Filter by stock type ('Service' or 'Product') - optional
        """
        # Get query parameters
        stock_type = request.args.get('type')
        
        # Build query
        query = StockItems.query
        
        # Apply filter if type parameter is provided
        if stock_type:
            if stock_type not in ['Service', 'Product']:
                return {"message": "Type must be either 'Service' or 'Product'"}, 400
            query = query.filter_by(stock_item_type=stock_type)
        
        items = query.all()
        result = []

        for item in items:
            result.append({
                "id": item.id,
                "item_name": item.item_name,
                "item_code": item.item_code,
                "unit_price": item.unit_price,
                "pack_price": item.pack_price,
                "pack_quantity": item.pack_quantity,
                "category": item.category,
                "stock_type": item.stock_item_type,  # Changed from item.stock_type to item.stock_item_type
                "etims_synced": item.etims_synced,
                "etims_item_code": item.etims_item_code,
                "etims_sync_date": item.etims_sync_date.isoformat() if item.etims_sync_date else None
            })

        return {
            "stock_items": result,
            "count": len(result),
            "filter": stock_type if stock_type else "all"
        }, 200



class StockItem(Resource):
    @jwt_required()
    @check_role('manager')
    def get(self, item_id=None):
        """
        GET /stock-items/<item_id>
        Get a single stock item
        """
        if item_id:
            item = StockItems.query.get(item_id)
            if not item:
                return {"message": "Item not found."}, 404

            return {
                "id": item.id,
                "item_name": item.item_name,
                "item_code": item.item_code,
                "unit_price": item.unit_price,
                "pack_price": item.pack_price,
                "pack_quantity": item.pack_quantity,
                "category": item.category,
                "stock_type": item.stock_item_type,  # Changed from item.stock_type to item.stock_item_type
                "etims_synced": item.etims_synced,
                "etims_item_code": item.etims_item_code,
                "etims_sync_date": item.etims_sync_date.isoformat() if item.etims_sync_date else None
            }, 200

        # If no item_id provided, return all items
        items = StockItems.query.all()
        return [
            {
                "id": item.id,
                "item_name": item.item_name,
                "item_code": item.item_code,
                "unit_price": item.unit_price,
                "pack_price": item.pack_price,
                "pack_quantity": item.pack_quantity,
                "category": item.category,
                "stock_type": item.stock_item_type,  # Changed from item.stock_type to item.stock_item_type
                "etims_synced": item.etims_synced,
                "etims_item_code": item.etims_item_code
            }
            for item in items
        ], 200

    @jwt_required()
    @check_role('manager')
    def put(self, item_id):
        """
        PUT /stock-items/<item_id>
        Update a stock item and sync to eTims
        """
        data = request.get_json()
        
        if not data:
            return {"message": "No input data provided"}, 400

        # Validate stock_type if provided (frontend sends 'stock_type', we need to map to 'stock_item_type')
        if 'stock_type' in data:
            if data['stock_type'] not in ['Service', 'Product']:
                return {"message": "stock_type must be either 'Service' or 'Product'"}, 400
            # Map frontend 'stock_type' to model field 'stock_item_type'
            data['stock_item_type'] = data.pop('stock_type')

        # Use eTims service to update and sync
        success, result = etims_service.update_and_sync_item(item_id, data)

        if not success:
            return {"message": result.get('error', 'Failed to update item')}, 400

        return result, 200

    @jwt_required()
    @check_role('manager')
    def delete(self, item_id):
        """
        DELETE /stock-items/<item_id>
        Delete a stock item from local and eTims
        """
        # Use eTims service to delete
        success, result = etims_service.delete_and_sync_item(item_id)

        if not success:
            return {"message": result.get('error', 'Failed to delete item')}, 400

        return result, 200


# ==========================================================
# NEW RESOURCE: Sync Items to eTims
# ==========================================================

class SyncAllItemsResource(Resource):
    @jwt_required()
    @check_role('manager')
    def post(self):
        """
        POST /stock-items/sync-all
        Sync all unsynced items to eTims
        """
        try:
            results = etims_service.sync_all_unsynced_items()
            
            return {
                "message": "Bulk sync completed",
                "results": results
            }, 200
            
        except Exception as e:
            logger.error(f"Error in bulk sync: {str(e)}")
            return {"message": f"Error during sync: {str(e)}"}, 500


# ==========================================================
# NEW RESOURCE: Sync Single Item
# ==========================================================

class SyncSingleItemResource(Resource):
    @jwt_required()
    @check_role('manager')
    def post(self, item_id):
        """
        POST /stock-items/<item_id>/sync
        Sync a single item to eTims
        """
        try:
            item = StockItems.query.get(item_id)
            if not item:
                return {"message": "Item not found."}, 404

            if item.etims_synced:
                return {
                    "message": "Item already synced to eTims",
                    "etims_item_code": item.etims_item_code
                }, 400

            success, result = etims_service.sync_item_to_etims(item)

            if not success:
                return {"message": result.get('error', 'Failed to sync item')}, 400

            return result, 200
            
        except Exception as e:
            logger.error(f"Error syncing item: {str(e)}")
            return {"message": f"Error syncing item: {str(e)}"}, 500


# ==========================================================
# NEW RESOURCE: Get eTims Items
# ==========================================================

class ETimsItemsResource(Resource):
    @jwt_required()
    def get(self):
        """
        GET /etims-items
        Fetch all items from the EtimsItem model (locally stored eTims items)
        """
        try:
            # Query all eTims items from local database
            etims_items = EtimsItem.query.order_by(EtimsItem.created_at.desc()).all()
            
            # Format the response
            data = []
            for item in etims_items:
                # Get local stock item if exists
                local_item = None
                if item.local_item_id:
                    local_item = StockItems.query.get(item.local_item_id)
                
                data.append({
                    "id": item.id,
                    "itemCode": item.item_code,
                    "code": item.item_code,
                    "name": item.name,
                    "orgCountryCode": item.org_country_code,
                    "unitPrice": item.unit_price,
                    "itemTypeCode": item.item_type_code,
                    "taxCode": item.tax_code,
                    "qtyUnitCode": item.qty_unit_code,
                    "pkgUnitCode": item.pkg_unit_code,
                    "itemClassCode": item.item_class_code,
                    "stock": item.stock,
                    "local_item_id": item.local_item_id,
                    "local_item_name": local_item.item_name if local_item else None,
                    "local_stock_type": local_item.stock_item_type if local_item else None,  # Changed to stock_item_type
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                    "updated_at": item.updated_at.isoformat() if item.updated_at else None
                })
            
            return {
                "success": True,
                "data": data,
                "count": len(data),
                "message": f"Retrieved {len(data)} eTims items from local database"
            }, 200
                
        except Exception as e:
            logger.error(f"Error fetching eTims items: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "message": "Failed to fetch eTims items"
            }, 500


# ==========================================================
# NEW RESOURCE: Get Reference Codes
# ==========================================================

class ETimsReferenceResource(Resource):
    @jwt_required()
    def get(self):
        """
        GET /etims-reference
        Fetch all reference codes from eTims (countries, currencies, etc.)
        """
        try:
            countries = etims_service.get_countries()
            currencies = etims_service.get_currencies()
            qty_units = etims_service.get_qty_unit_codes()
            pkg_units = etims_service.get_pkg_unit_codes()
            item_codes = etims_service.get_item_codes()
            branches = etims_service.get_branches()
            
            return {
                "success": True,
                "data": {
                    "countries": countries.get('data', []) if countries['success'] else [],
                    "currencies": currencies.get('data', []) if currencies['success'] else [],
                    "qty_units": qty_units.get('data', []) if qty_units['success'] else [],
                    "pkg_units": pkg_units.get('data', []) if pkg_units['success'] else [],
                    "item_codes": item_codes.get('data', []) if item_codes['success'] else [],
                    "branches": branches.get('data', []) if branches['success'] else []
                }
            }, 200
            
        except Exception as e:
            logger.error(f"Error fetching reference codes: {str(e)}")
            return {"message": str(e)}, 500

