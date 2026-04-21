from flask import request, jsonify
from flask_restful import Resource
from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError
from flask_jwt_extended import get_jwt_identity, jwt_required
from Server.Models.Users import Users
from Server.Models.Shops import Shops
from Server.Models.InventoryV2 import InventoryV2
from Server.Models.TransferV2 import TransfersV2
from Server.Models.SpoiltStock import SpoiltStock
from Server.Models.Shopstock import ShopStock
from Server.Models.ShopstockV2 import ShopStockV2
from Server.Models.LiveStock import LiveStock
from datetime import datetime, timezone
# import datetime
from app import db
from flask_restful import Resource
from flask import jsonify,request,make_response
from functools import wraps
from Server.Views.Services.journal_service import SpoiltJournalService
from fuzzywuzzy import process

class AddSpoiltFromInventory(Resource):
    @jwt_required()
    def post(self):
        data = request.get_json()

        # Required fields
        required = ['inventory_id', 'quantity']
        for field in required:
            if field not in data:
                return {"error": f"Missing required field: {field}"}, 400

        inventory_id = data['inventory_id']
        quantity = float(data['quantity'])
        comment = data.get('comment')
        disposal_method = data.get('disposal_method')
        collector_name = data.get('collector_name')

        # Logged-in user as clerk
        clerk_id = get_jwt_identity()

        # Fetch inventory batch
        inventory = InventoryV2.query.get(inventory_id)
        if not inventory:
            return {"error": "Inventory batch not found"}, 404

        # Validate quantity
        if quantity <= 0:
            return {"error": "Quantity must be greater than 0"}, 400

        if quantity > inventory.quantity:
            return {
                "error": "Quantity exceeds available stock",
                "available_quantity": inventory.quantity
            }, 400

        # Create spoilt stock entry with defaults
        spoilt = SpoiltStock(
            clerk_id=clerk_id,
            inventory_id=inventory_id,
            quantity=quantity,
            item=inventory.itemname,
            unit=inventory.metric,
            disposal_method=disposal_method,
            collector_name=collector_name,
            comment=comment,
            status="approved",  # ✅ CHANGED: Automatically set to approved
            batches_affected=inventory.BatchNumber,
            created_at = datetime.now(timezone.utc)
        )

        # Deduct from inventory
        inventory.quantity -= quantity
        inventory.totalCost = inventory.quantity * inventory.unitCost

        # Save
        db.session.add(spoilt)
        db.session.commit()

        return {
            "message": "Spoilt stock recorded successfully",
            "spoilt_id": spoilt.id,
            "item": spoilt.item,
            "unit": spoilt.unit,
            "quantity_spoilt": quantity,
            "remaining_batch_quantity": inventory.quantity,
            "batch_number": inventory.BatchNumber
        }, 201


