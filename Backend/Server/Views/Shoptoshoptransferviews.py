from flask import request, jsonify
from flask_restful import Resource
from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError
from flask_jwt_extended import get_jwt_identity, jwt_required
from Server.Models.Users import Users
from Server.Models.Shops import Shops
from Server.Models.ShopstockV2 import ShopStockV2
from Server.Models.InventoryV2 import InventoryV2
from Server.Models.Shoptoshoptransfer import Shoptoshoptransfer
from Server.Models.Employees import Employees
from app import db
from flask_restful import Resource
from sqlalchemy.orm import joinedload
from flask import jsonify,request,make_response
from functools import wraps
from sqlalchemy import func, text
from sqlalchemy import or_



class ShopToShopTransfer(Resource):
    @jwt_required()
    def post(self):
        data = request.get_json()

        # User
        user_id = get_jwt_identity()
        user = Users.query.get(user_id)
        if not user:
            return {"message": "Invalid user"}, 400

        from_shop_id = data.get('from_shop_id')
        to_shop_id = data.get('to_shop_id')
        quantity = data.get('quantity')
        item_name = data.get('item_name')

        # ✅ Validate inputs
        if not all([from_shop_id, to_shop_id, item_name, quantity]):
            return {"message": "Missing required fields"}, 400

        if from_shop_id == to_shop_id:
            return {"message": "Source and destination shops cannot be the same"}, 400

        try:
            quantity = float(quantity)
            if quantity <= 0:
                return {"message": "Quantity must be a positive number"}, 400
        except ValueError:
            return {"message": "Quantity must be numeric"}, 400

        # ✅ Get batches (FIFO by batch number, skip empties)
        source_batches = (
            ShopStockV2.query
            .filter_by(shop_id=from_shop_id, itemname=item_name)
            .filter(ShopStockV2.quantity > 0)
            .order_by(ShopStockV2.BatchNumber.asc())
            .all()
        )

        if not source_batches:
            return {"message": "Item not found in source shop"}, 404

        total_available = sum(batch.quantity for batch in source_batches)
        if total_available < quantity - 0.001:
            return {
                "message": "Insufficient stock",
                "available": total_available,
                "requested": quantity
            }, 400

        qty_to_transfer = quantity
        transfer_records = []
        created_transfers = []

        try:
            for batch in source_batches:
                if qty_to_transfer <= 0:
                    break

                take_qty = min(batch.quantity, qty_to_transfer)
                if take_qty <= 0:
                    continue

                # ✅ ONLY Deduct from source batch - DO NOT add to destination yet
                batch.quantity -= take_qty
                db.session.add(batch)

                # ✅ Create transfer record with status "pending"
                transfer = Shoptoshoptransfer(
                    from_shop_id=from_shop_id,
                    to_shop_id=to_shop_id,
                    users_id=user_id,
                    stockv2_id=batch.stockv2_id,
                    itemname=batch.itemname,
                    metric=batch.metric,
                    quantity=take_qty,
                    status="pending"
                )
                db.session.add(transfer)
                created_transfers.append(transfer)

                # ✅ Record transfer info
                transfer_records.append({
                    "transfer_id": transfer.transfer_id,  # Fixed: using transfer_id instead of id
                    "batch_number": batch.BatchNumber,
                    "deducted": take_qty,
                    "metric": batch.metric
                })

                qty_to_transfer -= take_qty

            db.session.flush()  # Flush to get transfer IDs
            
            # ===== CREATE DATABASE NOTIFICATIONS =====
            from Server.Views.Services.notifications_service import NotificationService
            
            # Get shop details
            from_shop = Shops.query.get(from_shop_id)
            to_shop = Shops.query.get(to_shop_id)
            
            from_shop_name = from_shop.shopname if from_shop and hasattr(from_shop, 'shopname') else f"Shop {from_shop_id}"
            to_shop_name = to_shop.shopname if to_shop and hasattr(to_shop, 'shopname') else f"Shop {to_shop_id}"
            
            # Prepare notification data
            notification_data = {
                'from_shop_id': from_shop_id,
                'from_shop_name': from_shop_name,
                'to_shop_id': to_shop_id,
                'to_shop_name': to_shop_name,
                'itemname': item_name,
                'quantity': quantity,
                'transfers': transfer_records,
                'initiated_by': user_id,
                'initiated_by_name': user.username if user else str(user_id),
                'initiated_at': datetime.utcnow().isoformat(),
                'status': 'pending'
            }
            
            notified_users = []
            
            # 1. NOTIFY THE USER WHO INITIATED THE TRANSFER (sender)
            if user_id:
                NotificationService.create_notification(
                    user_id=user_id,
                    notification_type='shop_to_shop_transfer_initiated',
                    title='Transfer Initiated',
                    message=f'You initiated a transfer of {quantity} {transfer_records[0]["metric"] if transfer_records else ""} {item_name} from your shop ({from_shop_name}) to {to_shop_name}',
                    data=notification_data
                )
                notified_users.append({
                    'user_id': user_id,
                    'type': 'initiator',
                    'shop': 'sending'
                })
                print(f"Notification sent to initiator (user: {user_id})")
            
            # 2. NOTIFY ALL USERS LINKED TO THE RECEIVING SHOP (to_shop)
            # Get all active employees for the receiving shop
            receiving_shop_employees = Employees.query.filter_by(
                shop_id=to_shop_id,
                account_status='active'
            ).all()
            
            receiving_shop_notified = 0
            for employee in receiving_shop_employees:
                employee_user = Users.query.filter_by(employee_id=employee.employee_id).first()
                
                if employee_user:
                    # Skip if this user is the same as the initiator
                    if employee_user.users_id == user_id:
                        print(f"Skipping initiator {employee_user.users_id} (already notified)")
                        continue
                    
                    NotificationService.create_notification(
                        user_id=employee_user.users_id,
                        notification_type='shop_to_shop_transfer_pending',
                        title='Pending Stock Transfer',
                        message=f'{quantity} {transfer_records[0]["metric"] if transfer_records else ""} of {item_name} is pending transfer from {from_shop_name} to your shop ({to_shop_name}). Please confirm receipt.',
                        data=notification_data
                    )
                    receiving_shop_notified += 1
                    notified_users.append({
                        'user_id': employee_user.users_id,
                        'employee_id': employee.employee_id,
                        'employee_name': f"{employee.first_name} {employee.surname}",
                        'type': 'receiving_shop_staff'
                    })
                    print(f"Notification sent to receiving shop staff: {employee.first_name} {employee.surname} (user: {employee_user.users_id})")
            
            # 3. OPTIONAL: NOTIFY USERS LINKED TO THE SENDING SHOP (for awareness)
            # Uncomment if you want to notify sending shop staff about the transfer
            """
            sending_shop_employees = Employees.query.filter_by(
                shop_id=from_shop_id,
                account_status='active'
            ).all()
            
            sending_shop_notified = 0
            for employee in sending_shop_employees:
                employee_user = Users.query.filter_by(employee_id=employee.employee_id).first()
                
                if employee_user and employee_user.users_id != user_id:
                    NotificationService.create_notification(
                        user_id=employee_user.users_id,
                        notification_type='shop_to_shop_transfer_awareness',
                        title='Stock Transfer Initiated',
                        message=f'{quantity} {transfer_records[0]["metric"] if transfer_records else ""} of {item_name} has been transferred from your shop to {to_shop_name}',
                        data=notification_data
                    )
                    sending_shop_notified += 1
                    notified_users.append({
                        'user_id': employee_user.users_id,
                        'type': 'sending_shop_staff'
                    })
            """
            
            db.session.commit()

            return {
                "message": "Transfer initiated successfully - awaiting recipient confirmation",
                "item": item_name,
                "requested_quantity": quantity,
                "deductions": transfer_records,
                "destination_shop": to_shop_id,
                "status": "pending",
                "notifications_summary": {
                    "initiator_notified": bool(user_id),
                    "receiving_shop_staff_notified": receiving_shop_notified,
                    "total_notified": len(notified_users)
                }
            }, 201

        except Exception as e:
            db.session.rollback()
            return {"message": "Transfer failed", "error": str(e)}, 500


