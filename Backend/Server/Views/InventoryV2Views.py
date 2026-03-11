from flask_restful import Resource
from Server.Models.InventoryV2 import InventoryV2
from Server.Models.TransferV2 import TransfersV2
from Server.Models.StoreReturn import ReturnsV2
from Server.Models.Shops import Shops
from Server.Models.ShopstockV2 import ShopStockV2
from Server.Models.BankAccounts import BankAccount, BankingTransaction
from Server.Models.Accounting.PurchaseLedger import PurchaseLedgerInventory
from Server.Models.Accounting.PurchaseLedger import DistributionLedger
from Server.Models.Users import Users
from app import db
import json
from functools import wraps
from pywebpush import webpush, WebPushException
from flask import request, make_response, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request
from dateutil import parser
from flask_restful import reqparse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import or_, func, and_
from datetime import datetime
import logging
from Server.Models.PushSubscription import PushSubscription
from Server.Models.Supplier import SupplierHistory , Suppliers
from flask import current_app
import re


def check_role(required_role):
    def wrapper(fn):
        @wraps(fn)
        def decorator(*args, **kwargs):
            current_user_id = get_jwt_identity()
            user = Users.query.get(current_user_id)
            if user and user.role != required_role:
                 return make_response( jsonify({"error": "Unauthorized access"}), 403 )       
            current_user_id = get_jwt_identity()
            user = Users.query.get(current_user_id)
            if user and user.role != required_role:
                 return make_response( jsonify({"error": "Unauthorized access"}), 403 )       
            return fn(*args, **kwargs)
        return decorator
    return wrapper
# def check_role(required_role):
#     def wrapper(fn):
#         @wraps(fn)
#         def decorator(*args, **kwargs):
#             verify_jwt_in_request()
#             user_role = request.headers.get('X-User-Role', None)
            
#             if user_role != required_role:
#                 return jsonify({"message": "Access denied: insufficient permissions"}), 403
#             return fn(*args, **kwargs)
#         return decorator
#     return wrapper


class GetInventoryByBatchV2(Resource):
    @jwt_required()
    @check_role('manager')
    def get(self):
        try:
            inventories = InventoryV2.query.all()

            def batch_sort_key(inventory):
                match = re.match(r"^.*-(?P<letter>[A-Z])(?P<number>\d+)$", inventory.BatchNumber)
                if match:
                    letter = match.group("letter")
                    number = int(match.group("number"))
                    return (letter, number)
                return ("Z", 9999)

            sorted_inventories = sorted(inventories, key=batch_sort_key)

            inventory_list = []
            for inv in sorted_inventories:
                inventory_list.append({
                    'inventoryV2_id': inv.inventoryV2_id,
                    'itemname': inv.itemname,
                    'quantity': inv.quantity,
                    'metric': inv.metric,
                    'unitCost': inv.unitCost,
                    'totalCost': inv.totalCost,
                    'amountPaid': inv.amountPaid,
                    'unitPrice': inv.unitPrice,
                    'BatchNumber': inv.BatchNumber,
                    'Suppliername': inv.Suppliername,
                    'Supplier_location': inv.Supplier_location,
                    'ballance': inv.ballance,
                    'note': inv.note,
                    'created_at': inv.created_at.strftime('%Y-%m-%d')
                })

            return make_response(jsonify({'inventories': inventory_list}), 200)

        except Exception as e:
            return make_response(jsonify({'message': 'Error fetching inventory', 'error': str(e)}), 500)


class ProcessInventoryV2(Resource):
    @jwt_required()
    def post(self):
        data = request.get_json()
        current_user_id = get_jwt_identity()

        # Required fields for processing inventory
        required_fields = [
            'source_inventory_id', 'processed_items', 'note'
        ]
        if not all(field in data for field in required_fields):
            return {'message': 'Missing required fields'}, 400

        source_inventory_id = data['source_inventory_id']
        processed_items = data['processed_items']  # List of processed items
        note = data['note']
        
        # Get created_at from payload if provided
        created_at = data.get('created_at')  # This will be None if not provided

        try:
            # ✅ Fetch source inventory item
            source_item = InventoryV2.query.get(source_inventory_id)
            if not source_item:
                return {'message': 'Source inventory item not found'}, 404

            # ✅ Validate processed items
            total_processed_quantity = 0
            for item in processed_items:
                if not all(field in item for field in ['itemname', 'quantity', 'metric', 'unitPrice']):
                    return {'message': 'Missing fields in processed items'}, 400
                total_processed_quantity += item['quantity']

            # ✅ Ensure we're not processing more than available
            if source_item.quantity < total_processed_quantity:
                return {'message': 'Insufficient inventory quantity for processing'}, 400

            # ✅ Calculate cost allocation based on quantity ratio
            processed_inventory_items = []
            
            for item_data in processed_items:
                # Calculate the cost allocation for this processed item
                quantity_ratio = item_data['quantity'] / total_processed_quantity
                allocated_cost = source_item.totalCost * quantity_ratio
                allocated_amount_paid = source_item.amountPaid * quantity_ratio
                
                # Calculate unit cost based on allocated cost
                unit_cost = allocated_cost / item_data['quantity'] if item_data['quantity'] > 0 else 0

                # Create new inventory item for the processed product
                new_processed_item = InventoryV2(
                    itemname=item_data['itemname'],
                    initial_quantity=item_data['quantity'],
                    quantity=item_data['quantity'],
                    metric=item_data['metric'],
                    unitCost=unit_cost,
                    totalCost=allocated_cost,
                    amountPaid=allocated_amount_paid,
                    unitPrice=item_data['unitPrice'],
                    BatchNumber=source_item.BatchNumber,  # Same batch number
                    user_id=current_user_id,
                    Trasnaction_type_credit=item_data['quantity'],  # Credit for new items
                    Transcation_type_debit=0.0,
                    paymentRef=source_item.paymentRef,
                    Suppliername=source_item.Suppliername,
                    Supplier_location=source_item.Supplier_location,
                    ballance=item_data['quantity'],
                    note=f"Processed from {source_item.itemname}.",
                    source=source_item.source,
                    created_at=created_at  # ✅ Set created_at from payload
                )

                db.session.add(new_processed_item)
                processed_inventory_items.append({
                    'itemname': item_data['itemname'],
                    'quantity': item_data['quantity'],
                    'metric': item_data['metric'],
                    'new_item_id': new_processed_item.inventoryV2_id
                })

            # ✅ Deduct the processed quantity from source item
            source_item.quantity -= total_processed_quantity
            source_item.ballance = source_item.quantity
            source_item.Transcation_type_debit = total_processed_quantity
            source_item.note = f"Processed into multiple items. {note}"

            db.session.commit()

            return {
                'message': 'Inventory processed successfully',
                'processed_items': processed_inventory_items,
                'source_item_remaining_quantity': source_item.quantity
            }, 201

        except Exception as e:
            db.session.rollback()
            return {'message': 'Error processing inventory', 'error': str(e)}, 500


class DistributeInventoryV2(Resource):
    @jwt_required()
    def post(self):
        data = request.get_json()
        current_user_id = get_jwt_identity()

        required_fields = [
            'shop_id', 'inventoryV2_id', 'quantity', 'itemname',
            'unitCost', 'amountPaid', 'BatchNumber', 'created_at', 'metric'
        ]
        if not all(field in data for field in required_fields):
            return {'message': 'Missing required fields'}, 400

        shop_id = data['shop_id']
        inventoryV2_id = data['inventoryV2_id']
        quantity = data['quantity']
        metric = data['metric']
        itemname = data['itemname']
        unitCost = data['unitCost']
        amountPaid = data['amountPaid']
        BatchNumber = data['BatchNumber']

        try:
            distribution_date = parser.isoparse(data['created_at'])
        except ValueError:
            return {'message': 'Invalid date format'}, 400

        # ✅ Fetch inventory item
        inventory_item = InventoryV2.query.get(inventoryV2_id)
        if not inventory_item:
            return {'message': 'Inventory item not found'}, 404

        # ✅ Ensure enough stock is available
        if inventory_item.quantity < quantity:
            return {'message': 'Insufficient inventory quantity'}, 400

        try:
            # ✅ Deduct stock immediately
            inventory_item.quantity -= quantity

            # ✅ Create transfer record
            new_transfer = TransfersV2(
                shop_id=shop_id,
                inventoryV2_id=inventoryV2_id,
                quantity=quantity,
                metric=metric,
                total_cost=unitCost * quantity,
                BatchNumber=BatchNumber,
                user_id=current_user_id,
                itemname=itemname,
                amountPaid=amountPaid,
                unitCost=unitCost,
                created_at=distribution_date,
                status="Not Received"
            )

            db.session.add(new_transfer)
            db.session.flush() 
            from Server.Views.Services.journal_service import DistributionJournalService


            journal_result = DistributionJournalService.post_distribution_journal(
            transfer=new_transfer,
            shop_id=shop_id
    )
            db.session.commit()

            # ✅ Send push notification
            self.send_push_to_shop(shop_id, itemname)

            return {
                'message': 'Transfer created successfully and notification sent.',
                'transfer_id': new_transfer.transferv2_id
            }, 201

        except Exception as e:
            db.session.rollback()
            return {'message': 'Error creating transfer', 'error': str(e)}, 500


    def send_push_to_shop(self, shop_id, itemname):
        """Send push notification to all subscriptions for a shop."""
        subscriptions = PushSubscription.query.filter_by(shop_id=shop_id).all()
        if not subscriptions:
            print(f"No push subscriptions found for shop {shop_id}")
            return

        # ✅ Fetch VAPID keys from app config
        vapid_private_key = current_app.config.get("VAPID_PRIVATE_KEY")
        vapid_email = current_app.config.get("VAPID_EMAIL")

        payload = {
            "title": "New Stock Alert",
            "body": f"New stock of {itemname} has been distributed to your shop. Please receive it.",
            "icon": "/logo192.png",
        }

        for sub in subscriptions:
            try:
                webpush(
                    subscription_info={
                        "endpoint": sub.endpoint,
                        "keys": {
                            "p256dh": sub.p256dh,
                            "auth": sub.auth,
                        },
                    },
                    data=json.dumps(payload),
                    vapid_private_key=vapid_private_key,
                    vapid_claims={"sub": vapid_email},
                )
                print(f"Push sent to shop {shop_id} subscriber {sub.id}")
            except WebPushException as e:
                print(f"Push failed for {sub.id}: {repr(e)}")