class AddSpoiltStock(Resource):
    @jwt_required()
    def post(self):
        data = request.get_json()

        # Get clerk from JWT
        user_id = get_jwt_identity()
        clerk = Users.query.get(user_id)
        if not clerk:
            return {"message": "Invalid user"}, 400

        # Required fields
        shop_id = data.get('shop_id')
        quantity = data.get('quantity')
        item = data.get('item')
        unit = data.get('unit')  # kgs or count
        disposal_method = data.get('disposal_method')  # depot or waste disposer
        collector_name = data.get('collector_name')
        comment = data.get('comment', '')

        if not all([item, quantity, unit, disposal_method]):
            return {"message": "Missing required fields"}, 400

        try:
            # Convert quantity to float for safety
            quantity = float(quantity)
        except ValueError:
            return {"message": "Invalid quantity format"}, 400

        # Find matching shop stock item(s), sorted by oldest batch first (FIFO)
        shop_stock_entries = ShopStockV2.query.filter_by(
            shop_id=shop_id,
            itemname=item
        ).order_by(ShopStockV2.BatchNumber).all()

        # Find matching livestock entry
        livestock_entry = LiveStock.query.filter_by(
            shop_id=shop_id,
            item_name=item
        ).first()

        if not shop_stock_entries and not livestock_entry:
            return {"message": f"Item '{item}' not found in shop {shop_id} stock or livestock"}, 400

        remaining_to_deduct = quantity
        batch_deductions = []  # Track which batches were deducted
        livestock_deduction = 0.0

        # First deduct from shop stock if available
        for stock in shop_stock_entries:
            if remaining_to_deduct <= 0:
                break
            if stock.quantity <= 0:
                continue

            deduct_amount = min(stock.quantity, remaining_to_deduct)
            stock.quantity -= deduct_amount
            remaining_to_deduct -= deduct_amount
            batch_deductions.append({
                'batch': stock.BatchNumber,
                'deducted': deduct_amount,
                'remaining': stock.quantity
            })
            db.session.add(stock)

        # If still remaining to deduct, try to deduct from livestock
        if remaining_to_deduct > 0 and livestock_entry:
            # Check if livestock has enough current quantity
            if livestock_entry.current_quantity > 0:
                deduct_amount = min(livestock_entry.current_quantity, remaining_to_deduct)
                livestock_entry.current_quantity -= deduct_amount
                livestock_deduction = deduct_amount
                remaining_to_deduct -= deduct_amount
                db.session.add(livestock_entry)

        if remaining_to_deduct > 0:
            db.session.rollback()
            available = quantity - remaining_to_deduct
            sources = []
            if batch_deductions:
                sources.append(f"shop stock: {sum(d['deducted'] for d in batch_deductions)}")
            if livestock_deduction > 0:
                sources.append(f"livestock: {livestock_deduction}")
            
            return {
                "message": f"Not enough stock to deduct spoilt quantity. Needed {quantity}, available {available} ({' + '.join(sources) if sources else 'none'})",
                "available": available,
                "sources": sources
            }, 400

        # Record spoilt stock as PENDING (but inventory is already deducted)
        record = SpoiltStock(
            clerk_id=user_id,
            shop_id=shop_id,
            item=item,
            quantity=quantity,
            unit=unit,
            disposal_method=disposal_method,
            collector_name=collector_name,
            comment=comment,
            status='pending',  # Set as pending - needs approval
            approved_by=None,
            approved_at=None,
            livestock_deduction=livestock_deduction
        )

        # Store batch deduction information
        if batch_deductions:
            batches_info = ', '.join([f"Batch {d['batch']}: -{d['deducted']}{unit}" for d in batch_deductions])
            record.batches_affected = batches_info

        db.session.add(record)
        
        try:
            db.session.commit()
            return {
                "message": "Spoilt stock deducted from inventory and recorded as pending approval",
                "details": {
                    "record_id": record.id,
                    "item": item,
                    "quantity": quantity,
                    "unit": unit,
                    "status": "pending",
                    "disposal_method": disposal_method,
                    "batches_affected": batch_deductions,
                    "livestock_deduction": livestock_deduction,
                    "created_at": record.created_at.isoformat()
                }
            }, 201
        except Exception as e:
            db.session.rollback()
            return {
                "message": "Failed to record spoilt stock",
                "error": str(e)
            }, 500
            

class ApproveSpoiltStock(Resource):
    @jwt_required()
    def post(self, record_id):
        # ===== AUTH USER =====
        user_id = get_jwt_identity()
        approver = Users.query.get(user_id)
        if not approver:
            return {"message": "Invalid user"}, 400

        # ===== FETCH RECORD =====
        spoilt_record = SpoiltStock.query.get(record_id)
        if not spoilt_record:
            return {"message": "Spoilt stock record not found"}, 404

        if spoilt_record.status != 'pending':
            return {"message": f"Record already {spoilt_record.status}"}, 400

        try:
            # ===== APPROVE RECORD =====
            spoilt_record.status = 'approved'
            spoilt_record.approved_by = user_id
            spoilt_record.approved_at = datetime.now(timezone.utc)

            db.session.add(spoilt_record)

            # Flush so updated record is available for journal
            db.session.flush()

            # ===== VALIDATE COST BEFORE JOURNAL =====
            if not hasattr(spoilt_record, "cost_of_spoilage") or spoilt_record.cost_of_spoilage is None:
                raise Exception("Cost of spoilage is missing. Ensure cost is calculated during stock deduction.")

            # ===== POST JOURNAL =====
            journal_result = SpoiltJournalService.post_spoilt_journal(spoilt_record)

            # ===== FINAL COMMIT =====
            db.session.commit()

            return {
                "message": "Spoilt stock approved and journal posted successfully",
                "details": {
                    "record_id": spoilt_record.id,
                    "item": spoilt_record.item,
                    "quantity": spoilt_record.quantity,
                    "unit": spoilt_record.unit,
                    "approved_by": user_id,
                    "approved_at": spoilt_record.approved_at.isoformat()
                },
                "financial": {
                    "cost_of_spoilage": float(spoilt_record.cost_of_spoilage)
                },
                "journal": journal_result
            }, 200

        except Exception as e:
            db.session.rollback()
            return {
                "message": "Failed to approve spoilt stock",
                "error": str(e),
                "spoilt_id": spoilt_record.id if spoilt_record else None
            }, 500