class ConfirmTransfer(Resource):
    @jwt_required()
    def post(self, transfer_id):
        data = request.get_json()
        action = data.get("action")  # "accept" or "decline"
        note = data.get("note", "")

        user_id = get_jwt_identity()
        user = Users.query.get(user_id)
        if not user:
            return {"message": "Invalid user"}, 400

        transfer = Shoptoshoptransfer.query.get(transfer_id)
        if not transfer or transfer.status != "pending":
            return {"message": "Invalid or already processed transfer"}, 400

        # ✅ Extract details from transfer
        batch_number = transfer.stockv2.BatchNumber if transfer.stockv2 else None
        inv_id = transfer.stockv2.inventoryv2_id if transfer.stockv2 else None
        metric = transfer.metric if hasattr(transfer, "metric") else None

        if action == "accept":
            # ✅ Look for existing destination stock with same batch & itemname
            destination_stock = ShopStockV2.query.filter_by(
                shop_id=transfer.to_shop_id,
                BatchNumber=batch_number,
                itemname=transfer.itemname
            ).first()

            if destination_stock:
                # ✅ Add quantity to existing stock
                destination_stock.quantity += transfer.quantity
            else:
                # ✅ Create new stock entry in destination shop
                new_stock = ShopStockV2(
                    shop_id=transfer.to_shop_id,
                    inventoryv2_id=inv_id,
                    itemname=transfer.itemname,
                    quantity=transfer.quantity,
                    BatchNumber=batch_number,
                    metric=metric
                )
                db.session.add(new_stock)

            transfer.status = "accepted"
            transfer.decline_note = None
            transfer.notification_ack = True

        elif action == "decline":
            # ✅ Return stock to sender shop
            sender_stock = ShopStockV2.query.filter_by(
                shop_id=transfer.from_shop_id,
                BatchNumber=batch_number,
                itemname=transfer.itemname
            ).first()

            if sender_stock:
                sender_stock.quantity += transfer.quantity
            else:
                # ✅ If original batch doesn't exist, create it
                new_sender_stock = ShopStockV2(
                    shop_id=transfer.from_shop_id,
                    inventoryv2_id=inv_id,
                    itemname=transfer.itemname,
                    quantity=transfer.quantity,
                    BatchNumber=batch_number,
                    metric=metric
                )
                db.session.add(new_sender_stock)

            transfer.status = "declined"
            transfer.decline_note = note or "No reason provided"
            transfer.notification_ack = False

        else:
            return {"message": "Invalid action"}, 400

        db.session.commit()
        return {"message": f"Transfer {action}ed successfully"}