class DistributeInventoryV2(Resource):
    @jwt_required()
    def post(self):
        data = request.get_json()
        current_user_id = get_jwt_identity()

        required_fields = [
            'shop_id', 'inventoryV2_id', 'quantity', 'itemname',
            'unitCost', 'amountPaid', 'BatchNumber', 'created_at', 'metric'
        ]
        if not all(field in data for field in required_fields):
            return {'message': 'Missing required fields'}, 400

        shop_id = data['shop_id']
        inventoryV2_id = data['inventoryV2_id']
        quantity = data['quantity']
        metric = data['metric']
        itemname = data['itemname']
        unitCost = data['unitCost']
        amountPaid = data['amountPaid']
        BatchNumber = data['BatchNumber']

        try:
            distribution_date = parser.isoparse(data['created_at'])
        except ValueError:
            return {'message': 'Invalid date format'}, 400

        # ✅ Fetch inventory item
        inventory_item = InventoryV2.query.get(inventoryV2_id)
        if not inventory_item:
            return {'message': 'Inventory item not found'}, 404

        # ✅ Ensure enough stock is available
        if inventory_item.quantity < quantity:
            return {'message': 'Insufficient inventory quantity'}, 400

        try:
            # ✅ Deduct stock immediately
            inventory_item.quantity -= quantity

            # ✅ Create transfer record
            new_transfer = TransfersV2(
                shop_id=shop_id,
                inventoryV2_id=inventoryV2_id,
                quantity=quantity,
                metric=metric,
                total_cost=unitCost * quantity,
                BatchNumber=BatchNumber,
                user_id=current_user_id,
                itemname=itemname,
                amountPaid=amountPaid,
                unitCost=unitCost,
                created_at=distribution_date,
                status="Not Received"
            )

            db.session.add(new_transfer)
            db.session.flush() 
            from Server.Views.Services.journal_service import DistributionJournalService


            journal_result = DistributionJournalService.post_distribution_journal(
            transfer=new_transfer,
            shop_id=shop_id
    )
            db.session.commit()

            # ✅ Send push notification
            self.send_push_to_shop(shop_id, itemname)

            return {
                'message': 'Transfer created successfully and notification sent.',
                'transfer_id': new_transfer.transferv2_id
            }, 201

        except Exception as e:
            db.session.rollback()
            return {'message': 'Error creating transfer', 'error': str(e)}, 500


    def send_push_to_shop(self, shop_id, itemname):
        """Send push notification to all subscriptions for a shop."""
        subscriptions = PushSubscription.query.filter_by(shop_id=shop_id).all()
        if not subscriptions:
            print(f"No push subscriptions found for shop {shop_id}")
            return

        # ✅ Fetch VAPID keys from app config
        vapid_private_key = current_app.config.get("VAPID_PRIVATE_KEY")
        vapid_email = current_app.config.get("VAPID_EMAIL")

        payload = {
            "title": "New Stock Alert",
            "body": f"New stock of {itemname} has been distributed to your shop. Please receive it.",
            "icon": "/logo192.png",
        }

        for sub in subscriptions:
            try:
                webpush(
                    subscription_info={
                        "endpoint": sub.endpoint,
                        "keys": {
                            "p256dh": sub.p256dh,
                            "auth": sub.auth,
                        },
                    },
                    data=json.dumps(payload),
                    vapid_private_key=vapid_private_key,
                    vapid_claims={"sub": vapid_email},
                )
                print(f"Push sent to shop {shop_id} subscriber {sub.id}")
            except WebPushException as e:
                print(f"Push failed for {sub.id}: {repr(e)}")


class ReceiveTransfer(Resource):
    @jwt_required()
    def patch(self, transfer_id):
        """
        Receive a transfer with validation that received quantity 
        is not less than 97% of the sent quantity
        """
        # Get the request data
        data = request.get_json()
        
        # Validate required field
        if 'received_quantity' not in data:
            return {'message': 'received_quantity is required'}, 400
            
        received_quantity = data['received_quantity']
        
        # Validate that received_quantity is a valid number
        try:
            received_quantity = float(received_quantity)
        except ValueError:
            return {'message': 'received_quantity must be a valid number'}, 400
            
        # Get the transfer
        transfer = TransfersV2.query.get(transfer_id)
        if not transfer:
            return {'message': 'Transfer not found'}, 404

        # Check if already received (you might want to add a status field)
        if transfer.status == "Received":
            return {'message': 'Transfer already received'}, 400

        # Calculate minimum acceptable quantity (97% of sent quantity)
        MINIMUM_THRESHOLD_PERCENTAGE = 97
        minimum_acceptable = transfer.quantity * (MINIMUM_THRESHOLD_PERCENTAGE / 100)
        
        # Validate that received quantity is not less than 97% of sent quantity
        if received_quantity < minimum_acceptable:
            shortfall = transfer.quantity - received_quantity
            shortfall_percentage = (shortfall / transfer.quantity) * 100
            
            return {
                'message': f'Received quantity is below acceptable threshold ({MINIMUM_THRESHOLD_PERCENTAGE}%)',
                'details': {
                    'sent_quantity': round(transfer.quantity, 2),
                    'received_quantity': round(received_quantity, 2),
                    'minimum_acceptable': round(minimum_acceptable, 2),
                    'shortfall': round(shortfall, 2),
                    'shortfall_percentage': round(shortfall_percentage, 2),
                    'threshold_percentage': MINIMUM_THRESHOLD_PERCENTAGE
                },
                'action_required': 'Please verify the physical goods received and ensure they match or exceed the minimum acceptable quantity.'
            }, 400

        try:
            # Calculate difference
            difference = transfer.quantity - received_quantity
            
            # Update transfer with received quantity and difference
            transfer.received_quantity = received_quantity
            transfer.difference = difference
            transfer.status = "Received"
            
            # ✅ Update shop stock with ACTUAL received quantity, not original quantity
            new_shop_stock = ShopStockV2(
                shop_id=transfer.shop_id,
                transferv2_id=transfer.transferv2_id,
                inventoryv2_id=transfer.inventoryV2_id,
                quantity=received_quantity,  # Use actual received quantity
                total_cost=transfer.unitCost * received_quantity,  # Recalculate based on received
                itemname=transfer.itemname,
                metric=transfer.metric,
                BatchNumber=transfer.BatchNumber,
                unitPrice=transfer.unitCost
            )

            db.session.add(new_shop_stock)
            db.session.commit()

            # Determine if there was any loss (even if within acceptable range)
            loss_percentage = (difference / transfer.quantity) * 100 if transfer.quantity > 0 else 0
            
            response_data = {
                'message': 'Transfer received successfully and stock added to shop.',
                'transfer_details': {
                    'transfer_id': transfer_id,
                    'item_name': transfer.itemname,
                    'sent_quantity': round(transfer.quantity, 2),
                    'received_quantity': round(received_quantity, 2),
                    'difference': round(difference, 2),
                    'loss_percentage': round(loss_percentage, 2)
                },
                'compliance': f'Received quantity meets {MINIMUM_THRESHOLD_PERCENTAGE}% threshold requirement',
                'threshold_applied': MINIMUM_THRESHOLD_PERCENTAGE
            }
            
            # Add warning if close to threshold (97-100%)
            if 0 < loss_percentage <= (100 - MINIMUM_THRESHOLD_PERCENTAGE):
                response_data['warning'] = 'Loss detected but within acceptable range'
            
            return response_data, 200

        except Exception as e:
            db.session.rollback()
            return {
                'message': 'Error receiving transfer',
                'error': str(e)
            }, 500