class RejectSpoiltStock(Resource):
    @jwt_required()
    def post(self, record_id):
        user_id = get_jwt_identity()
        rejector = Users.query.get(user_id)
        if not rejector:
            return {"message": "Invalid user"}, 400

        spoilt_record = SpoiltStock.query.get(record_id)
        if not spoilt_record:
            return {"message": "Spoilt stock record not found"}, 404

        if spoilt_record.status != 'pending':
            return {"message": f"Record already {spoilt_record.status}"}, 400

        # RESTORE the deducted stock before rejecting
        shop_id = spoilt_record.shop_id
        quantity = spoilt_record.quantity
        item = spoilt_record.item

        # Restore to shop stock (add back to batches)
        if spoilt_record.batches_affected:
            # Parse the batches_affected string to get batch info
            # Format: "Batch X: -Yunit, Batch Z: -Wunit"
            batch_deductions = []
            for part in spoilt_record.batches_affected.split(', '):
                if 'Batch' in part:
                    batch_info = part.replace('Batch ', '').split(': -')
                    if len(batch_info) == 2:
                        batch_number = batch_info[0].strip()
                        deducted_amount = float(batch_info[1].replace(spoilt_record.unit, '').strip())
                        batch_deductions.append({
                            'batch': batch_number,
                            'deducted': deducted_amount
                        })
            
            # Restore to each batch
            for deduction in batch_deductions:
                stock_entry = ShopStockV2.query.filter_by(
                    shop_id=shop_id,
                    itemname=item,
                    BatchNumber=deduction['batch']
                ).first()
                
                if stock_entry:
                    stock_entry.quantity += deduction['deducted']
                    db.session.add(stock_entry)

        # Restore to livestock if applicable
        if spoilt_record.livestock_deduction and spoilt_record.livestock_deduction > 0:
            livestock_entry = LiveStock.query.filter_by(
                shop_id=shop_id,
                item_name=item
            ).first()
            
            if livestock_entry:
                livestock_entry.current_quantity += spoilt_record.livestock_deduction
                db.session.add(livestock_entry)

        # Update the spoilt stock record to rejected
        spoilt_record.status = 'rejected'
        spoilt_record.approved_by = user_id
        spoilt_record.approved_at = datetime.now(timezone.utc)

        try:
            db.session.commit()
            return {
                "message": "Spoilt stock rejected and inventory restored",
                "details": {
                    "record_id": spoilt_record.id,
                    "item": spoilt_record.item,
                    "quantity": spoilt_record.quantity,
                    "restored_stock": quantity,
                    "rejected_by": user_id,
                    "rejected_at": spoilt_record.approved_at.isoformat()
                }
            }, 200
        except Exception as e:
            db.session.rollback()
            return {
                "message": "Failed to reject spoilt stock",
                "error": str(e)
            }, 500