class DeclineTransfers(Resource):
    @jwt_required()
    def patch(self, transfer_id):
        data = request.get_json() or {}
        note = data.get("note", "No reason provided")

        user_id = get_jwt_identity()
        user = Users.query.get(user_id)
        if not user:
            return {"message": "Invalid user"}, 400

        transfer = Shoptoshoptransfer.query.get(transfer_id)
        if not transfer:
            return {"message": "Transfer not found"}, 404

        if transfer.status != "pending":
            return {"message": "Only pending transfers can be declined"}, 400

        try:
            # ✅ Extract details
            batch_number = transfer.stockv2.BatchNumber if transfer.stockv2 else None
            inv_id = transfer.stockv2_id if transfer.stockv2 else None

            # ✅ Restore stock to sender shop
            sender_stock = ShopStockV2.query.filter_by(
                shop_id=transfer.from_shop_id,
                BatchNumber=batch_number,
                itemname=transfer.itemname,
                inventoryv2_id=inv_id
            ).first()

            if sender_stock:
                sender_stock.quantity += transfer.quantity
            else:
                # If stock row doesn't exist, create it
                sender_stock = ShopStockV2(
                    shop_id=transfer.from_shop_id,
                    inventoryv2_id=inv_id,
                    itemname=transfer.itemname,
                    quantity=transfer.quantity,
                    BatchNumber=batch_number,
                    metric=transfer.metric
                )
                db.session.add(sender_stock)

            # ✅ Update transfer status
            transfer.status = "declined"
            transfer.decline_note = note
            transfer.notification_ack = False  # trigger popup for sender

            db.session.flush()  # Flush to ensure transfer is saved before notifications
            
            # ===== CREATE DATABASE NOTIFICATIONS =====
            from Server.Views.Services.notifications_service import NotificationService
            
            # Get shop details
            from_shop = Shops.query.get(transfer.from_shop_id)
            to_shop = Shops.query.get(transfer.to_shop_id)
            
            from_shop_name = from_shop.shopname if from_shop and hasattr(from_shop, 'shopname') else f"Shop {transfer.from_shop_id}"
            to_shop_name = to_shop.shopname if to_shop and hasattr(to_shop, 'shopname') else f"Shop {transfer.to_shop_id}"
            
            # Get the user who declined (current user)
            declining_user = Users.query.get(user_id)
            
            # Get employee details for the declining user (if they are an employee)
            declining_employee = Employees.query.filter_by(employee_id=declining_user.employee_id).first() if declining_user and declining_user.employee_id else None
            
            # Prepare decliner info
            decliner_name = declining_user.username if declining_user else str(user_id)
            if declining_employee:
                decliner_name = f"{declining_employee.first_name} {declining_employee.surname}"
            
            decliner_role = declining_employee.role if declining_employee else "Staff"
            decliner_shop = to_shop_name if transfer.to_shop_id else "the receiving shop"
            
            # Get the user who initiated the transfer (sender)
            initiator_user = Users.query.get(transfer.users_id) if transfer.users_id else None
            
            # Get employee details for the initiator (if they are an employee)
            initiator_employee = Employees.query.filter_by(employee_id=initiator_user.employee_id).first() if initiator_user and initiator_user.employee_id else None
            initiator_name = initiator_user.username if initiator_user else "Unknown"
            if initiator_employee:
                initiator_name = f"{initiator_employee.first_name} {initiator_employee.surname}"
            
            # Prepare notification data
            notification_data = {
                'transfer_id': transfer.transfer_id,
                'from_shop_id': transfer.from_shop_id,
                'from_shop_name': from_shop_name,
                'to_shop_id': transfer.to_shop_id,
                'to_shop_name': to_shop_name,
                'itemname': transfer.itemname,
                'quantity': transfer.quantity,
                'metric': transfer.metric,
                'batch_number': batch_number,
                'declined_by': user_id,
                'declined_by_name': decliner_name,
                'declined_by_role': decliner_role,
                'declined_by_shop': decliner_shop,
                'declined_at': datetime.utcnow().isoformat(),
                'decline_note': note,
                'restored_quantity': transfer.quantity,
                'status': 'declined'
            }
            
            notified_users = []
            
            # 1. NOTIFY THE USER WHO DECLINED THE TRANSFER
            if user_id:
                NotificationService.create_notification(
                    user_id=user_id,
                    notification_type='shop_to_shop_transfer_declined_by_you',
                    title='Transfer Declined',
                    message=f'You declined the transfer of {transfer.quantity} {transfer.metric} of {transfer.itemname} from {from_shop_name} to {to_shop_name}',
                    data=notification_data
                )
                notified_users.append({
                    'user_id': user_id,
                    'type': 'decliner',
                    'role': 'receiver',
                    'name': decliner_name
                })
                print(f"Notification sent to decliner: {decliner_name} (user: {user_id})")
            
            # 2. NOTIFY THE USER WHO INITIATED THE TRANSFER (sender) - WITH DECLINER INFO
            if initiator_user and initiator_user.users_id != user_id:
                # Create a detailed message with decliner information
                decline_message = f'{decliner_name} from {to_shop_name} declined your transfer of {transfer.quantity} {transfer.metric} of {transfer.itemname}'
                
                if note and note != "No reason provided":
                    decline_message += f'. Reason: {note}'
                
                NotificationService.create_notification(
                    user_id=initiator_user.users_id,
                    notification_type='shop_to_shop_transfer_declined',
                    title='Transfer Declined',
                    message=decline_message,
                    data=notification_data
                )
                notified_users.append({
                    'user_id': initiator_user.users_id,
                    'type': 'initiator',
                    'role': 'sender',
                    'name': initiator_name
                })
                print(f"Notification sent to initiator: {initiator_name} (user: {initiator_user.users_id}) - Declined by: {decliner_name}")
            else:
                if not initiator_user:
                    print(f"No initiator user found for transfer {transfer_id}")
                elif initiator_user.users_id == user_id:
                    print(f"Initiator is the same as decliner, skipping duplicate notification")
            
            # 3. OPTIONAL: NOTIFY OTHER STAFF AT THE RECEIVING SHOP ABOUT THE DECLINE
            # Uncomment if you want to notify other staff at the receiving shop
            """
            if transfer.to_shop_id:
                receiving_shop_employees = Employees.query.filter_by(
                    shop_id=transfer.to_shop_id,
                    account_status='active'
                ).all()
                
                receiving_shop_notified = 0
                for employee in receiving_shop_employees:
                    employee_user = Users.query.filter_by(employee_id=employee.employee_id).first()
                    
                    if employee_user and employee_user.users_id != user_id:
                        if not initiator_user or employee_user.users_id != initiator_user.users_id:
                            employee_name = f"{employee.first_name} {employee.surname}"
                            NotificationService.create_notification(
                                user_id=employee_user.users_id,
                                notification_type='shop_to_shop_transfer_declined_shop_notification',
                                title='Transfer Declined',
                                message=f'{decliner_name} declined a transfer of {transfer.quantity} {transfer.metric} of {transfer.itemname} from {from_shop_name}',
                                data=notification_data
                            )
                            receiving_shop_notified += 1
                            notified_users.append({
                                'user_id': employee_user.users_id,
                                'type': 'receiving_shop_staff',
                                'name': employee_name
                            })
                print(f"Notified {receiving_shop_notified} additional receiving shop staff members")
            """
            
            # 4. OPTIONAL: NOTIFY STAFF AT THE SENDING SHOP ABOUT THE DECLINE
            # Uncomment if you want to notify staff at the sending shop
            """
            if transfer.from_shop_id:
                sending_shop_employees = Employees.query.filter_by(
                    shop_id=transfer.from_shop_id,
                    account_status='active'
                ).all()
                
                sending_shop_notified = 0
                for employee in sending_shop_employees:
                    employee_user = Users.query.filter_by(employee_id=employee.employee_id).first()
                    
                    if employee_user and employee_user.users_id != user_id:
                        if not initiator_user or employee_user.users_id != initiator_user.users_id:
                            employee_name = f"{employee.first_name} {employee.surname}"
                            NotificationService.create_notification(
                                user_id=employee_user.users_id,
                                notification_type='shop_to_shop_transfer_declined_shop_notification',
                                title='Transfer Declined',
                                message=f'A transfer of {transfer.quantity} {transfer.metric} of {transfer.itemname} to {to_shop_name} was declined by {decliner_name}',
                                data=notification_data
                            )
                            sending_shop_notified += 1
                            notified_users.append({
                                'user_id': employee_user.users_id,
                                'type': 'sending_shop_staff',
                                'name': employee_name
                            })
                print(f"Notified {sending_shop_notified} additional sending shop staff members")
            """
            
            db.session.commit()

            return {
                "message": "Transfer declined successfully, stock returned to sender shop",
                "transfer_id": transfer_id,
                "restored_quantity": transfer.quantity,
                "metric": transfer.metric,
                "sender_shop": transfer.from_shop_id,
                "decliner": {
                    "user_id": user_id,
                    "name": decliner_name,
                    "role": decliner_role,
                    "shop": to_shop_name
                },
                "notifications_summary": {
                    "decliner_notified": bool(user_id),
                    "initiator_notified": bool(initiator_user and initiator_user.users_id != user_id),
                    "total_notified": len(notified_users)
                }
            }, 200

        except Exception as e:
            db.session.rollback()
            return {"message": "Error declining transfer", "error": str(e)}, 500