class DeclineTransfer(Resource):
    @jwt_required()
    def patch(self, transfer_id):
        transfer = TransfersV2.query.get(transfer_id)
        if not transfer:
            return {'message': 'Transfer not found'}, 404

        # 🚫 Ensure only "Not Received" transfers can be declined
        if transfer.status != "Not Received":
            return {'message': f'Transfer cannot be declined. Current status: {transfer.status}'}, 400

        try:
            # ✅ Return stock to inventory
            inventory_item = InventoryV2.query.get(transfer.inventoryV2_id)
            if not inventory_item:
                return {'message': 'Original inventory item not found'}, 404

            inventory_item.quantity += transfer.quantity

            # ✅ Update transfer status
            transfer.status = "Declined"

            db.session.commit()

            return {
                'message': 'Transfer declined successfully. Stock returned to inventory.',
                'transfer_id': transfer.transferv2_id,
                'restored_quantity': transfer.quantity
            }, 200

        except Exception as e:
            db.session.rollback()
            return {'message': 'Error declining transfer', 'error': str(e)}, 500


class PendingTransfers(Resource):
    @jwt_required()
    def get(self):
        try:
            # Get shop_id from query params
            shop_id = request.args.get("shop_id", type=int)
            if not shop_id:
                return {"message": "shop_id is required"}, 400

            # Filter only pending transfers for this shop
            pending = TransfersV2.query.filter_by(
                status="Not Received",
                shop_id=shop_id
            ).all()

            result = []
            for t in pending:
                result.append({
                    "transferv2_id": t.transferv2_id,
                    "shop_id": t.shop_id,
                    "inventoryV2_id": t.inventoryV2_id,
                    "itemname": t.itemname,
                    "quantity": t.quantity,
                    "metric": t.metric,
                    "unitCost": t.unitCost,
                    "amountPaid": t.amountPaid,
                    "total_cost": t.total_cost,
                    "BatchNumber": t.BatchNumber,
                    "created_at": t.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "status": t.status
                })

            return {"pending_transfers": result}, 200

        except Exception as e:
            return {"message": "Error fetching pending transfers", "error": str(e)}, 500

# class DeleteShopStockV2(Resource):
#     @jwt_required()
#     # @check_role('manager')
#     def delete(self, shop_stockV2_id):
#         current_user_id = get_jwt_identity()

#         shop_stock = ShopStockV2.query.get(shop_stockV2_id)
#         if not shop_stock:
#             return {'message': 'ShopStock record not found'}, 404

#         # 🔁 Use the correct attribute name based on your model
#         transfer = TransfersV2.query.get(shop_stock.transferv2_id)
#         if not transfer:
#             return {'message': 'Related Transfer record not found'}, 404

#         inventory_item = InventoryV2.query.get(shop_stock.inventoryv2_id)
#         if not inventory_item:
#             return {'message': 'Related Inventory item not found'}, 404

#         try:
#             # Restore quantity
#             inventory_item.quantity += shop_stock.quantity
#             print(f"Reverted inventory quantity for Inventory ID {inventory_item.inventoryV2_id}. New quantity: {inventory_item.quantity}")

#             db.session.delete(transfer)
#             db.session.delete(shop_stock)
#             db.session.commit()

#             return {
#                 'message': 'ShopStock and associated records deleted successfully',
#                 'details': {
#                     'shop_stockV2_id': int(shop_stockV2_id),
#                     'inventoryV2_id': int(inventory_item.inventoryV2_id),
#                     'transferV2_id': int(transfer.transferv2_id)
#                 }
#             }, 200

#         except Exception as e:
#             db.session.rollback()
#             return {'message': 'Error deleting ShopStock', 'error': str(e)}, 500

class DeleteShopStockV2(Resource):
    @jwt_required()
    def delete(self, stockv2_id):
        current_user_id = get_jwt_identity()
        
        try:
            # Get JSON data from request
            data = request.get_json()
            if not data:
                return {'message': 'Request body must be JSON'}, 400
                
            quantity_to_delete = data.get('quantity')
            if quantity_to_delete is None:
                return {'message': 'Quantity is required'}, 400
            
            try:
                quantity_to_delete = int(quantity_to_delete)
            except (ValueError, TypeError):
                return {'message': 'Quantity must be an integer'}, 400

            # Start a new session to avoid conflicts
            db.session.begin_nested()

            shop_stock = ShopStockV2.query.get(stockv2_id)
            if not shop_stock:
                db.session.rollback()
                return {'message': 'ShopStock record not found'}, 404

            # Validate the quantity to delete
            if quantity_to_delete <= 0:
                db.session.rollback()
                return {'message': 'Quantity to delete must be positive'}, 400
                
            if quantity_to_delete > shop_stock.quantity:
                db.session.rollback()
                return {
                    'message': f'Cannot delete more than available quantity ({shop_stock.quantity})',
                    'available_quantity': shop_stock.quantity
                }, 400

            # Check if transfer exists, but don't fail if it doesn't
            transfer = None
            if shop_stock.transferv2_id:
                transfer = TransfersV2.query.get(shop_stock.transferv2_id)
                if not transfer:
                    current_app.logger.warning(f"Transfer record {shop_stock.transferv2_id} not found for stock {stockv2_id}")

            # Check if inventory item exists
            inventory_item = None
            if shop_stock.inventoryv2_id:
                inventory_item = InventoryV2.query.get(shop_stock.inventoryv2_id)
                if not inventory_item:
                    current_app.logger.warning(f"Inventory record {shop_stock.inventoryv2_id} not found for stock {stockv2_id}")

            # If inventory item doesn't exist, we can't restore quantity to inventory
            # But we can still process the return/delete operation
            if not inventory_item:
                # Create a log entry or alternative handling for missing inventory
                current_app.logger.warning(f"Processing return without inventory restoration for stock {stockv2_id}")
                
                if quantity_to_delete < shop_stock.quantity:
                    # Partial deletion without inventory restoration
                    shop_stock.quantity -= quantity_to_delete
                    
                    return_record = ReturnsV2(
                        stockv2_id=shop_stock.stockv2_id,
                        inventoryv2_id=shop_stock.inventoryv2_id,  # Use the ID even if record doesn't exist
                        shop_id=shop_stock.shop_id,
                        quantity=quantity_to_delete,
                        returned_by=current_user_id,
                        return_date=datetime.utcnow(),
                        reason="Partial return - inventory item not available"
                    )
                    db.session.add(return_record)
                else:
                    # Full deletion without inventory restoration
                    return_record = ReturnsV2(
                        stockv2_id=shop_stock.stockv2_id,
                        inventoryv2_id=shop_stock.inventoryv2_id,  # Use the ID even if record doesn't exist
                        shop_id=shop_stock.shop_id,
                        quantity=shop_stock.quantity,
                        returned_by=current_user_id,
                        return_date=datetime.utcnow(),
                        reason="Full return - inventory item not available"
                    )
                    db.session.add(return_record)
                    
                    # Delete related return records first
                    ReturnsV2.query.filter_by(stockv2_id=shop_stock.stockv2_id).delete()
                    
                    # Only delete transfer if it exists and has no other dependencies
                    if transfer:
                        other_stocks = ShopStockV2.query.filter(
                            ShopStockV2.transferv2_id == transfer.transferv2_id,
                            ShopStockV2.stockv2_id != shop_stock.stockv2_id
                        ).count()
                        
                        if other_stocks == 0:
                            db.session.delete(transfer)
                    
                    db.session.delete(shop_stock)
            else:
                # Original logic with inventory restoration
                if quantity_to_delete < shop_stock.quantity:
                    shop_stock.quantity -= quantity_to_delete
                    inventory_item.quantity += quantity_to_delete
                    
                    return_record = ReturnsV2(
                        stockv2_id=shop_stock.stockv2_id,
                        inventoryv2_id=inventory_item.inventoryV2_id,
                        shop_id=shop_stock.shop_id,
                        quantity=quantity_to_delete,
                        returned_by=current_user_id,
                        return_date=datetime.utcnow(),
                        reason="Partial return to inventory"
                    )
                    db.session.add(return_record)
                else:
                    inventory_item.quantity += shop_stock.quantity
                    
                    return_record = ReturnsV2(
                        stockv2_id=shop_stock.stockv2_id,
                        inventoryv2_id=inventory_item.inventoryV2_id,
                        shop_id=shop_stock.shop_id,
                        quantity=shop_stock.quantity,
                        returned_by=current_user_id,
                        return_date=datetime.utcnow(),
                        reason="Full return to inventory"
                    )
                    db.session.add(return_record)
                    
                    ReturnsV2.query.filter_by(stockv2_id=shop_stock.stockv2_id).delete()
                    
                    if transfer:
                        other_stocks = ShopStockV2.query.filter(
                            ShopStockV2.transferv2_id == transfer.transferv2_id,
                            ShopStockV2.stockv2_id != shop_stock.stockv2_id
                        ).count()
                        
                        if other_stocks == 0:
                            db.session.delete(transfer)
                    
                    db.session.delete(shop_stock)

            db.session.commit()
            
            # Build response
            response_data = {
                'message': 'Return processed successfully',
                'details': {
                    'stockv2_id': int(stockv2_id),
                    'returned_quantity': quantity_to_delete,
                    'return_record_id': return_record.returnv2_id
                }
            }
            
            # Add optional details
            if transfer:
                response_data['details']['transferv2_id'] = int(transfer.transferv2_id)
            
            if inventory_item:
                response_data['details']['inventoryv2_id'] = int(inventory_item.inventoryV2_id)
                response_data['details']['inventory_restored'] = True
            else:
                response_data['details']['inventoryv2_id'] = shop_stock.inventoryv2_id
                response_data['details']['inventory_restored'] = False
                response_data['details']['note'] = 'Inventory item not found - quantity not restored to inventory'
            
            if quantity_to_delete < shop_stock.quantity:
                response_data['details']['remaining_quantity'] = shop_stock.quantity
            
            return response_data, 200

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f"Database error in DeleteShopStockV2: {str(e)}")
            return {
                'message': 'Database operation failed',
                'error': str(e),
                'type': 'database_error'
            }, 500
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Unexpected error in DeleteShopStockV2: {str(e)}")
            return {
                'message': 'An unexpected error occurred',
                'error': str(e),
                'type': 'unexpected_error'
            }, 500