class GetPendingSpoiltStock(Resource):
    @jwt_required()
    def get(self):
        # Join with Users and Shops tables to get names
        pending_records = db.session.query(
            SpoiltStock,
            Users.username,
            Shops.shopname
        ).join(
            Users, SpoiltStock.clerk_id == Users.users_id
        ).join(
            Shops, SpoiltStock.shop_id == Shops.shops_id
        ).filter(
            SpoiltStock.status == 'pending'
        ).order_by(SpoiltStock.created_at.desc()).all()
        
        result = []
        for record, username, shopname in pending_records:
            result.append({
                'id': record.id,
                'created_at': record.created_at.isoformat(),
                'clerk_id': record.clerk_id,
                'clerk_username': username,  # Add username
                'shop_id': record.shop_id,
                'shop_name': shopname,  # Add shop name
                'item': record.item,
                'quantity': record.quantity,
                'unit': record.unit,
                'disposal_method': record.disposal_method,
                'collector_name': record.collector_name,
                'comment': record.comment,
                'batches_affected': record.batches_affected,
                'livestock_deduction': record.livestock_deduction
            })
        
        return {"pending_records": result}, 200

class SpoiltStockHistory(Resource):
    @jwt_required()
    def get(self):
        # Get query parameters for filtering
        shop_id = request.args.get('shop_id')
        status = request.args.get('status')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        query = SpoiltStock.query
        
        if shop_id:
            query = query.filter_by(shop_id=shop_id)
        if status:
            query = query.filter_by(status=status)
        if start_date:
            query = query.filter(SpoiltStock.created_at >= start_date)
        if end_date:
            query = query.filter(SpoiltStock.created_at <= end_date)
            
        records = query.order_by(SpoiltStock.created_at.desc()).all()
        
        result = []
        for record in records:
            result.append({
                'id': record.id,
                'created_at': record.created_at.isoformat(),
                'clerk_id': record.clerk_id,
                'shop_id': record.shop_id,
                'item': record.item,
                'quantity': record.quantity,
                'unit': record.unit,
                'disposal_method': record.disposal_method,
                'status': record.status,
                'approved_by': record.approved_by,
                'approved_at': record.approved_at.isoformat() if record.approved_at else None,
                'batches_affected': record.batches_affected,
                'livestock_deduction': record.livestock_deduction
            })
        
        return {"spoilt_stock_history": result}, 200
    
class SpoiltStockResource(Resource):
    @jwt_required()
    def get(self):
        try:
            shop_id = request.args.get('shop_id')
            filter_by_shop = request.args.get('filter_by_shop', 'false').lower() == 'true'
            
            base_query = SpoiltStock.query.order_by(SpoiltStock.created_at.desc())
            
            # Filter by shop_id if provided
            if shop_id:
                # If shop_id is provided, filter by exact match
                records = base_query.filter_by(shop_id=shop_id).all()
            elif filter_by_shop:
                # If filter_by_shop=true but no shop_id, filter out records with null shop_id
                records = base_query.filter(SpoiltStock.shop_id.isnot(None)).all()
            else:
                # Get all records (including those with null shop_id)
                records = base_query.all()

            result = []
            for record in records:
                user = Users.query.filter_by(users_id=record.clerk_id).first()
                shop = Shops.query.filter_by(shops_id=record.shop_id).first() if record.shop_id else None

                username = user.username if user else "Unknown User"
                
                # Determine shopname
                if record.shop_id is None:
                    shopname = "Inventory"
                elif shop:
                    shopname = shop.shopname
                else:
                    shopname = "Unknown Shop"

                # Format created_at
                if record.created_at:
                    if isinstance(record.created_at, str):
                        try:
                            created_at = datetime.strptime(record.created_at, '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d %H:%M:%S')
                        except ValueError:
                            created_at = record.created_at
                    else:
                        created_at = record.created_at.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    created_at = None

                result.append({
                    "id": record.id,
                    "created_at": created_at,
                    "clerk_id": record.clerk_id,
                    "username": username,
                    "shop_id": record.shop_id,
                    "shop_name": shopname,
                    "item": record.item,
                    "quantity": record.quantity,
                    "unit": record.unit,
                    "disposal_method": record.disposal_method,
                    "collector_name": record.collector_name,
                    'batches_affected': record.batches_affected,
                    'status': record.status,
                    "comment": record.comment
                })

            return make_response(jsonify(result), 200)
        
        except Exception as e:
            return make_response(jsonify({"error": str(e)}), 500)


    @jwt_required()
    def put(self, id):
        data = request.get_json()

        record = SpoiltStock.query.get(id)
        if not record:
            return {"message": "Spoilt stock record not found"}, 404

        record.item = data.get('item', record.item)
        record.quantity = data.get('quantity', record.quantity)
        record.unit = data.get('unit', record.unit)
        record.disposal_method = data.get('disposal_method', record.disposal_method)
        record.collector_name = data.get('collector_name', record.collector_name)
        record.comment = data.get('comment', record.comment)

        db.session.commit()

        return {"message": "Spoilt stock record updated successfully"}, 200

    @jwt_required()
    def delete(self, id):
        record = SpoiltStock.query.get(id)
        if not record:
            return {"message": "Spoilt stock record not found"}, 404

        db.session.delete(record)
        db.session.commit()

        return {"message": "Spoilt stock record deleted successfully"}, 200