# class TransferNotifications(Resource):
#     @jwt_required()
#     def get(self):
#         shop_id = request.args.get("shop_id", type=int)
#         if not shop_id:
#             return {"message": "shop_id is required"}, 400

#         user_id = get_jwt_identity()
#         user = Users.query.get(user_id)
#         if not user:
#             return {"message": "Invalid user"}, 400

#         # ✅ Get all declined & unacknowledged transfers where this shop is the sender
#         declined_transfers = (
#             Shoptoshoptransfer.query
#             .filter_by(from_shop_id=shop_id, status="declined", notification_ack=False)
#             .all()
#         )

#         results = []
#         for t in declined_transfers:
#             # Get the to_shop name by querying the Shops model
#             to_shop = Shops.query.get(t.to_shop_id)
#             to_shop_name = to_shop.shopname if to_shop else "Unknown Shop"
            
#             results.append({
#                 "transfer_id": t.transfer_id,
#                 "itemname": t.itemname,
#                 "quantity_returned": t.quantity,
#                 "decline_note": t.decline_note,
#                 "to_shop_id": t.to_shop_id,
#                 "to_shop_name": to_shop_name,
#                 "declined_at": t.transfer_date.isoformat()
#             })

#         return results, 200


# class AcknowledgeNotification(Resource):
#     @jwt_required()
#     def post(self, transfer_id):
#         transfer = Shoptoshoptransfer.query.get(transfer_id)
#         if not transfer:
#             return {"message": "Transfer not found"}, 404

