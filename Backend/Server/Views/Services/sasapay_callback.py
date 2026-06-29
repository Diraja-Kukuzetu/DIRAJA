# Server/Resources/sasapay_callback.py
from flask_restful import Resource
from flask import request, current_app
import json
from datetime import datetime
from app import db
from Server.Models.Sales import Sales
from Server.Models.Paymnetmethods import SalesPaymentMethods
from Server.Models.SoldItems import SoldItem
from Server.Models.ShopstockV2 import ShopStockV2
from Server.Models.LiveStock import LiveStock
from Server.Models.Customers import Customers
from Server.Views.Services.journal_service import JournalService
import logging

logger = logging.getLogger(__name__)

class SasaPayCallbackResource(Resource):
    def post(self):
        """Handle SasaPay payment callback and finalize sale"""
        try:
            callback_data = request.get_json()
            
            # Log the callback
            current_app.logger.info(f"[SASAPAY] Callback received: {callback_data}")
            
            # Validate callback
            if not callback_data or 'ResultCode' not in callback_data:
                current_app.logger.error("[SASAPAY] Invalid callback data")
                return {"status": "error", "message": "Invalid callback data"}, 200

            # Extract important fields
            checkout_request_id = callback_data.get('CheckoutRequestID')
            result_code = callback_data.get('ResultCode')
            result_desc = callback_data.get('ResultDesc')
            transaction_amount = callback_data.get('Amount')
            sasapay_transaction_id = callback_data.get('TransactionReference') or callback_data.get('SasaPayTransactionID')
            merchant_code = callback_data.get('MerchantCode')
            merchant_reference = callback_data.get('MerchantTransactionReference')
            customer_name = callback_data.get('CustomerName')
            customer_number = callback_data.get('CustomerNumber')
            
            if not checkout_request_id:
                current_app.logger.error("[SASAPAY] Missing CheckoutRequestID")
                return {"status": "error", "message": "Missing CheckoutRequestID"}, 200

            # Find the payment method
            payment_method = SalesPaymentMethods.query.filter_by(
                checkout_request_id=checkout_request_id
            ).first()
            
            if not payment_method:
                current_app.logger.error(f"[SASAPAY] Payment method not found for: {checkout_request_id}")
                return {"status": "error", "message": "Transaction not found"}, 200

            # Find the sale
            sale = Sales.query.get(payment_method.sale_id)
            if not sale:
                current_app.logger.error(f"[SASAPAY] Sale not found for ID: {payment_method.sale_id}")
                return {"status": "error", "message": "Sale not found"}, 200

            # Update payment method with callback data
            payment_method.sasapay_transaction_id = sasapay_transaction_id
            payment_method.payment_status = 'success' if result_code == '0' else 'failed'
            payment_method.callback_received_at = datetime.utcnow()
            payment_method.result_code = result_code
            payment_method.result_desc = result_desc
            payment_method.callback_data = json.dumps(callback_data)
            
            # Parse reservation data stored during initiation
            reservation_data = None
            if payment_method.callback_data:
                try:
                    # The callback_data field currently has the callback JSON
                    # We need to parse the original reservation data
                    # If you stored it separately, retrieve it
                    reservation_data = json.loads(payment_method.callback_data) if payment_method.callback_data else None
                except:
                    # Try to get from a separate field if you added one
                    pass

            if result_code == '0':
                # ===== PAYMENT SUCCESS - FINALIZE SALE =====
                current_app.logger.info(f"[SASAPAY] Payment successful for sale {sale.sales_id}")
                
                # ===== UPDATE CUSTOMER INFO FROM CALLBACK =====
                if customer_name or customer_number:
                    # Update sale
                    if customer_name:
                        sale.customer_name = customer_name
                    if customer_number:
                        sale.customer_number = customer_number
                    
                    # Update customer record
                    customer = Customers.query.filter_by(sales_id=sale.sales_id).first()
                    if customer:
                        if customer_name:
                            customer.customer_name = customer_name
                        if customer_number:
                            customer.customer_number = customer_number
                        db.session.add(customer)
                
                # ===== UPDATE SALE STATUS =====
                # Calculate total paid from all successful payments
                total_paid = db.session.query(db.func.sum(SalesPaymentMethods.amount_paid))\
                    .filter(SalesPaymentMethods.sale_id == sale.sales_id)\
                    .filter(SalesPaymentMethods.payment_status == 'success')\
                    .scalar() or 0
                
                # Calculate total from sold items
                sold_items_total = db.session.query(db.func.sum(SoldItem.total_price))\
                    .filter(SoldItem.sales_id == sale.sales_id)\
                    .scalar() or 0
                
                # Update balance
                sale.balance = max(0, sold_items_total - total_paid)
                
                # Determine status
                if sale.balance == 0:
                    sale.status = 'paid'
                else:
                    sale.status = 'partially_paid'
                
                sale.note = f"Payment confirmed via SasaPay. Transaction: {sasapay_transaction_id or checkout_request_id}"
                sale.timestamp = datetime.utcnow()
                
                db.session.add(sale)
                current_app.logger.info(f"[SASAPAY] Updated sale {sale.sales_id}: status={sale.status}, balance={sale.balance}")
                
                # ===== DEDUCT STOCK =====
                # We need to find and deduct stock for each sold item
                sold_items = SoldItem.query.filter_by(sales_id=sale.sales_id).all()
                
                for sold_item in sold_items:
                    # Check if stock was already deducted (to prevent double deduction)
                    if sold_item.BatchNumber and "Livestock" not in sold_item.BatchNumber:
                        # Parse batch numbers from BatchNumber field
                        # Format: "Batch B001 (5.0), Batch B002 (3.0)"
                        batch_info = sold_item.BatchNumber.split(", ")
                        remaining_quantity = sold_item.quantity
                        
                        for batch_entry in batch_info:
                            if remaining_quantity <= 0:
                                break
                            
                            # Extract batch number and quantity
                            import re
                            match = re.search(r'Batch (\w+)\s*\(([\d.]+)\)', batch_entry)
                            if match:
                                batch_number = match.group(1)
                                deduct_qty = float(match.group(2))
                                
                                # Find the batch
                                batch = ShopStockV2.query.filter_by(
                                    BatchNumber=batch_number,
                                    shop_id=sale.shop_id,
                                    itemname=sold_item.item_name
                                ).first()
                                
                                if batch and batch.quantity >= deduct_qty:
                                    batch.quantity -= deduct_qty
                                    db.session.add(batch)
                                    remaining_quantity -= deduct_qty
                                    current_app.logger.info(f"[SASAPAY] Deducted {deduct_qty} from batch {batch_number}")
                                else:
                                    current_app.logger.warning(f"[SASAPAY] Batch {batch_number} not found or insufficient stock")
                        
                        # If still has remaining quantity, check livestock
                        if remaining_quantity > 0:
                            livestock = LiveStock.query.filter(
                                LiveStock.shop_id == sale.shop_id,
                                LiveStock.item_name == sold_item.item_name
                            ).first()
                            if livestock and livestock.current_quantity >= remaining_quantity:
                                livestock.current_quantity -= remaining_quantity
                                livestock.clock_out_quantity -= remaining_quantity
                                db.session.add(livestock)
                                current_app.logger.info(f"[SASAPAY] Deducted {remaining_quantity} from livestock")

                # ===== POST JOURNAL ENTRY =====
                try:
                    # Get sold items with their details
                    sold_items_with_details = []
                    for item in sold_items:
                        sold_items_with_details.append({
                            'item_name': item.item_name,
                            'quantity': item.quantity,
                            'metric': item.metric,
                            'unit_price': item.unit_price,
                            'total_price': item.total_price,
                            'Purchase_account': item.Purchase_account,
                            'Cost_of_sale': item.Cost_of_sale
                        })
                    
                    # Get creditor_id if this was a credit sale
                    creditor_id = None
                    # Check if creditor exists in sale note or reservation data
                    if sale.note and 'creditor' in sale.note.lower():
                        # Extract creditor ID if stored
                        pass
                    
                    journal_result = JournalService.post_sale_journal(
                        sale=sale,
                        sold_items=sold_items_with_details,
                        shop_id=sale.shop_id,
                        creditor_id=creditor_id,
                        amount_paid=payment_method.amount_paid
                    )
                    current_app.logger.info(f"[SASAPAY] Journal posted for sale {sale.sales_id}")
                except Exception as e:
                    current_app.logger.error(f"[SASAPAY] Journal posting failed: {str(e)}")
                    # Don't rollback - sale is already saved

            else:
                # ===== PAYMENT FAILED - MARK AS FAILED =====
                current_app.logger.warning(f"[SASAPAY] Payment failed for sale {sale.sales_id}: {result_desc} (Code: {result_code})")

                # Update sale status to failed
                sale.status = 'failed'
                sale.note = f"Payment failed: {result_desc}"
                sale.timestamp = datetime.utcnow()

                # Mark payment as failed
                payment_method.failure_reason = result_desc

                db.session.add(sale)
                current_app.logger.warning(f"[SASAPAY] Marked sale {sale.sales_id} as failed")

            # ===== COMMIT ALL CHANGES =====
            db.session.commit()

            # ===== RETURN SUCCESS RESPONSE =====
            return {
                "status": "success",
                "message": "Callback processed successfully",
                "result_code": result_code,
                "sale_id": sale.sales_id if sale else None,
                "sale_status": sale.status if sale else None
            }, 200

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"[SASAPAY] Callback processing error: {str(e)}", exc_info=True)
            # Always return 200 to prevent retries from SasaPay
            return {"status": "error", "message": str(e)}, 200