class SpoiltValue(Resource):
    def get(self):
        """Get combined stock loss report from spoilt stock and transfer differences per shop"""
        
        shop_id = request.args.get('shop_id')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        # Parse date filters if provided
        date_filters = {}
        if start_date:
            try:
                date_filters['start_date'] = datetime.strptime(start_date, '%Y-%m-%d').date()
            except ValueError:
                return make_response(jsonify({"error": "Invalid start_date format. Use YYYY-MM-DD"}), 400)
        
        if end_date:
            try:
                date_filters['end_date'] = datetime.strptime(end_date, '%Y-%m-%d').date()
            except ValueError:
                return make_response(jsonify({"error": "Invalid end_date format. Use YYYY-MM-DD"}), 400)
        
        # Get spoilt stock records
        spoilt_query = SpoiltStock.query
        
        if shop_id:
            spoilt_query = spoilt_query.filter_by(shop_id=shop_id)
        
        if 'start_date' in date_filters:
            spoilt_query = spoilt_query.filter(SpoiltStock.created_at >= date_filters['start_date'])
        
        if 'end_date' in date_filters:
            spoilt_query = spoilt_query.filter(SpoiltStock.created_at <= date_filters['end_date'])
        
        spoilt_records = spoilt_query.order_by(SpoiltStock.created_at.desc()).all()
        
        # Get transfer records with differences
        transfer_query = TransfersV2.query.filter(TransfersV2.difference != 0)
        
        if shop_id:
            transfer_query = transfer_query.filter_by(shop_id=shop_id)
        
        if 'start_date' in date_filters:
            transfer_query = transfer_query.filter(TransfersV2.created_at >= date_filters['start_date'])
        
        if 'end_date' in date_filters:
            transfer_query = transfer_query.filter(TransfersV2.created_at <= date_filters['end_date'])
        
        transfer_records = transfer_query.order_by(TransfersV2.created_at.desc()).all()
        
        # Process spoilt stock records
        spoilt_losses = []
        for record in spoilt_records:
            user = Users.query.filter_by(users_id=record.clerk_id).first()
            
            # Get shop name
            if record.shop_id:
                shop = Shops.query.filter_by(shops_id=record.shop_id).first()
                shopname = shop.shopname if shop else f"Shop ID: {record.shop_id}"
            else:
                shopname = "Inventory"
            
            # Calculate value for spoilt stock
            # First try to get unit cost from InventoryV2 using item name
            inventory_item = InventoryV2.query.filter_by(
                itemname=record.item
            ).order_by(InventoryV2.created_at.desc()).first()
            
            if inventory_item:
                unit_cost = inventory_item.unitCost
                total_value = unit_cost * record.quantity if unit_cost else 0
            else:
                unit_cost = None
                total_value = 0
            
            spoilt_losses.append({
                "type": "spoilt_stock",
                "id": record.id,
                "date": record.created_at.strftime('%Y-%m-%d') if record.created_at else None,
                "datetime": record.created_at.strftime('%Y-%m-%d %H:%M:%S') if record.created_at else None,
                "shop_id": record.shop_id,
                "shop_name": shopname,
                "item": record.item,
                "quantity": record.quantity,
                "unit": record.unit,
                "unit_cost": unit_cost,
                "total_value": total_value,
                "reason": f"Spoilt - {record.disposal_method}",
                "batch_number": record.batches_affected,
                "clerk": user.username if user else "Unknown",
                "status": record.status,
                "comment": record.comment
            })
        
        # Process transfer differences
        transfer_losses = []
        for transfer in transfer_records:
            # Only consider negative differences (losses)
            if transfer.difference >= 0:
                continue
                
            user = Users.query.filter_by(users_id=transfer.user_id).first()
            shop = Shops.query.filter_by(shops_id=transfer.shop_id).first()
            
            # Calculate value for transfer difference
            unit_cost = transfer.unitCost
            
            # If unitCost is not available in transfer, try to get from InventoryV2
            if not unit_cost and transfer.BatchNumber:
                inventory_item = InventoryV2.query.filter_by(
                    BatchNumber=transfer.BatchNumber
                ).first()
                if inventory_item:
                    unit_cost = inventory_item.unitCost
            
            # Calculate loss value (difference is negative for losses)
            loss_quantity = abs(transfer.difference)
            total_value = unit_cost * loss_quantity if unit_cost else 0
            
            transfer_losses.append({
                "type": "transfer_difference",
                "id": transfer.transferv2_id,
                "date": transfer.created_at.strftime('%Y-%m-%d') if transfer.created_at else None,
                "datetime": transfer.created_at.strftime('%Y-%m-%d %H:%M:%S') if transfer.created_at else None,
                "shop_id": transfer.shop_id,
                "shop_name": shop.shopname if shop else f"Shop ID: {transfer.shop_id}",
                "item": transfer.itemname,
                "quantity": loss_quantity,
                "unit": transfer.metric,
                "unit_cost": unit_cost,
                "total_value": total_value,
                "reason": f"Transfer Shortage",
                "batch_number": transfer.BatchNumber,
                "clerk": user.username if user else "Unknown",
                "received_quantity": transfer.received_quantity,
                "expected_quantity": transfer.quantity,
                "difference": transfer.difference,
                "status": transfer.status
            })
        
        # Combine both lists
        all_losses = spoilt_losses + transfer_losses
        
        # Sort by date descending
        all_losses.sort(key=lambda x: x['datetime'] or '', reverse=True)
        
        # Calculate totals
        total_spoilt_value = sum(item['total_value'] for item in spoilt_losses)
        total_transfer_loss_value = sum(item['total_value'] for item in transfer_losses)
        total_loss_value = total_spoilt_value + total_transfer_loss_value
        
        # Group by shop for summary
        shop_summary = {}
        for loss in all_losses:
            shop_id_key = loss['shop_id'] or 'inventory'
            shop_name = loss['shop_name']
            
            if shop_id_key not in shop_summary:
                shop_summary[shop_id_key] = {
                    'shop_id': loss['shop_id'],
                    'shop_name': shop_name,
                    'total_loss_value': 0,
                    'spoilt_value': 0,
                    'transfer_loss_value': 0,
                    'item_count': 0
                }
            
            shop_summary[shop_id_key]['total_loss_value'] += loss['total_value']
            shop_summary[shop_id_key]['item_count'] += 1
            
            if loss['type'] == 'spoilt_stock':
                shop_summary[shop_id_key]['spoilt_value'] += loss['total_value']
            else:
                shop_summary[shop_id_key]['transfer_loss_value'] += loss['total_value']
        
        # Convert shop_summary to list
        shop_summary_list = list(shop_summary.values())
        
        return jsonify({
            "status": "success",
            "data": all_losses,
            "summary": {
                "total_losses": len(all_losses),
                "total_spoilt_items": len(spoilt_losses),
                "total_transfer_differences": len(transfer_losses),
                "total_spoilt_value": total_spoilt_value,
                "total_transfer_loss_value": total_transfer_loss_value,
                "total_loss_value": total_loss_value,
                "shops_summary": shop_summary_list
            },
            "count": len(all_losses),
            "message": "Stock loss report retrieved successfully"
        })