class GetTransferV2(Resource):
    @jwt_required()
    def get(self):
        try:
            # Pagination - use 'per_page' to match frontend
            page = int(request.args.get('page', 1))
            per_page = int(request.args.get('per_page', request.args.get('limit', 50)))
            
            # Filters
            search_query = request.args.get('searchQuery', '')
            status_filter = request.args.get('status', '')
            shop_filter = request.args.get('shop_id', '')
            item_filter = request.args.get('itemFilter', '')
            
            # Date range filters
            start_date = request.args.get('startDate', '')
            end_date = request.args.get('endDate', '')
            
            # Sort parameters
            sort_by = request.args.get('sort_by', 'created_at')
            sort_order = request.args.get('sort_order', 'desc')

            # Valid sort fields - make sure they match frontend
            valid_sort_fields = ['created_at', 'username', 'shop_name', 'itemname', 'total_cost', 'quantity']
            if sort_by not in valid_sort_fields:
                sort_by = 'created_at'
            if sort_order not in ['asc', 'desc']:
                sort_order = 'desc'

            # Base query with joins
            transfers_query = TransfersV2.query.join(Users, TransfersV2.user_id == Users.users_id)\
                                             .join(Shops, TransfersV2.shop_id == Shops.shops_id)

            # Apply filters
            if search_query:
                transfers_query = transfers_query.filter(
                    or_(
                        TransfersV2.itemname.ilike(f"%{search_query}%"),
                        TransfersV2.BatchNumber.ilike(f"%{search_query}%"),
                        Users.username.ilike(f"%{search_query}%"),
                        Shops.shopname.ilike(f"%{search_query}%")
                    )
                )

            # Apply date range filter
            if start_date and end_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    # Add one day to include the end date fully
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    
                    transfers_query = transfers_query.filter(
                        TransfersV2.created_at.between(start_date_obj, end_date_obj)
                    )
                except ValueError:
                    return {"error": "Invalid date format. Use YYYY-MM-DD."}, 400
            elif start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    transfers_query = transfers_query.filter(
                        TransfersV2.created_at >= start_date_obj
                    )
                except ValueError:
                    return {"error": "Invalid date format. Use YYYY-MM-DD."}, 400
            elif end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    transfers_query = transfers_query.filter(
                        TransfersV2.created_at <= end_date_obj
                    )
                except ValueError:
                    return {"error": "Invalid date format. Use YYYY-MM-DD."}, 400

            if status_filter:
                transfers_query = transfers_query.filter(TransfersV2.status == status_filter)

            if shop_filter:
                try:
                    transfers_query = transfers_query.filter(TransfersV2.shop_id == int(shop_filter))
                except ValueError:
                    return {"error": "Invalid shop ID format."}, 400

            if item_filter:
                transfers_query = transfers_query.filter(TransfersV2.itemname.ilike(f"%{item_filter}%"))

            # CALCULATE TOTALS FOR ENTIRE DATE RANGE/FILTERS
            # Create a copy of the query for totals calculation
            totals_query = transfers_query
            
            # Calculate total cost and total amount paid for all matching records
            from sqlalchemy import func
            
            totals = totals_query.with_entities(
                func.sum(TransfersV2.total_cost).label('total_cost_sum'),
                func.sum(TransfersV2.amountPaid).label('amount_paid_sum'),
                func.count(TransfersV2.transferv2_id).label('total_transfers_count')
            ).first()
            
            total_cost_sum = totals.total_cost_sum or 0.0
            total_amount_paid_sum = totals.amount_paid_sum or 0.0
            total_transfers_count = totals.total_transfers_count or 0

            # Handle sorting
            if sort_by == 'username':
                order_field = Users.username
            elif sort_by == 'shop_name':
                order_field = Shops.shopname
            elif sort_by == 'itemname':
                order_field = TransfersV2.itemname
            elif sort_by == 'total_cost':
                order_field = TransfersV2.total_cost
            elif sort_by == 'quantity':
                order_field = TransfersV2.quantity
            else:
                order_field = TransfersV2.created_at

            # Sort direction
            if sort_order == 'desc':
                transfers_query = transfers_query.order_by(order_field.desc())
            else:
                transfers_query = transfers_query.order_by(order_field.asc())

            # ALWAYS use pagination - never return all records
            # Count total items before pagination
            total_transfers = transfers_query.count()
            total_pages = max(1, (total_transfers + per_page - 1) // per_page)
            
            # Apply pagination
            offset = (page - 1) * per_page
            transfers_list = transfers_query.offset(offset).limit(per_page).all()

            # Construct response data
            all_transfers = []
            for transfer in transfers_list:
                # Already joined, so we can access directly
                username = transfer.users.username if transfer.users else "Unknown User"
                shopname = transfer.shop.shopname if transfer.shop else "Unknown Shop"
            
                all_transfers.append({
                    "transferv2_id": transfer.transferv2_id,
                    "shop_id": transfer.shop_id,
                    "inventoryV2_id": transfer.inventoryV2_id,      
                    "quantity": float(transfer.quantity) if transfer.quantity else 0.0, 
                    "received_quantity": float(transfer.received_quantity) if transfer.received_quantity else 0.0,
                    "difference": float(transfer.difference) if transfer.difference else 0.0,            
                    "metric": transfer.metric or "",
                    "total_cost": float(transfer.total_cost) if transfer.total_cost else 0.0,
                    "BatchNumber": transfer.BatchNumber or "",
                    "user_id": transfer.user_id,
                    "username": username,
                    "shop_name": shopname,
                    "itemname": transfer.itemname or "",
                    "status": transfer.status or "",
                    "amountPaid": float(transfer.amountPaid) if transfer.amountPaid else 0.0,
                    "unitCost": float(transfer.unitCost) if transfer.unitCost else 0.0,
                    "created_at": transfer.created_at.strftime('%Y-%m-%d %H:%M:%S') if transfer.created_at else None,
                })

            return {
                "status": "success",
                "data": all_transfers,
                "total_transfers": total_transfers,
                "total_pages": total_pages,
                "current_page": page,
                "per_page": per_page,
                "has_next": page < total_pages,
                "has_prev": page > 1,
                "count": len(all_transfers),
                # NEW: Add summary data for the entire filtered range
                "summary": {
                    "total_cost": float(total_cost_sum),
                    "total_amount_paid": float(total_amount_paid_sum),
                    "balance": float(total_cost_sum - total_amount_paid_sum),
                    "total_transfers_count": total_transfers_count
                },
                "message": "Transfers retrieved successfully"
            }, 200

        except SQLAlchemyError as e:
            current_app.logger.error(f"Database error: {str(e)}")
            return {"error": "Database operation failed."}, 500
        except ValueError as e:
            current_app.logger.error(f"Value error: {str(e)}")
            return {"error": str(e)}, 400
        except Exception as e:
            current_app.logger.error(f"Unexpected error: {str(e)}")
            return {"error": "An unexpected error occurred."}, 500


class GetTransferByIdV2(Resource):
    @jwt_required()
    @check_role('manager')
    def get(self, transferV2_id):
        transfer = TransfersV2.query.filter_by(transferV2_id=transferV2_id).first()
        
        if not transfer:
            return make_response(jsonify({"message": "Transfer not found"})), 404
        
        user = Users.query.filter_by(users_id=transfer.user_id).first()
        shop = Shops.query.filter_by(shops_id=transfer.shop_id).first()
        
        username = user.username if user else "Unknown User"
        shopname = shop.shopname if shop else "Unknown Shop"
    
        transfer_data = {
            "transferV2_id": transfer.transferV2_id,
            "shop_id": transfer.shop_id,
            "inventoryV2_id": transfer.inventoryV2_id,      
            "quantity": transfer.quantity,             
            "metric": transfer.metric,
            "totalCost": transfer.total_cost,
            "batchnumber": transfer.BatchNumber,
            "user_id": transfer.user_id,
            "username": username,
            "shop_name": shopname,
            "itemname": transfer.itemname,
            "amountPaid": transfer.amountPaid,
            "unitCost": transfer.unitCost,
            "created_at": transfer.created_at,
        }

        return make_response(jsonify(transfer_data), 200)


class UpdateTransferV2(Resource):
    @jwt_required()
    @check_role('manager')
    def put(self, transferV2_id):
        data = request.get_json()
        transfer = TransfersV2.query.filter_by(transferV2_id=transferV2_id).first()

        if not transfer:
            return make_response(jsonify({"message": "Transfer not found"}), 404)

        transfer.shop_id = data.get("shop_id", transfer.shop_id)
        transfer.inventoryV2_id = data.get("inventoryV2_id", transfer.inventoryV2_id)
        transfer.quantity = data.get("quantity", transfer.quantity)
        transfer.metric = data.get("metric", transfer.metric)
        transfer.total_cost = data.get("totalCost", transfer.total_cost)
        transfer.BatchNumber = data.get("batchnumber", transfer.BatchNumber)
        transfer.user_id = data.get("user_id", transfer.user_id)
        transfer.itemname = data.get("itemname", transfer.itemname)
        transfer.amountPaid = data.get("amountPaid", transfer.amountPaid)
        transfer.unitCost = data.get("unitCost", transfer.unitCost)

        if 'date' in data:
            try:
                transfer.created_at = datetime.strptime(data['date'], '%Y-%m-%d')
            except ValueError:
                return make_response(jsonify({"message": "Invalid date format. Use YYYY-MM-DD."}), 400)

        db.session.commit()

        return make_response(jsonify({"message": "Transfer updated successfully"}), 200)


class AddInventoryV2(Resource):
    @jwt_required()
    def post(self):
        data = request.get_json()
        current_user_id = get_jwt_identity()

        required_fields = [
            'itemname', 'quantity', 'metric', 'unitCost', 'amountPaid', 'unitPrice',
            'Suppliername', 'phone_number', 'Supplier_location', 'created_at', 'payment_status'
        ]
        if not all(field in data for field in required_fields):
            return {'message': 'Missing required fields'}, 400

        # Extract fields
        itemname = data.get('itemname')
        quantity = float(data.get('quantity'))
        metric = data.get('metric')
        unitCost = float(data.get('unitCost'))
        amountPaid = float(data.get('amountPaid'))
        unitPrice = float(data.get('unitPrice'))
        Suppliername = data.get('Suppliername')
        Supplier_location = data.get('Supplier_location')
        source = data.get('source')
        paymentRef = data.get('paymentRef')
        note = data.get('note', '')
        created_at_str = data.get('created_at')
        payment_status = data.get('payment_status', 'paid').lower()
        email = data.get('email')
        phone_number = data.get('phone_number')

        # Validate payment status
        valid_statuses = ['paid', 'unpaid', 'partially_paid']
        if payment_status not in valid_statuses:
            return {'message': f'Invalid payment status. Must be one of: {valid_statuses}'}, 400

        try:
            created_at = datetime.strptime(created_at_str, "%Y-%m-%d")
        except ValueError:
            return {'message': 'Invalid date format. Please use YYYY-MM-DD for created_at.'}, 400

        totalCost = unitCost * quantity
        balance = totalCost - amountPaid
        
        # Validate amount paid based on payment status
        if payment_status == 'paid' and amountPaid < totalCost:
            return {'message': 'Payment status cannot be PAID when amount paid is less than total cost'}, 400
        elif payment_status == 'unpaid' and amountPaid > 0:
            return {'message': 'Payment status cannot be UNPAID when amount paid is greater than 0'}, 400
        elif payment_status == 'partially_paid' and (amountPaid <= 0 or amountPaid >= totalCost):
            return {'message': 'PARTIALLY_PAID status requires amount paid to be between 0 and total cost'}, 400
        
        # Determine credit amount based on payment status
        credit_amount = 0
        if payment_status in ['unpaid', 'partially_paid']:
            credit_amount = balance  # Credit amount equals the balance

        last_inventory = InventoryV2.query.order_by(InventoryV2.inventoryV2_id.desc()).first()
        next_batch_number = 1 if not last_inventory else last_inventory.inventoryV2_id + 1
        batch_code = InventoryV2.generate_batch_code(
            Suppliername, Supplier_location, itemname, created_at, next_batch_number
        )
        debit_account_value = unitPrice * quantity

        if not source or len(source.strip()) == 0:
            source = "Unknown"

        try:
            # Step 1: Check or create supplier
            supplier = Suppliers.query.filter_by(
                supplier_name=Suppliername,
                supplier_location=Supplier_location
            ).first()

            if not supplier:
                supplier = Suppliers(
                    supplier_name=Suppliername,
                    supplier_location=Supplier_location,
                    total_amount_received=amountPaid,
                    credit_amount=credit_amount,  # Set initial credit amount
                    email=email,
                    phone_number=phone_number,
                    items_sold=json.dumps([itemname])
                )
                db.session.add(supplier)
                db.session.flush()
            else:
                supplier.total_amount_received += amountPaid
                # Update supplier credit amount
                if payment_status in ['unpaid', 'partially_paid']:
                    supplier.credit_amount = (supplier.credit_amount or 0) + credit_amount
                
                # Update items sold
                if supplier.items_sold:
                    try:
                        items_list = json.loads(supplier.items_sold)
                    except:
                        items_list = supplier.items_sold if isinstance(supplier.items_sold, list) else []
                else:
                    items_list = []
                    
                if itemname not in items_list:
                    items_list.append(itemname)
                supplier.items_sold = json.dumps(items_list)
                db.session.flush()

            # Step 2: Add inventory record
            new_inventory = InventoryV2(
                itemname=itemname,
                initial_quantity=quantity,
                quantity=quantity,
                metric=metric,
                unitCost=unitCost,
                totalCost=totalCost,
                amountPaid=amountPaid,
                unitPrice=unitPrice,
                BatchNumber=batch_code,
                user_id=current_user_id,
                Suppliername=Suppliername,
                Supplier_location=Supplier_location,
                ballance=balance,
                note=note,
                created_at=created_at,
                source=source,
                Trasnaction_type_credit=amountPaid,
                Transcation_type_debit=debit_account_value,
                paymentRef=paymentRef,
                payment_status=payment_status,  # Using payment_status field
                credits_amount=credit_amount  # Using credits_amount field (note the 's' in credits_amount)
            )
            db.session.add(new_inventory)
            db.session.flush()  # Get the inventory ID

            # Step 3: Add supplier history
            supplier_history = SupplierHistory(
                supplier_id=supplier.supplier_id,
                amount_received=amountPaid,
                transaction_date=datetime.utcnow(),
                item_bought=itemname,
                payment_status=payment_status,
                credit_amount=credit_amount,
                inventory_id=new_inventory.inventoryV2_id  # Link to inventory
            )
            db.session.add(supplier_history)

            # Step 4: Handle bank transaction (only for paid amounts)
            if amountPaid > 0 and source not in ["Unknown", "External funding"]:
                # Import your bank models
                
                account = BankAccount.query.filter_by(Account_name=source).first()
                if not account:
                    return {'message': f'Bank account with name "{source}" not found'}, 404

                if account.Account_Balance < amountPaid:
                    return {'message': f'Insufficient balance in account "{source}"'}, 400

                account.Account_Balance -= amountPaid
                db.session.add(account)

                transaction = BankingTransaction(
                    account_id=account.id,
                    Transaction_type_debit=amountPaid,
                    Transaction_type_credit=None,
                    reference=f"Inventory Purchase: {batch_code}"
                )
                db.session.add(transaction)

            db.session.commit()
            
            # Step 5: Try posting journal entry (if you have this service)
            try:
                from Server.Views.Services.journal_service import PurchaseJournalService
                journal_result = PurchaseJournalService.post_purchase_journal(new_inventory)
                db.session.commit()
            except ImportError:
                journal_result = {"message": "Journal service not available"}
            except Exception as e:
                journal_result = {"message": f"Journal posting failed: {str(e)}"}

            return {
                'message': 'Inventory added successfully',
                'BatchNumber': batch_code,
                'SupplierID': supplier.supplier_id,
                'payment_status': payment_status,
                'credit_amount': credit_amount,
                'outstanding_balance': balance,
                'journal_entry': journal_result
            }, 201

        except Exception as e:
            db.session.rollback()
            return {'message': 'Error adding inventory', 'error': str(e)}, 500

class AllInventoryV2(Resource):
    @jwt_required()
   
    def get(self):
        inventories = InventoryV2.query.order_by(InventoryV2.created_at.desc()).all()

        all_inventory = [{
            "inventoryV2_id": inventory.inventoryV2_id,
            "itemname": inventory.itemname,
            "initial_quantity": inventory.initial_quantity,
            "remaining_quantity": inventory.quantity,
            "metric": inventory.metric,
            "totalCost": inventory.totalCost,
            "unitCost": inventory.unitCost,
            "batchnumber": inventory.BatchNumber,
            "amountPaid": inventory.amountPaid,
            "balance": inventory.ballance,
            "note": inventory.note,
            "created_at": inventory.created_at,
            "unitPrice": inventory.unitPrice,
            "source": inventory.source,
            "paymentRef": inventory.paymentRef
        } for inventory in inventories]

        return make_response(jsonify(all_inventory), 200)


class GetAllInventoryV2(Resource):
    @jwt_required()
    def get(self):
        try:
            # Pagination
            page = int(request.args.get('page', 1))
            per_page = int(request.args.get('per_page', request.args.get('limit', 50)))
            
            # Existing filters
            search_query = request.args.get('searchQuery', '')
            item_name_filter = request.args.get('itemFilter', '')
            source_filter = request.args.get('sourceFilter', '')
            metric_filter = request.args.get('metricFilter', '')
            stock_range_filter = request.args.get('stockRangeFilter', '')
            
            # Date range filters
            start_date = request.args.get('startDate', '')
            end_date = request.args.get('endDate', '')
            
            # New filters
            supplier_filter = request.args.get('supplier', '')
            transaction_code_filter = request.args.get('transactionCode', '')
            filter_item_name = request.args.get('filterItemName', '')
            
            # Sort parameters
            sort_by = request.args.get('sort_by', 'created_at')
            sort_order = request.args.get('sort_order', 'desc')

            # Valid sort fields
            valid_sort_fields = ['created_at', 'itemname', 'remaining_quantity', 'initial_quantity', 
                               'unitPrice', 'totalCost', 'batchnumber', 'source', 'supplier']
            if sort_by not in valid_sort_fields:
                sort_by = 'created_at'
            if sort_order not in ['asc', 'desc']:
                sort_order = 'desc'

            # Base query
            inventory_query = InventoryV2.query

            # Apply search filter
            if search_query:
                inventory_query = inventory_query.filter(
                    or_(
                        InventoryV2.itemname.ilike(f"%{search_query}%"),
                        InventoryV2.BatchNumber.ilike(f"%{search_query}%"),
                        InventoryV2.note.ilike(f"%{search_query}%"),
                        InventoryV2.source.ilike(f"%{search_query}%"),
                        InventoryV2.Suppliername.ilike(f"%{search_query}%"),
                        InventoryV2.paymentRef.ilike(f"%{search_query}%")  # Added to search
                    )
                )

            # Apply item name filter (original filter)
            if item_name_filter:
                inventory_query = inventory_query.filter(InventoryV2.itemname == item_name_filter)

            # Apply filter item name (new filter from Filter dropdown)
            if filter_item_name:
                inventory_query = inventory_query.filter(InventoryV2.itemname.ilike(f"%{filter_item_name}%"))

            # Apply source filter
            if source_filter:
                inventory_query = inventory_query.filter(InventoryV2.source == source_filter)

            # Apply metric filter
            if metric_filter:
                inventory_query = inventory_query.filter(InventoryV2.metric == metric_filter)

            # Apply supplier filter - using Suppliername field
            if supplier_filter:
                inventory_query = inventory_query.filter(
                    InventoryV2.Suppliername.ilike(f"%{supplier_filter}%")
                )

            # Apply transaction code filter (search in paymentRef) - UPDATED
            if transaction_code_filter:
                inventory_query = inventory_query.filter(
                    InventoryV2.paymentRef.ilike(f"%{transaction_code_filter}%")
                )

            # Apply date range filter
            if start_date and end_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    # Add one day to include the end date fully
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    
                    inventory_query = inventory_query.filter(
                        InventoryV2.created_at.between(start_date_obj, end_date_obj)
                    )
                except ValueError:
                    return {"error": "Invalid date format. Use YYYY-MM-DD."}, 400
            elif start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    inventory_query = inventory_query.filter(
                        InventoryV2.created_at >= start_date_obj
                    )
                except ValueError:
                    return {"error": "Invalid date format. Use YYYY-MM-DD."}, 400
            elif end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                    inventory_query = inventory_query.filter(
                        InventoryV2.created_at <= end_date_obj
                    )
                except ValueError:
                    return {"error": "Invalid date format. Use YYYY-MM-DD."}, 400

            # Apply stock range filter
            if stock_range_filter:
                if stock_range_filter == "out-of-stock":
                    inventory_query = inventory_query.filter(InventoryV2.quantity == 0)
                elif stock_range_filter == "low-stock":
                    inventory_query = inventory_query.filter(
                        and_(
                            InventoryV2.quantity > 0,
                            InventoryV2.quantity <= InventoryV2.initial_quantity * 0.2
                        )
                    )
                elif stock_range_filter == "medium-stock":
                    inventory_query = inventory_query.filter(
                        and_(
                            InventoryV2.quantity > InventoryV2.initial_quantity * 0.2,
                            InventoryV2.quantity <= InventoryV2.initial_quantity * 0.5
                        )
                    )
                elif stock_range_filter == "high-stock":
                    inventory_query = inventory_query.filter(
                        InventoryV2.quantity > InventoryV2.initial_quantity * 0.5
                    )

            # Handle sorting - updated for Suppliername
            if sort_by == 'itemname':
                order_field = InventoryV2.itemname
            elif sort_by == 'remaining_quantity':
                order_field = InventoryV2.quantity
            elif sort_by == 'initial_quantity':
                order_field = InventoryV2.initial_quantity
            elif sort_by == 'unitPrice':
                order_field = InventoryV2.unitPrice
            elif sort_by == 'totalCost':
                order_field = InventoryV2.totalCost
            elif sort_by == 'batchnumber':
                order_field = InventoryV2.BatchNumber
            elif sort_by == 'source':
                order_field = InventoryV2.source
            elif sort_by == 'supplier':
                order_field = InventoryV2.Suppliername
            else:
                order_field = InventoryV2.created_at

            # Sort direction
            if sort_order == 'desc':
                inventory_query = inventory_query.order_by(order_field.desc())
            else:
                inventory_query = inventory_query.order_by(order_field.asc())

            # Count total items before pagination
            total_inventory = inventory_query.count()
            total_pages = max(1, (total_inventory + per_page - 1) // per_page)
            
            # Apply pagination
            offset = (page - 1) * per_page
            inventory_list = inventory_query.offset(offset).limit(per_page).all()

            # Calculate summary statistics for the filtered data
            all_items_summary = []
            total_stock_value = 0
            total_cost_value = 0
            total_stock_quantity = 0
            low_stock_count = 0
            out_of_stock_count = 0
            
            for inv in inventory_list:
                stock_value = inv.quantity * inv.unitPrice if inv.quantity and inv.unitPrice else 0
                total_stock_value += stock_value
                total_cost_value += inv.totalCost if inv.totalCost else 0
                total_stock_quantity += inv.quantity if inv.quantity else 0
                
                # Calculate status
                if inv.quantity <= 0:
                    out_of_stock_count += 1
                elif inv.initial_quantity > 0 and inv.quantity <= inv.initial_quantity * 0.2:
                    low_stock_count += 1

            # Construct response data
            all_inventory = []
            for inventory in inventory_list:
                # Calculate balance if not already calculated
                balance = inventory.ballance if hasattr(inventory, 'ballance') else 0
                
                all_inventory.append({
                    "inventoryV2_id": inventory.inventoryV2_id,
                    "itemname": inventory.itemname,
                    "initial_quantity": float(inventory.initial_quantity) if inventory.initial_quantity else 0.0,
                    "remaining_quantity": float(inventory.quantity) if inventory.quantity else 0.0,
                    "metric": inventory.metric or "",
                    "totalCost": float(inventory.totalCost) if inventory.totalCost else 0.0,
                    "unitCost": float(inventory.unitCost) if inventory.unitCost else 0.0,
                    "batchnumber": inventory.BatchNumber or "",
                    "amountPaid": float(inventory.amountPaid) if inventory.amountPaid else 0.0,
                    "balance": float(balance) if balance else 0.0,
                    "note": inventory.note or "",
                    "created_at": inventory.created_at.strftime('%Y-%m-%d %H:%M:%S') if inventory.created_at else None,
                    "unitPrice": float(inventory.unitPrice) if inventory.unitPrice else 0.0,
                    "source": inventory.source or "",
                    "paymentRef": inventory.paymentRef or "",
                    "supplier": inventory.Suppliername if hasattr(inventory, 'Suppliername') else "",
                    "expiry_date": inventory.expiry_date.strftime('%Y-%m-%d') if hasattr(inventory, 'expiry_date') and inventory.expiry_date else None,
                    "location": inventory.location if hasattr(inventory, 'location') else ""
                })

            return {
                "status": "success",
                "data": all_inventory,
                "total_inventory": total_inventory,
                "total_pages": total_pages,
                "current_page": page,
                "per_page": per_page,
                "has_next": page < total_pages,
                "has_prev": page > 1,
                "count": len(all_inventory),
                "summary": {
                    "totalItems": total_inventory,
                    "totalValue": total_stock_value,
                    "totalCost": total_cost_value,
                    "totalStock": total_stock_quantity,
                    "lowStockItems": low_stock_count,
                    "outOfStockItems": out_of_stock_count
                },
                "message": "Inventory retrieved successfully"
            }, 200

        except SQLAlchemyError as e:
            current_app.logger.error(f"Database error: {str(e)}")
            return {"error": "Database operation failed."}, 500
        except ValueError as e:
            current_app.logger.error(f"Value error: {str(e)}")
            return {"error": str(e)}, 400
        except Exception as e:
            current_app.logger.error(f"Unexpected error: {str(e)}")
            return {"error": "An unexpected error occurred."}, 500
        

class InventoryResourceByIdV2(Resource):
    @jwt_required()
    # @check_role('manager')
    def get(self, inventoryV2_id):
        inventory = InventoryV2.query.get(inventoryV2_id)
   
        if inventory:
            return {
                "inventoryV2_id": inventory.inventoryV2_id,
                "itemname": inventory.itemname,
                "initial_quantity": inventory.initial_quantity,
                "quantity": inventory.quantity,
                "metric": inventory.metric,
                "totalCost": inventory.totalCost,
                "unitCost": inventory.unitCost,
                "batchnumber": inventory.BatchNumber,
                "amountPaid": inventory.amountPaid,
                "balance": inventory.ballance,
                "note": inventory.note,
                "created_at": inventory.created_at.isoformat() if inventory.created_at else None,
                "unitPrice": inventory.unitPrice,
                "source": inventory.source,
                "paymentRef": inventory.paymentRef,
                "Suppliername": inventory.Suppliername,
                "Supplier_location": inventory.Supplier_location
            }, 200
        else:
            return {"error": "Inventory not found"}, 404
        
    @jwt_required()
    def delete(self, inventoryV2_id):
        inventory = InventoryV2.query.get(inventoryV2_id)

        if not inventory:
            return {"error": "Inventory not found"}, 404

        try:
            # Delete purchase ledger entries first (FK: inventory_id)
            try:
                purchase_ledger_entries = PurchaseLedgerInventory.query.filter_by(
                    inventory_id=inventoryV2_id
                ).all()
                for entry in purchase_ledger_entries:
                    db.session.delete(entry)
            except Exception as e:
                return {
                    "message": "Failed while deleting purchase ledger records",
                    "error": str(e),
                    "hint": "Check PurchaseLedgerInventory model foreign key. Should be 'inventory_id'."
                }, 500

            # Get all transfers to delete their distribution ledger entries
            transfers = TransfersV2.query.filter_by(inventoryV2_id=inventoryV2_id).all()
            
            # Delete distribution ledger entries for each transfer
            for transfer in transfers:
                try:
                    distribution_entries = DistributionLedger.query.filter_by(
                        transfer_id=transfer.transferv2_id
                    ).all()
                    for entry in distribution_entries:
                        db.session.delete(entry)
                except Exception as e:
                    return {
                        "message": f"Failed while deleting distribution ledger records for transfer {transfer.transferv2_id}",
                        "error": str(e)
                    }, 500

            # Delete transfer records (FK: inventoryV2_id)
            try:
                for transfer in transfers:
                    db.session.delete(transfer)
            except Exception as e:
                return {
                    "message": "Failed while deleting transfer records",
                    "error": str(e),
                    "hint": "Check TransfersV2 model foreign key. Should be 'inventoryV2_id'."
                }, 500

            # Delete shop stock records (FK: inventoryv2_id)
            try:
                shop_stocks = ShopStockV2.query.filter_by(inventoryv2_id=inventoryV2_id).all()
                for stock in shop_stocks:
                    db.session.delete(stock)
            except Exception as e:
                return {
                    "message": "Failed while deleting shop stock records",
                    "error": str(e),
                    "hint": "Check ShopStockV2 model foreign key. Should be 'inventoryv2_id'."
                }, 500

            # Delete inventory itself
            try:
                db.session.delete(inventory)
            except Exception as e:
                return {
                    "message": "Failed while deleting inventory record",
                    "error": str(e)
                }, 500

            # Commit the transaction
            db.session.commit()

            return {"message": "Inventory and all related records (including ledger entries) deleted successfully"}, 200

        except Exception as e:
            db.session.rollback()
            return {
                "message": "General error while deleting inventory",
                "error": str(e)
            }, 500

    @jwt_required()
    def put(self, inventoryV2_id):
        data = request.get_json()
        inventory = InventoryV2.query.get(inventoryV2_id)
        if not inventory:
            return {'message': 'Inventory not found'}, 404

        try:
            # Store old values for comparison
            old_itemname = inventory.itemname
            old_initial_quantity = inventory.initial_quantity
            old_unitCost = inventory.unitCost
            old_unitPrice = inventory.unitPrice
            old_totalCost = inventory.totalCost
            old_amountPaid = inventory.amountPaid
            old_ballance = inventory.ballance  # Fixed: use ballance (double 'l')
            old_paymentRef = inventory.paymentRef
            old_Suppliername = inventory.Suppliername
            old_Supplier_location = inventory.Supplier_location
            old_note = inventory.note
            old_created_at = inventory.created_at

            # Get new values from request
            itemname = data.get('itemname', inventory.itemname)
            initial_quantity = int(data.get('initial_quantity', inventory.initial_quantity))
            unitCost = float(data.get('unitCost', inventory.unitCost))
            unitPrice = float(data.get('unitPrice', inventory.unitPrice))
            totalCost = unitCost * initial_quantity
            amountPaid = float(data.get('amountPaid', inventory.amountPaid))
            ballance = totalCost - amountPaid  # Fixed: calculate ballance
            paymentRef = data.get('paymentRef', inventory.paymentRef)
            Suppliername = data.get('Suppliername', inventory.Suppliername)
            Supplier_location = data.get('Supplier_location', inventory.Supplier_location)
            note = data.get('note', inventory.note)

            # Handle date
            created_at_str = data.get('created_at', None)
            if created_at_str:
                try:
                    created_at = datetime.strptime(created_at_str, '%Y-%m-%d')
                except ValueError:
                    return {'message': 'Invalid date format for created_at, expected YYYY-MM-DD'}, 400
            else:
                created_at = inventory.created_at

            # Update inventory
            inventory.itemname = itemname
            inventory.initial_quantity = initial_quantity
            inventory.unitCost = unitCost
            inventory.unitPrice = unitPrice
            inventory.totalCost = totalCost
            inventory.amountPaid = amountPaid
            inventory.ballance = ballance  # Fixed: update ballance (double 'l')
            inventory.paymentRef = paymentRef
            inventory.Suppliername = Suppliername
            inventory.Supplier_location = Supplier_location
            inventory.note = note
            inventory.created_at = created_at

            # Update purchase ledger entries
            purchase_ledger_entries = PurchaseLedgerInventory.query.filter_by(
                inventory_id=inventoryV2_id
            ).all()
            
            for entry in purchase_ledger_entries:
                # Update amount if totalCost changed
                if totalCost != old_totalCost:
                    entry.amount = totalCost
                
                # Update date if created_at changed
                if created_at != old_created_at:
                    entry.created_at = created_at
                
                # Update description if itemname changed
                if itemname != old_itemname:
                    entry.description = f"Purchase of {itemname} (Batch: {inventory.BatchNumber})"

            # Get all transfers to update their distribution ledger entries
            transfers = TransfersV2.query.filter_by(inventoryV2_id=inventoryV2_id).all()
            
            for transfer in transfers:
                # Update transfer details
                transfer.itemname = itemname
                transfer.unitCost = unitCost
                transfer.amountPaid = amountPaid
                transfer.paymentRef = paymentRef

                # Update distribution ledger entries for this transfer
                distribution_entries = DistributionLedger.query.filter_by(
                    transfer_id=transfer.transferv2_id
                ).all()
                
                for entry in distribution_entries:
                    # Update amount based on transfer quantity and unit cost
                    if unitCost != old_unitCost or transfer.quantity != old_initial_quantity:
                        # Calculate new amount based on transferred quantity
                        transferred_quantity = transfer.quantity
                        entry.amount = transferred_quantity * unitCost
                    
                    # Update date if created_at changed
                    if created_at != old_created_at:
                        entry.created_at = created_at
                    
                    # Update description if needed
                    if itemname != old_itemname:
                        entry.description = f"Distribution of {itemname} to {transfer.shop.shopname if transfer.shop else 'shop'}"

            # Update shop stock records
            shop_stocks = ShopStockV2.query.filter_by(inventoryv2_id=inventoryV2_id).all()
            for stock in shop_stocks:
                stock.itemname = itemname
                stock.unitPrice = unitPrice
                
                # Update selling price if unitPrice changed
                if unitPrice != old_unitPrice:
                    stock.unitPrice = unitPrice

            db.session.commit()
            
            return {
                'message': 'Inventory and all related records (including ledger entries) updated successfully',
                'updated_fields': {
                    'itemname': itemname != old_itemname,
                    'quantity': initial_quantity != old_initial_quantity,
                    'unitCost': unitCost != old_unitCost,
                    'unitPrice': unitPrice != old_unitPrice,
                    'totalCost': totalCost != old_totalCost,
                    'amountPaid': amountPaid != old_amountPaid,
                    'ballance': ballance != old_ballance,  # Fixed: use ballance
                    'paymentRef': paymentRef != old_paymentRef,
                    'date': created_at != old_created_at
                }
            }, 200

        except ValueError as e:
            db.session.rollback()
            return {'message': 'Invalid data type', 'error': str(e)}, 400
        except Exception as e:
            db.session.rollback()
            return {'message': 'Error updating inventory', 'error': str(e)}, 500

class StockDeletionResourceV2(Resource):     
    @jwt_required()
    @check_role('manager')
    def delete(self, stockV2_id):
        stock = ShopStockV2.query.get(stockV2_id)

        if not stock:
            return {"error": "Stock not found"}, 404

        try:
            if stock.inventoryV2_id == 0:
                related_transfers = TransfersV2.query.filter_by(shop_id=stock.shop_id, itemname=stock.itemname).all()
            else:
                related_transfers = TransfersV2.query.filter_by(stockV2_id=stockV2_id).all()

            if related_transfers:
                for transfer in related_transfers:
                    db.session.delete(transfer)

            if stock.inventoryV2_id != 0:
                inventory = InventoryV2.query.get(stock.inventoryV2_id)
                if inventory:
                    inventory.quantity += stock.quantity

            db.session.delete(stock)
            db.session.commit()

            return make_response(jsonify({"message": "Stock deleted successfully"}), 200)

        except Exception as e:
            db.session.rollback()
            error_message = str(e)
            current_app.logger.error(f"Error occurred: {error_message}")
            return jsonify({'error': 'Error deleting stock', 'details': error_message}), 500


class ManualTransferV2(Resource):
    @jwt_required()
    @check_role('manager')
    def post(self):
        data = request.get_json()
        current_user_id = get_jwt_identity()

        MANUAL_TRANSFER_SHOP_ID = 12

        required_fields = ['itemname', 'quantity', 'metric', 'unitCost', 'unitPrice', 'amountPaid']
        if not all(field in data for field in required_fields):
            return {'message': 'Missing required fields'}, 400

        try:
            itemname = data['itemname']
            quantity = float(data['quantity'])
            metric = data['metric'].strip().lower()
            unitCost = float(data['unitCost'])
            unitPrice = float(data['unitPrice'])
            amountPaid = float(data['amountPaid'])
            batch_number = itemname

            if metric == "tray":
                quantity *= 30
                metric = "egg"

            new_transfer = TransfersV2(
                shop_id=MANUAL_TRANSFER_SHOP_ID,
                inventoryV2_id=None,
                quantity=quantity,
                metric=metric,
                total_cost=unitCost * quantity,
                BatchNumber=batch_number,
                user_id=current_user_id,
                itemname=itemname,
                amountPaid=amountPaid,
                unitCost=unitCost
            )

            db.session.add(new_transfer)
            db.session.commit()

            existing_stock = ShopStockV2.query.filter_by(
                shop_id=MANUAL_TRANSFER_SHOP_ID,
                itemname=itemname,
                metric=metric,
                BatchNumber=batch_number
            ).first()

            if existing_stock:
                existing_stock.quantity += quantity
                existing_stock.total_cost += unitCost * quantity
                existing_stock.unitPrice = unitPrice
            else:
                new_shop_stock = ShopStockV2(
                    shop_id=MANUAL_TRANSFER_SHOP_ID,
                    inventoryV2_id=None,
                    transferV2_id=new_transfer.transferV2_id,
                    quantity=quantity,
                    total_cost=unitCost * quantity,
                    itemname=itemname,
                    metric=metric,
                    BatchNumber=batch_number,
                    unitPrice=unitPrice
                )
                db.session.add(new_shop_stock)

            db.session.commit()

            return {'message': 'Manual stock added successfully'}, 201

        except ValueError:
            db.session.rollback()
            return {'message': 'Invalid data type provided'}, 400

        except Exception as e:
            db.session.rollback()
            return {'message': 'Error processing request', 'error': str(e)}, 500 


class ProcessInventoryPayment(Resource):
    @jwt_required()
    def post(self):
        data = request.get_json()
        
        required_fields = ['inventory_id', 'amount_paid', 'source_account', 'payment_reference']
        if not all(field in data for field in required_fields):
            return {'message': 'Missing required fields'}, 400
        
        inventory_id = data.get('inventory_id')
        amount_paid = float(data.get('amount_paid'))
        source_account = data.get('source_account')
        payment_reference = data.get('payment_reference')
        notes = data.get('notes', '')
        
        try:
            # Get inventory
            inventory = InventoryV2.query.get(inventory_id)
            if not inventory:
                return {'message': 'Inventory not found'}, 404
            
            # Check if inventory has outstanding balance
            if inventory.ballance <= 0:
                return {'message': 'This inventory has no outstanding balance'}, 400
            
            # Check payment amount
            if amount_paid <= 0:
                return {'message': 'Payment amount must be greater than 0'}, 400
            
            if amount_paid > inventory.ballance:
                return {'message': f'Payment amount exceeds outstanding balance of {inventory.ballance}'}, 400
            
            # Get supplier
            supplier = Suppliers.query.filter_by(
                supplier_name=inventory.Suppliername,
                supplier_location=inventory.Supplier_location
            ).first()
            
            if not supplier:
                return {'message': 'Supplier not found'}, 404
            
            account = BankAccount.query.filter_by(Account_name=source_account).first()
            if not account:
                return {'message': f'Bank account "{source_account}" not found'}, 404
            
            if account.Account_Balance < amount_paid:
                return {'message': f'Insufficient balance in account "{source_account}"'}, 400
            
            # Process the payment
            account.Account_Balance -= amount_paid
            
            # Update inventory
            inventory.amountPaid += amount_paid
            inventory.ballance -= amount_paid
            
            # UPDATE PAYMENT REFERENCE - Append new payment reference to existing one
            if inventory.paymentRef:
                # If there's an existing payment reference, append the new one
                inventory.paymentRef = f"{inventory.paymentRef}, {payment_reference}"
            else:
                # If no existing reference, set it to the new one
                inventory.paymentRef = payment_reference
            
            # UPDATE SOURCE ACCOUNT - Only update if it's a bank account (not "Unknown" or "External funding")
            if source_account not in ["Unknown", "External funding"]:
                # You can choose to either:
                # Option A: Always update to the latest source account
                inventory.source = source_account
                
                # Option B: Append if different (uncomment if you want this behavior)
                # if inventory.source != source_account and inventory.source not in ["Unknown", "External funding"]:
                #     inventory.source = f"{inventory.source}, {source_account}"
                # else:
                #     inventory.source = source_account
            
            # Update payment status and credits_amount
            if inventory.ballance == 0:
                inventory.payment_status = 'paid'
                inventory.credits_amount = 0
            else:
                inventory.payment_status = 'partially_paid'
                inventory.credits_amount = inventory.ballance
            
            # Update supplier
            supplier.total_amount_received += amount_paid
            if supplier.credit_amount:
                supplier.credit_amount -= amount_paid
            
            # Create bank transaction
            transaction = BankingTransaction(
                account_id=account.id,
                Transaction_type_debit=amount_paid,
                Transaction_type_credit=None,
    
            )
            db.session.add(transaction)
            
            # Create supplier history for this payment
            supplier_history = SupplierHistory(
                supplier_id=supplier.supplier_id,
                amount_received=amount_paid,
                transaction_date=datetime.utcnow(),
                item_bought=inventory.itemname,
                payment_status='paid',
                credit_amount=0,
                inventory_id=inventory_id,
                
            )
            db.session.add(supplier_history)
            
            db.session.commit()
            
            return {
                'message': 'Payment processed successfully',
                'inventory_id': inventory_id,
                'supplier_id': supplier.supplier_id,
                'amount_paid': amount_paid,
                'new_balance': inventory.ballance,
                'payment_status': inventory.payment_status,
                'payment_reference': payment_reference,
                'updated_source': inventory.source,
                'updated_payment_ref': inventory.paymentRef
            }, 200
            
        except Exception as e:
            db.session.rollback()
            return {'message': 'Error processing payment', 'error': str(e)}, 500