#         transfer.notification_ack = True
#         db.session.commit()
#         return {"message": "Notification acknowledged"}

            
class GetAllShopToShopTransfers(Resource):
    @jwt_required()
    def get(self):
        # Get query parameters
        from_shop_id = request.args.get('from_shop_id')
        to_shop_id = request.args.get('to_shop_id')
        shop_id = request.args.get('shop_id')  # For transfers involving either from or to shop
        item_name = request.args.get('item_name')
        status = request.args.get('status')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        # Build base query
        query = Shoptoshoptransfer.query.options(
            db.joinedload(Shoptoshoptransfer.user),
            db.joinedload(Shoptoshoptransfer.shop),
            db.joinedload(Shoptoshoptransfer.stockv2)
        )
        
        # Apply filters
        if from_shop_id:
            query = query.filter_by(from_shop_id=from_shop_id)
        
        if to_shop_id:
            query = query.filter_by(to_shop_id=to_shop_id)
        
        if shop_id:
            # Filter by transfers involving the shop (either as sender or receiver)
            query = query.filter(
                db.or_(
                    Shoptoshoptransfer.from_shop_id == shop_id,
                    Shoptoshoptransfer.to_shop_id == shop_id
                )
            )
        
        if item_name:
            # Case-insensitive search for item name
            query = query.filter(Shoptoshoptransfer.itemname.ilike(f"%{item_name}%"))
        
        if status:
            query = query.filter_by(status=status)
        
        # Date range filtering
        if start_date:
            try:
                start_datetime = datetime.strptime(start_date, '%Y-%m-%d')
                query = query.filter(Shoptoshoptransfer.transfer_date >= start_datetime)
            except ValueError:
                return make_response(jsonify({"error": "Invalid start_date format. Use YYYY-MM-DD"}), 400)
        
        if end_date:
            try:
                end_datetime = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
                query = query.filter(Shoptoshoptransfer.transfer_date < end_datetime)
            except ValueError:
                return make_response(jsonify({"error": "Invalid end_date format. Use YYYY-MM-DD"}), 400)
        
        # Order by transfer date (most recent first)
        query = query.order_by(Shoptoshoptransfer.transfer_date.desc())
        
        # Get all transfers
        transfers = query.all()
        
        if not transfers:
            return make_response(jsonify({"message": "No transfers found"}), 404)
        
        transfers_data = []
        for transfer in transfers:
            # Get additional shop names
            from_shop = Shops.query.get(transfer.from_shop_id)
            to_shop = Shops.query.get(transfer.to_shop_id)
            
            transfers_data.append({
                "transfer_id": transfer.transfer_id,
                "shops_id": transfer.shops_id,
                "shop_name": transfer.shop.shopname if transfer.shop else "Unknown Shop",
                "from_shop_id": transfer.from_shop_id,
                "from_shop_name": from_shop.shopname if from_shop else "Unknown Shop",
                "to_shop_id": transfer.to_shop_id,
                "to_shop_name": to_shop.shopname if to_shop else "Unknown Shop",
                "user_id": transfer.users_id,
                "username": transfer.user.username if transfer.user else "Unknown User",
                "stockv2_id": transfer.stockv2_id,
                "itemname": transfer.itemname,
                "quantity": transfer.quantity,
                "status": transfer.status,
                "batch_number": transfer.stockv2.BatchNumber if transfer.stockv2 else "Unknown",
                "unit_price": transfer.stockv2.unitPrice if transfer.stockv2 else 0,
                "transfer_date": transfer.transfer_date.isoformat() if transfer.transfer_date else None
            })

        return make_response(jsonify(transfers_data), 200)
    
