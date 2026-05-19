# Server/Resources/sasapay_callback.py
from flask_restful import Resource
from flask import request, current_app
import json
from datetime import datetime
from app import db
from Server.Models.Sales import Sales
from Server.Models.Paymnetmethods import SalesPaymentMethods
from Server.Models.Transactions import TranscationType
from Server.Models.BankAccounts import BankAccount
import logging

logger = logging.getLogger(__name__)

class SasaPayCallbackResource(Resource):
    """Handle SasaPay STK push callback"""
    
    def post(self):
        """Receive payment confirmation from SasaPay"""
        try:
            # Get callback data
            callback_data = request.get_json()
            logger.info(f"Received SasaPay callback: {json.dumps(callback_data)}")
            
            # Extract relevant data (adjust based on actual SasaPay callback format)
            # This format may vary - adjust according to SasaPay documentation
            status = callback_data.get("statusCode") or callback_data.get("ResultCode")
            result_desc = callback_data.get("message") or callback_data.get("ResultDesc")
            transaction_reference = callback_data.get("TransactionReference") or callback_data.get("TransID")
            checkout_request_id = callback_data.get("CheckoutRequestID")
            amount = float(callback_data.get("Amount", 0))
            phone_number = callback_data.get("PhoneNumber")
            merchant_code = callback_data.get("MerchantCode")
            
            # Extract sale ID from transaction reference
            sale_id = None
            if transaction_reference:
                # Assuming format: SALE{sale_id}...
                sale_id_str = transaction_reference.replace("SALE", "").split()[0]
                try:
                    sale_id = int(''.join(filter(str.isdigit, sale_id_str)))
                except ValueError:
                    pass
            
            # If status is success (0 typically means success)
            # Adjust based on your SasaPay success indicator
            is_success = (status == "0" or status == "0" or status == 0)
            
            if is_success and sale_id:
                # Update the sale payment
                return self._process_successful_payment(
                    sale_id=sale_id,
                    amount=amount,
                    transaction_code=transaction_reference,
                    checkout_request_id=checkout_request_id,
                    phone_number=phone_number,
                    callback_data=callback_data
                )
            else:
                logger.warning(f"SasaPay payment failed: {result_desc}")
                return {
                    "success": False,
                    "message": "Payment not successful",
                    "result_desc": result_desc
                }, 200  # Always return 200 to SasaPay
                
        except Exception as e:
            logger.error(f"Error processing SasaPay callback: {str(e)}")
            # Always return 200 to avoid retries
            return {"success": False, "error": str(e)}, 200
    
    def _process_successful_payment(self, sale_id, amount, transaction_code, 
                                   checkout_request_id, phone_number, callback_data):
        """Process successful SasaPay payment"""
        try:
            # Find the sale
            sale = Sales.query.get(sale_id)
            if not sale:
                logger.error(f"Sale {sale_id} not found for SasaPay callback")
                return {"success": False, "message": "Sale not found"}, 200
            
            # Check if payment was already recorded
            existing_payment = SalesPaymentMethods.query.filter_by(
                sale_id=sale_id,
                payment_method='sasapay',
                transaction_code=transaction_code
            ).first()
            
            if existing_payment:
                logger.info(f"Payment {transaction_code} already processed for sale {sale_id}")
                return {"success": True, "message": "Payment already processed"}, 200
            
            # Get shop to bank mapping
            shop_to_bank_mapping = {
                1: 12, 2: 3, 3: 6, 4: 2, 5: 5, 6: 17,
                7: 15, 8: 9, 10: 18, 11: 8, 12: 7,
                14: 14, 16: 13, 19: 22
            }
            bank_id = shop_to_bank_mapping.get(sale.shop_id, 11)
            
            # Record payment
            payment_record = SalesPaymentMethods(
                sale_id=sale_id,
                payment_method='sasapay',
                amount_paid=amount,
                transaction_code=transaction_code,
                discount=0,
                created_at=datetime.utcnow(),
                metadata=json.dumps({
                    'checkout_request_id': checkout_request_id,
                    'phone_number': phone_number,
                    'callback_data': callback_data
                })
            )
            db.session.add(payment_record)
            
            # Update bank account
            bank_account = BankAccount.query.get(bank_id)
            if bank_account:
                previous_balance = bank_account.Account_Balance
                bank_account.Account_Balance += amount
                
                # Record transaction
                transaction = TranscationType(
                    Transaction_type="Debit",
                    Transaction_amount=amount,
                    From_account=f"SASAPAY Payment - Sale #{sale_id}",
                    To_account=bank_account.Account_name,
                    created_at=datetime.utcnow(),
                    transaction_code=transaction_code
                )
                db.session.add(transaction)
            
            # Update sale status
            total_paid = db.session.query(db.func.sum(SalesPaymentMethods.amount_paid))\
                .filter(SalesPaymentMethods.sale_id == sale_id).scalar() or 0
            
            sale.status = 'paid' if total_paid >= sale.total_amount else 'partially_paid'
            sale.balance = sale.total_amount - total_paid
            
            db.session.commit()
            
            logger.info(f"Successfully processed SasaPay payment {transaction_code} for sale {sale_id}")
            
            return {
                "success": True,
                "message": "Payment processed successfully",
                "sale_id": sale_id,
                "amount": amount,
                "transaction_code": transaction_code,
                "new_balance": sale.balance
            }, 200
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error processing payment for sale {sale_id}: {str(e)}")
            return {"success": False, "error": str(e)}, 200