class GetPendingShopToShopTransfers(Resource):
    @jwt_required()
    def get(self):
        # Get shop_id from query parameters
        shop_id = request.args.get('shop_id')
        
        if not shop_id:
            return make_response(jsonify({"error": "shop_id query parameter is required"}), 400)
        
        try:
            shop_id = int(shop_id)
        except ValueError:
            return make_response(jsonify({"error": "shop_id must be a valid integer"}), 400)
        
        # Query for pending transfers where the shop is the RECEIVER (to_shop_id)
        pending_transfers = Shoptoshoptransfer.query.options(
            db.joinedload(Shoptoshoptransfer.user),
            db.joinedload(Shoptoshoptransfer.shop),
            db.joinedload(Shoptoshoptransfer.stockv2)
        ).filter(
            Shoptoshoptransfer.status == "pending",
            Shoptoshoptransfer.to_shop_id == shop_id  # Only transfers TO this shop
        ).order_by(Shoptoshoptransfer.transfer_date.desc()).all()
        
        transfers_data = []
        for transfer in pending_transfers:
            # Get additional shop names
            from_shop = Shops.query.get(transfer.from_shop_id)
            to_shop = Shops.query.get(transfer.to_shop_id)
            
            transfers_data.append({
                "transfer_id": transfer.transfer_id,
                "shops_id": transfer.shops_id,
                "shop_name": transfer.shop.shopname if transfer.shop else "Unknown Shop",
                "from_shop_id": transfer.from_shop_id,
                "from_shop_name": from_shop.shopname if from_shop else "Unknown Shop",
                "to_shop_id": transfer.to_shop_id,
                "to_shop_name": to_shop.shopname if to_shop else "Unknown Shop",
                "user_id": transfer.users_id,
                "username": transfer.user.username if transfer.user else "Unknown User",
                "stockv2_id": transfer.stockv2_id,
                "itemname": transfer.itemname,
                "metric": transfer.metric,
                "quantity": transfer.quantity,
                "status": transfer.status,
                "batch_number": transfer.stockv2.BatchNumber if transfer.stockv2 else "Unknown",
                "unit_price": transfer.stockv2.unitPrice if transfer.stockv2 else 0,
                "transfer_date": transfer.transfer_date.isoformat() if transfer.transfer_date else None
            })

        return make_response(jsonify(transfers_data), 200)



# class ShopToShopTransferList(Resource):
#     @jwt_required()
#     def get(self):
#         status = request.args.get("status", None)
#         to_shop_id = request.args.get("to_shop_id", None)

#         query = db.session.query(
#             func.min(Shoptoshoptransfer.transfer_id).label("transfer_id"),
#             Shoptoshoptransfer.itemname,
#             func.sum(Shoptoshoptransfer.quantity).label("total_quantity"),
#             Shoptoshoptransfer.metric,
#             Shoptoshoptransfer.from_shop_id,
#             Shoptoshoptransfer.to_shop_id,
#             Shoptoshoptransfer.status,
#             func.min(Shoptoshoptransfer.transfer_date).label("transfer_date"),
#             func.group_concat(Shoptoshoptransfer.decline_note.op('SEPARATOR')(', ')).label("decline_notes"),  # ✅ MySQL
#             Shops.shopname.label("from_shop_name"),
#             Users.username.label("user")
#         ).join(
#             Shops, Shoptoshoptransfer.from_shop_id == Shops.shops_id
#         ).join(
#             Users, Shoptoshoptransfer.users_id == Users.users_id
#         )

#         if status:
#             query = query.filter(Shoptoshoptransfer.status == status)
#         if to_shop_id:
#             query = query.filter(Shoptoshoptransfer.to_shop_id == to_shop_id)

#         query = query.group_by(
#             Shoptoshoptransfer.itemname,
#             Shoptoshoptransfer.metric,
#             Shoptoshoptransfer.from_shop_id,
#             Shoptoshoptransfer.to_shop_id,
#             Shoptoshoptransfer.status,
#             Shops.shopname,
#             Users.username
#         ).order_by(func.min(Shoptoshoptransfer.transfer_date).asc())

#         results = query.all()

#         transfers = []
#         for row in results:
#             transfers.append({
#                 "id": row.transfer_id,
#                 "itemname": row.itemname,
#                 "quantity": row.total_quantity,
#                 "metric": row.metric,
#                 "from_shop_id": row.from_shop_id,
#                 "to_shop_id": row.to_shop_id,
#                 "status": row.status,
#                 "transfer_date": row.transfer_date.strftime("%Y-%m-%d %H:%M:%S"),
#                 "decline_note": row.decline_notes,
#                 "from_shop_name": row.from_shop_name,
#                 "user": row.user
#             })

#         return transfers, 200
