
from app import db
import os
import json
from flask_restful import Resource
from Server.Models.Sales import Sales
from Server.Models.StockItems import StockItems
from Server.Models.LiveStock import LiveStock
from Server.Models.SoldItems import SoldItem
from Server.Models.Paymnetmethods import SalesPaymentMethods
from Server.Models.Users import Users
from Server.Models.Shops import Shops
from Server.Models.Expenses import Expenses
from Server.Models.Transactions import TranscationType
from Server.Models.BankAccounts import BankAccount
from Server.Models.Inventory import Inventory
from Server.Models.InventoryV2 import InventoryV2
from Server.Models.ShopstockV2 import ShopStockV2
from Server.Models.Customers import Customers
from Server.Utils import get_sales_filtered, serialize_sales
from flask import jsonify,request,make_response
from Server.Models.Shopstock import ShopStock
from sqlalchemy import func, or_
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text
from flask import jsonify, request, Response
from functools import wraps
from Server.Models.Creditors import Creditors
from datetime import datetime, timedelta
from Server.Models.Transactions import TranscationType
from Server.Models.BankAccounts import BankAccount
from Server.Models.CashDeposit import CashDeposits
from Server.Views.Utils.customer_utils import CustomerService
from flask import current_app
from fuzzywuzzy import process
import logging
from math import modf
import threading
from Server.Views.Services.sasapay_service import SasaPayPaymentService
from Server.Views.Services.journal_service import JournalService
from flask import send_file
from io import BytesIO
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from Server.Views.Sasapyaviews import SasaPayTransactionStatementResource

logger = logging.getLogger(__name__)

# class AddSale(Resource):
#     @jwt_required()
#     def post(self):
#         data = request.get_json()
#         current_user_id = get_jwt_identity()
#         new_sale = None

#         # ===== VALIDATION =====
#         required_fields = [
#             'shop_id', 'customer_name', 'customer_number',
#             'items', 'payment_methods', 'status', 'delivery'
#         ]
#         if not all(field in data for field in required_fields):
#             return {
#                 'message': 'Missing required fields',
#                 'missing': [f for f in required_fields if f not in data]
#             }, 400

#         try:
#             shop_id = int(data['shop_id'])
#             payment_methods = data['payment_methods']
#             promocode = data.get('promocode', '')
#             status = data['status'].lower()
#             balance = float(data.get('balance', 0))
#             delivery = bool(data.get('delivery', 0))
#             creditor_id = data.get('creditor_id')
#             register_for_loyalty = data.get('register_for_loyalty', False)
#             created_at = datetime.strptime(data['sale_date'], "%Y-%m-%d") if 'sale_date' in data else datetime.utcnow()

#             if not isinstance(data['items'], list) or not data['items']:
#                 return {'message': 'Items must be a non-empty list'}, 400

#             items = []
#             total_price = 0.0
#             total_quantity = 0.0
#             purchase_account = 0.0
#             etims_items_data = []

#             for item in data['items']:
#                 item_fields = ['item_name', 'quantity', 'metric', 'unit_price']
#                 if not all(field in item for field in item_fields):
#                     return {
#                         'message': 'Missing required item fields',
#                         'missing': [f for f in item_fields if f not in item]
#                     }, 400

#                 metric = item['metric'].strip().lower()
#                 if metric not in ['item', 'kg', 'ltrs']:
#                     return {
#                         'message': f"Invalid metric '{metric}' for item '{item['item_name']}'. Must be one of: item, kg, ltrs",
#                         'invalid_item': item
#                     }, 400

#                 stock_item = StockItems.query.filter_by(
#                     item_name=item['item_name']
#                 ).first()

#                 if not stock_item:
#                     logger.warning(f"Item '{item['item_name']}' not found in StockItems")
                
#                 etims_item_code = None
#                 if stock_item and stock_item.etims_synced:
#                     etims_item_code = stock_item.etims_item_code
#                     logger.info(f"✅ Found eTims code {etims_item_code} for '{item['item_name']}'")
#                 else:
#                     logger.warning(f"⚠️  No eTims code found for '{item['item_name']}'")

#                 is_service = False
#                 if stock_item:
#                     is_service = stock_item.stock_item_type == "Service"
#                     logger.info(f"Item '{item['item_name']}' is {'Service' if is_service else 'Product'}")

#                 item_data = {
#                     'item_name': item['item_name'],
#                     'quantity': float(item['quantity']),
#                     'metric': metric,
#                     'unit_price': float(item['unit_price']),
#                     'total_price': float(item['total_price']),
#                     'item_id': stock_item.id if stock_item else None,
#                     'etims_item_code': etims_item_code,
#                     'stock_item': stock_item,
#                     'is_service': is_service
#                 }
#                 items.append(item_data)
                
#                 etims_items_data.append({
#                     'item_name': item['item_name'],
#                     'quantity': float(item['quantity']),
#                     'metric': metric,
#                     'unit_price': float(item['unit_price']),
#                     'total_price': float(item['total_price']),
#                     'etims_item_code': etims_item_code,
#                     'item_id': stock_item.id if stock_item else None,
#                     'is_service': is_service
#                 })
                
#                 total_quantity += float(item['quantity'])
#                 total_price += float(item['total_price'])

#         except (ValueError, KeyError, TypeError) as e:
#             return {'message': f'Invalid data format: {str(e)}'}, 400

#         # ===== CREDITOR VALIDATION =====
#         creditor = None
#         if creditor_id:
#             try:
#                 creditor_id = int(creditor_id)
#                 creditor = Creditors.query.filter_by(id=creditor_id, shop_id=shop_id).first()
#                 if not creditor:
#                     return {'message': f'Creditor with ID {creditor_id} not found for this shop'}, 404
                
#                 if status not in ["unpaid", "partially_paid"]:
#                     return {'message': 'Creditor sales must have status "unpaid" or "partially paid"'}, 400
                    
#             except (ValueError, TypeError):
#                 return {'message': 'Invalid creditor ID format'}, 400

#         # ===== PAYMENT METHOD VALIDATION =====
#         if status != "unpaid":
#             if not isinstance(payment_methods, list):
#                 return {'message': 'Payment methods must be a list'}, 400

#             for pm in payment_methods:
#                 if 'method' not in pm or 'amount' not in pm:
#                     return {'message': 'Each payment method must have "method" and "amount"'}, 400
#                 try:
#                     float(pm['amount'])
#                 except ValueError:
#                     return {'message': f'Invalid amount for payment method {pm["method"]}'}, 400

#         # ===== STOCK PROCESSING =====
#         stock_processing_errors = []
#         batch_deductions = []
#         stock_ids_used = []
#         sold_items = []
#         livestock_deductions = []

#         try:
#             for item in items:
#                 if item.get('is_service', False):
#                     logger.info(f"⏭️ Skipping stock deduction for service item: {item['item_name']}")
                    
#                     sold_item = {
#                         'item_name': item['item_name'],
#                         'quantity': item['quantity'],
#                         'metric': item['metric'],
#                         'unit_price': item['unit_price'],
#                         'total_price': item['total_price'],
#                         'BatchNumber': "Service Item - No Stock Deduction",
#                         'stockv2_id': None,
#                         'item_id': item.get('item_id'),
#                         'etims_item_code': item.get('etims_item_code'),
#                         'Cost_of_sale': item['total_price'],
#                         'Purchase_account': 0.0,
#                         'LivestockDeduction': 0.0,
#                         'is_service': True
#                     }
#                     sold_items.append(sold_item)
                    
#                     batch_deductions.append({
#                         'item_name': item['item_name'],
#                         'item_id': item.get('item_id'),
#                         'etims_item_code': item.get('etims_item_code'),
#                         'deductions': [("Service Item", 0)],
#                         'is_service': True
#                     })
                    
#                     continue

#                 batches = ShopStockV2.query.filter(
#                     ShopStockV2.itemname == item['item_name'],
#                     ShopStockV2.shop_id == shop_id,
#                     ShopStockV2.quantity > 0
#                 ).order_by(ShopStockV2.BatchNumber).all()

#                 remaining_qty = item['quantity']
#                 item_batch_deductions = []
#                 item_stock_ids = []
#                 item_purchase_account = 0.0
#                 item_livestock_deduction = 0.0

#                 for batch in batches:
#                     if remaining_qty <= 0:
#                         break

#                     deduct_qty = min(batch.quantity, remaining_qty)
#                     batch.quantity -= deduct_qty
#                     remaining_qty -= deduct_qty
#                     item_batch_deductions.append((batch.BatchNumber, deduct_qty))
#                     item_stock_ids.append(str(batch.stockv2_id))

#                     inventory = InventoryV2.query.filter_by(inventoryV2_id=batch.inventoryv2_id).first()
#                     if inventory:
#                         item_purchase_account += inventory.unitCost * deduct_qty

#                     db.session.add(batch)

#                 if remaining_qty > 0:
#                     livestock_entry = LiveStock.query.filter(
#                         LiveStock.shop_id == shop_id,
#                         func.lower(LiveStock.item_name) == item['item_name'].lower()
#                     ).first()

#                     if livestock_entry:
#                         if livestock_entry.current_quantity > 0:
#                             deduct_qty = min(livestock_entry.current_quantity, remaining_qty)
#                             livestock_entry.current_quantity -= deduct_qty
#                             livestock_entry.clock_out_quantity -= deduct_qty
#                             remaining_qty -= deduct_qty
#                             item_livestock_deduction = deduct_qty
#                             db.session.add(livestock_entry)
#                             livestock_deductions.append({
#                                 'item_name': item['item_name'],
#                                 'quantity': deduct_qty,
#                                 'original_current': livestock_entry.current_quantity + deduct_qty,
#                                 'new_current': livestock_entry.current_quantity
#                             })

#                 if remaining_qty > 0:
#                     stock_processing_errors.append(
#                         f"Insufficient stock for {item['item_name']}. Needed {item['quantity']}, available {item['quantity'] - remaining_qty}"
#                     )
#                     continue

#                 if item_batch_deductions:
#                     batch_deductions.append({
#                         'item_name': item['item_name'],
#                         'item_id': item.get('item_id'),
#                         'etims_item_code': item.get('etims_item_code'),
#                         'deductions': item_batch_deductions,
#                         'is_service': False
#                     })
#                     stock_ids_used.extend(item_stock_ids)

#                 purchase_account += item_purchase_account

#                 sold_item = {
#                     'item_name': item['item_name'],
#                     'quantity': item['quantity'],
#                     'metric': item['metric'],
#                     'unit_price': item['unit_price'],
#                     'total_price': item['total_price'],
#                     'BatchNumber': ", ".join(f"{bn} ({q})" for bn, q in item_batch_deductions) if item_batch_deductions else "From Livestock",
#                     'stockv2_id': item_stock_ids[0] if item_stock_ids else None,
#                     'item_id': item.get('item_id'),
#                     'etims_item_code': item.get('etims_item_code'),
#                     'Cost_of_sale': item['total_price'],
#                     'Purchase_account': item_purchase_account,
#                     'LivestockDeduction': item_livestock_deduction,
#                     'is_service': False
#                 }
#                 sold_items.append(sold_item)

#             if stock_processing_errors:
#                 db.session.rollback()
#                 return {'message': 'Stock processing failed', 'errors': stock_processing_errors}, 400

#         except Exception as e:
#             db.session.rollback()
#             return {'message': 'Stock processing failed', 'error': str(e)}, 500

#         # ===== PAYMENT PROCESSING =====
#         total_amount_paid = sum(float(pm['amount']) for pm in payment_methods) if status != "unpaid" else 0
        
#         total_sale_amount = sum(float(item['total_price']) for item in sold_items)
        
#         auto_discount_applied = False
#         if balance > 0 and status == "paid":
#             balance_percentage = (balance / total_sale_amount) * 100
#             if balance_percentage <= 3.0:
#                 has_discount = any(pm.get('discount', 0) > 0 for pm in payment_methods)
#                 if not has_discount and len(payment_methods) == 1:
#                     payment_methods[0]['discount'] = balance
#                     auto_discount_applied = True
#                     balance = 0

#         try:
#             # ===== CREATE LOCAL SALE =====
#             new_sale = Sales(
#                 user_id=current_user_id,
#                 shop_id=shop_id,
#                 customer_name=data['customer_name'],
#                 customer_number=data['customer_number'],
#                 status=status,
#                 delivery=delivery,
#                 created_at=created_at,
#                 balance=balance,
#                 promocode=promocode,
#             )
#             db.session.add(new_sale)
#             db.session.flush()

#             # ===== CREDITOR BALANCE UPDATE =====
#             if creditor:
#                 creditor.total_credit = (creditor.total_credit or 0) + total_sale_amount
#                 creditor.credit_amount = (creditor.credit_amount or 0) + total_sale_amount
#                 db.session.add(creditor)

#             # ===== CREATE SOLD ITEMS WITH REFERENCES =====
#             for item in sold_items:
#                 total_price = float(item['total_price'])
#                 fractional_part = round(total_price - int(total_price), 2)

#                 sold_item = SoldItem(
#                     sales_id=new_sale.sales_id,
#                     item_name=item['item_name'],
#                     quantity=item['quantity'],
#                     metric=item['metric'],
#                     unit_price=item['unit_price'],
#                     total_price=total_price,
#                     BatchNumber=item['BatchNumber'],
#                     stockv2_id=item.get('stockv2_id'),
#                     item_id=item.get('item_id'),
#                     etims_item_code=item.get('etims_item_code'),
#                     Cost_of_sale=item['Cost_of_sale'],
#                     Purchase_account=item.get('Purchase_account', 0.0),
#                     LivestockDeduction=item.get('LivestockDeduction', 0.0),
#                     round_off=fractional_part,
#                     is_service=item.get('is_service', False)
#                 )
#                 db.session.add(sold_item)

#             # ===== PAYMENT METHODS =====
#             for payment in payment_methods:
#                 method = payment['method'].strip().lower()
#                 amount = float(payment['amount'])
#                 transaction_code = payment.get('transaction_code', 'N/A').strip().upper()
                
#                 discount = 0
#                 if 'discount' in payment:
#                     try:
#                         discount = float(payment['discount'])
#                     except (ValueError, TypeError):
#                         discount = 0

#                 db.session.add(SalesPaymentMethods(
#                     sale_id=new_sale.sales_id,
#                     payment_method=method,
#                     amount_paid=amount,
#                     transaction_code=transaction_code,
#                     discount=discount,
#                     created_at=created_at
#                 ))

#             # ===== CUSTOMER RECORD - USING CUSTOMER SERVICE =====
#             customer_result = None
#             if data['customer_name'] or data['customer_number']:
#                 try:
#                     customer_result = CustomerService.add_or_update_customer(
#                         customer_name=data['customer_name'],
#                         customer_number=data['customer_number'],
#                         shop_id=shop_id,
#                         sales_id=new_sale.sales_id,
#                         user_id=current_user_id,
#                         items=[item['item_name'] for item in items],
#                         amount_paid=total_amount_paid,
#                         payment_method=", ".join(pm['method'] for pm in payment_methods),
#                         created_at=created_at,
#                         register_for_loyalty=register_for_loyalty
#                     )
                    
#                     logger.info(f"Customer processed: {customer_result['action']}, points earned: {customer_result['points_earned']}")
                    
#                 except Exception as e:
#                     logger.error(f"Failed to process customer: {str(e)}")
#                     # Continue with sale even if customer processing fails
#                     customer_result = None

#             # ===== COMMIT ALL TRANSACTIONS =====
#             db.session.commit()
#             logger.info(f"Sale {new_sale.sales_id} committed successfully with customer data")

#             # ===== JOURNAL POSTING =====
#             try:
#                 journal_result = JournalService.post_sale_journal(
#                     sale=new_sale,
#                     sold_items=sold_items,
#                     shop_id=shop_id,
#                     creditor_id=creditor_id,
#                     amount_paid=total_amount_paid
#                 )
#                 db.session.commit()
#                 logger.info(f"Journal posted successfully for sale {new_sale.sales_id}")
#             except Exception as e:
#                 logger.error(f"Journal posting failed: {str(e)}")
#                 # Don't rollback here - sale is already committed
#                 # Log the error but continue
#                 pass

#             # ===== BUILD RESPONSE (without eTims yet) =====
#             response_data = {
#                 'message': 'Sale processed successfully',
#                 'sale_id': new_sale.sales_id,
#                 'financial': {
#                     'total': total_price,
#                     'paid': total_amount_paid,
#                     'balance': balance,
#                     'purchase_cost': purchase_account
#                 },
#                 'items': {
#                     'count': len(items),
#                     'details': sold_items
#                 },
#                 'stock_deductions': {
#                     'shop_stock': batch_deductions,
#                     'livestock': livestock_deductions
#                 },
#                 'payments': {
#                     'methods': [pm['method'] for pm in payment_methods],
#                     'discounts_applied': [{'method': pm['method'], 'discount': float(pm.get('discount', 0))} for pm in payment_methods]
#                 },
#                 'delivery': delivery,
#                 'customer': None,
#                 'etims': None
#             }

#             # Add customer information to response
#             if customer_result:
#                 response_data['customer'] = {
#                     'customer_id': customer_result['customer'].customer_id,
#                     'customer_name': customer_result['customer'].customer_name,
#                     'is_new_customer': customer_result['is_new'],
#                     'action': customer_result['action'],
#                     'points_earned': customer_result['points_earned'],
#                     'loyalty_points': customer_result['customer'].loyalty_points or 0,
#                     'loyalty_tier': customer_result['customer'].loyalty_tier or 'Bronze',
#                     'is_loyalty_registered': customer_result['customer'].is_loyalty_registered or False
#                 }

#             # Add auto-discount notification if applied
#             if auto_discount_applied:
#                 response_data['auto_discount'] = {
#                     'applied': True,
#                     'amount': balance,
#                     'reason': f'Balance of {balance} ({balance_percentage:.2f}% of total) was within 3% threshold and converted to discount'
#                 }

#             # Add creditor information to response if applicable
#             if creditor:
#                 response_data['creditor'] = {
#                     'creditor_id': creditor.id,
#                     'creditor_name': creditor.name,
#                     'previous_total_credit': creditor.total_credit - total_sale_amount,
#                     'new_total_credit': creditor.total_credit,
#                     'previous_credit_amount': creditor.credit_amount - total_sale_amount,
#                     'new_credit_amount': creditor.credit_amount
#                 }

#             # ===== CREATE ETIMS SALE RECORD (LAST - AFTER EVERYTHING ELSE) =====
#             etims_success = False
#             etims_result = None
            
#             try:
#                 # Check if all items have eTims codes
#                 has_etims_codes = all(item.get('etims_item_code') for item in etims_items_data)
                
#                 if has_etims_codes:
#                     etims_sale_data = {
#                         'items': etims_items_data,
#                         'customer_name': data['customer_name'],
#                         'customer_number': data['customer_number'],
#                         'sale_date': data.get('sale_date'),
#                         'payment_methods': payment_methods,
#                         'shop_id': shop_id
#                     }
                    
#                     # Create eTims record in a separate transaction
#                     etims_success, etims_result = etims_sale_service.create_etims_sale_from_sale(
#                         etims_sale_data,
#                         new_sale.sales_id,
#                         shop_id
#                     )
                    
#                     if etims_success:
#                         logger.info(f"✅ eTims sale record created: {etims_result.get('etims_sale', {}).get('trader_invoice_no')}")
#                     else:
#                         logger.warning(f"⚠️  Failed to create eTims sale record: {etims_result.get('error') if etims_result else 'Unknown error'}")
#                 else:
#                     missing_etims_items = [item['item_name'] for item in etims_items_data if not item.get('etims_item_code')]
#                     logger.warning(f"⚠️  Skipping eTims record - missing eTims codes for: {missing_etims_items}")
#                     etims_result = {
#                         'error': f'Missing eTims codes for: {", ".join(missing_etims_items)}',
#                         'skipped': True
#                     }
                    
#             except Exception as e:
#                 logger.error(f"Error creating eTims sale record: {str(e)}")
#                 etims_result = {'error': str(e), 'skipped': True}

#             # Add eTims info to response
#             response_data['etims'] = {
#                 'record_created': etims_success,
#                 'status': 'pending' if etims_success else 'skipped',
#                 'trader_invoice_no': etims_result.get('etims_sale', {}).get('trader_invoice_no') if etims_success else None,
#                 'message': etims_result.get('message', 'Sale will be published during bulk sync') if etims_success else etims_result.get('error', 'No eTims record created')
#             }

#             return response_data, 201

#         except Exception as e:
#             db.session.rollback()
#             logger.error(f"Transaction failed: {str(e)}")
#             return {
#                 'message': 'Transaction failed',
#                 'error': str(e),
#                 'debug_info': {
#                     'sale_id': new_sale.sales_id if new_sale else "Not created",
#                     'processed_payments': [pm['method'] for pm in payment_methods] if payment_methods else [],
#                     'delivery': delivery,
#                     'creditor_id': creditor_id,
#                     'auto_discount_applied': auto_discount_applied
#                 }
#             }, 500

class AddSale(Resource):
    @jwt_required()
    def post(self):
        data = request.get_json()
        current_user_id = get_jwt_identity()
        new_sale = None

        # ===== VALIDATION =====
        required_fields = [
            'shop_id', 'customer_name', 'customer_number',
            'items', 'payment_methods', 'status', 'delivery'
        ]
        if not all(field in data for field in required_fields):
            return {
                'message': 'Missing required fields',
                'missing': [f for f in required_fields if f not in data]
            }, 400

        try:
            shop_id = int(data['shop_id'])
            payment_methods = data['payment_methods']
            promocode = data.get('promocode', '')
            status = data['status'].lower()
            balance = float(data.get('balance', 0))
            delivery = bool(data.get('delivery', 0))
            creditor_id = data.get('creditor_id')
            register_for_loyalty = data.get('register_for_loyalty', False)
            created_at = datetime.strptime(data['sale_date'], "%Y-%m-%d") if 'sale_date' in data else datetime.utcnow()

            if not isinstance(data['items'], list) or not data['items']:
                return {'message': 'Items must be a non-empty list'}, 400

            items = []
            total_price = 0.0
            total_quantity = 0.0
            purchase_account = 0.0

            for item in data['items']:
                item_fields = ['item_name', 'quantity', 'metric', 'unit_price']
                if not all(field in item for field in item_fields):
                    return {
                        'message': 'Missing required item fields',
                        'missing': [f for f in item_fields if f not in item]
                    }, 400

                metric = item['metric'].strip().lower()
                if metric not in ['item', 'kg', 'ltrs']:
                    return {
                        'message': f"Invalid metric '{metric}' for item '{item['item_name']}'. Must be one of: item, kg, ltrs",
                        'invalid_item': item
                    }, 400

                stock_item = StockItems.query.filter_by(
                    item_name=item['item_name']
                ).first()

                if not stock_item:
                    logger.warning(f"Item '{item['item_name']}' not found in StockItems")

                is_service = False
                if stock_item:
                    is_service = stock_item.stock_item_type == "Service"
                    logger.info(f"Item '{item['item_name']}' is {'Service' if is_service else 'Product'}")

                item_data = {
                    'item_name': item['item_name'],
                    'quantity': float(item['quantity']),
                    'metric': metric,
                    'unit_price': float(item['unit_price']),
                    'total_price': float(item['total_price']),
                    'item_id': stock_item.id if stock_item else None,
                    'stock_item': stock_item,
                    'is_service': is_service
                }
                items.append(item_data)
                
                total_quantity += float(item['quantity'])
                total_price += float(item['total_price'])

        except (ValueError, KeyError, TypeError) as e:
            return {'message': f'Invalid data format: {str(e)}'}, 400

        # ===== CREDITOR VALIDATION =====
        creditor = None
        if creditor_id:
            try:
                creditor_id = int(creditor_id)
                creditor = Creditors.query.filter_by(id=creditor_id, shop_id=shop_id).first()
                if not creditor:
                    return {'message': f'Creditor with ID {creditor_id} not found for this shop'}, 404
                
                if status not in ["unpaid", "partially_paid"]:
                    return {'message': 'Creditor sales must have status "unpaid" or "partially paid"'}, 400
                    
            except (ValueError, TypeError):
                return {'message': 'Invalid creditor ID format'}, 400

        # ===== PAYMENT METHOD VALIDATION =====
        if status != "unpaid":
            if not isinstance(payment_methods, list):
                return {'message': 'Payment methods must be a list'}, 400

            for pm in payment_methods:
                if 'method' not in pm or 'amount' not in pm:
                    return {'message': 'Each payment method must have "method" and "amount"'}, 400
                try:
                    float(pm['amount'])
                except ValueError:
                    return {'message': f'Invalid amount for payment method {pm["method"]}'}, 400

        # ===== STOCK PROCESSING =====
        stock_processing_errors = []
        batch_deductions = []
        stock_ids_used = []
        sold_items = []
        livestock_deductions = []

        try:
            for item in items:
                if item.get('is_service', False):
                    logger.info(f"⏭️ Skipping stock deduction for service item: {item['item_name']}")
                    
                    sold_item = {
                        'item_name': item['item_name'],
                        'quantity': item['quantity'],
                        'metric': item['metric'],
                        'unit_price': item['unit_price'],
                        'total_price': item['total_price'],
                        'BatchNumber': "Service Item - No Stock Deduction",
                        'stockv2_id': None,
                        'item_id': item.get('item_id'),
                        'Cost_of_sale': item['total_price'],
                        'Purchase_account': 0.0,
                        'LivestockDeduction': 0.0,
                        'is_service': True
                    }
                    sold_items.append(sold_item)
                    
                    batch_deductions.append({
                        'item_name': item['item_name'],
                        'item_id': item.get('item_id'),
                        'deductions': [("Service Item", 0)],
                        'is_service': True
                    })
                    
                    continue

                batches = ShopStockV2.query.filter(
                    ShopStockV2.itemname == item['item_name'],
                    ShopStockV2.shop_id == shop_id,
                    ShopStockV2.quantity > 0
                ).order_by(ShopStockV2.BatchNumber).all()

                remaining_qty = item['quantity']
                item_batch_deductions = []
                item_stock_ids = []
                item_purchase_account = 0.0
                item_livestock_deduction = 0.0

                for batch in batches:
                    if remaining_qty <= 0:
                        break

                    deduct_qty = min(batch.quantity, remaining_qty)
                    batch.quantity -= deduct_qty
                    remaining_qty -= deduct_qty
                    item_batch_deductions.append((batch.BatchNumber, deduct_qty))
                    item_stock_ids.append(str(batch.stockv2_id))

                    inventory = InventoryV2.query.filter_by(inventoryV2_id=batch.inventoryv2_id).first()
                    if inventory:
                        item_purchase_account += inventory.unitCost * deduct_qty

                    db.session.add(batch)

                if remaining_qty > 0:
                    livestock_entry = LiveStock.query.filter(
                        LiveStock.shop_id == shop_id,
                        func.lower(LiveStock.item_name) == item['item_name'].lower()
                    ).first()

                    if livestock_entry:
                        if livestock_entry.current_quantity > 0:
                            deduct_qty = min(livestock_entry.current_quantity, remaining_qty)
                            livestock_entry.current_quantity -= deduct_qty
                            livestock_entry.clock_out_quantity -= deduct_qty
                            remaining_qty -= deduct_qty
                            item_livestock_deduction = deduct_qty
                            db.session.add(livestock_entry)
                            livestock_deductions.append({
                                'item_name': item['item_name'],
                                'quantity': deduct_qty,
                                'original_current': livestock_entry.current_quantity + deduct_qty,
                                'new_current': livestock_entry.current_quantity
                            })

                if remaining_qty > 0:
                    stock_processing_errors.append(
                        f"Insufficient stock for {item['item_name']}. Needed {item['quantity']}, available {item['quantity'] - remaining_qty}"
                    )
                    continue

                if item_batch_deductions:
                    batch_deductions.append({
                        'item_name': item['item_name'],
                        'item_id': item.get('item_id'),
                        'deductions': item_batch_deductions,
                        'is_service': False
                    })
                    stock_ids_used.extend(item_stock_ids)

                purchase_account += item_purchase_account

                sold_item = {
                    'item_name': item['item_name'],
                    'quantity': item['quantity'],
                    'metric': item['metric'],
                    'unit_price': item['unit_price'],
                    'total_price': item['total_price'],
                    'BatchNumber': ", ".join(f"{bn} ({q})" for bn, q in item_batch_deductions) if item_batch_deductions else "From Livestock",
                    'stockv2_id': item_stock_ids[0] if item_stock_ids else None,
                    'item_id': item.get('item_id'),
                    'Cost_of_sale': item['total_price'],
                    'Purchase_account': item_purchase_account,
                    'LivestockDeduction': item_livestock_deduction,
                    'is_service': False
                }
                sold_items.append(sold_item)

            if stock_processing_errors:
                db.session.rollback()
                return {'message': 'Stock processing failed', 'errors': stock_processing_errors}, 400

        except Exception as e:
            db.session.rollback()
            return {'message': 'Stock processing failed', 'error': str(e)}, 500

        # ===== PAYMENT PROCESSING =====
        total_amount_paid = sum(float(pm['amount']) for pm in payment_methods) if status != "unpaid" else 0
        
        total_sale_amount = sum(float(item['total_price']) for item in sold_items)
        
        auto_discount_applied = False
        if balance > 0 and status == "paid":
            balance_percentage = (balance / total_sale_amount) * 100
            if balance_percentage <= 3.0:
                has_discount = any(pm.get('discount', 0) > 0 for pm in payment_methods)
                if not has_discount and len(payment_methods) == 1:
                    payment_methods[0]['discount'] = balance
                    auto_discount_applied = True
                    balance = 0

        try:
            # ===== CREATE LOCAL SALE =====
            new_sale = Sales(
                user_id=current_user_id,
                shop_id=shop_id,
                customer_name=data['customer_name'],
                customer_number=data['customer_number'],
                status=status,
                delivery=delivery,
                created_at=created_at,
                balance=balance,
                promocode=promocode,
            )
            db.session.add(new_sale)
            db.session.flush()

            # ===== CREDITOR BALANCE UPDATE =====
            if creditor:
                creditor.total_credit = (creditor.total_credit or 0) + total_sale_amount
                creditor.credit_amount = (creditor.credit_amount or 0) + total_sale_amount
                db.session.add(creditor)

            # ===== CREATE SOLD ITEMS WITH REFERENCES =====
            for item in sold_items:
                total_price = float(item['total_price'])
                fractional_part = round(total_price - int(total_price), 2)

                sold_item = SoldItem(
                    sales_id=new_sale.sales_id,
                    item_name=item['item_name'],
                    quantity=item['quantity'],
                    metric=item['metric'],
                    unit_price=item['unit_price'],
                    total_price=total_price,
                    BatchNumber=item['BatchNumber'],
                    stockv2_id=item.get('stockv2_id'),
                    item_id=item.get('item_id'),
                    Cost_of_sale=item['Cost_of_sale'],
                    Purchase_account=item.get('Purchase_account', 0.0),
                    LivestockDeduction=item.get('LivestockDeduction', 0.0),
                    round_off=fractional_part,
                    is_service=item.get('is_service', False)
                )
                db.session.add(sold_item)

            # ===== PAYMENT METHODS =====
            for payment in payment_methods:
                method = payment['method'].strip().lower()
                amount = float(payment['amount'])
                transaction_code = payment.get('transaction_code', 'N/A').strip().upper()
                
                discount = 0
                if 'discount' in payment:
                    try:
                        discount = float(payment['discount'])
                    except (ValueError, TypeError):
                        discount = 0

                db.session.add(SalesPaymentMethods(
                    sale_id=new_sale.sales_id,
                    payment_method=method,
                    amount_paid=amount,
                    transaction_code=transaction_code,
                    discount=discount,
                    created_at=created_at
                ))

            # ===== CUSTOMER RECORD - USING CUSTOMER SERVICE =====
            customer_result = None
            if data['customer_name'] or data['customer_number']:
                try:
                    customer_result = CustomerService.add_or_update_customer(
                        customer_name=data['customer_name'],
                        customer_number=data['customer_number'],
                        shop_id=shop_id,
                        sales_id=new_sale.sales_id,
                        user_id=current_user_id,
                        items=[item['item_name'] for item in items],
                        amount_paid=total_amount_paid,
                        payment_method=", ".join(pm['method'] for pm in payment_methods),
                        created_at=created_at,
                        register_for_loyalty=register_for_loyalty
                    )
                    
                    logger.info(f"Customer processed: {customer_result['action']}, points earned: {customer_result['points_earned']}")
                    
                except Exception as e:
                    logger.error(f"Failed to process customer: {str(e)}")
                    # Continue with sale even if customer processing fails
                    customer_result = None

            # ===== COMMIT ALL TRANSACTIONS =====
            db.session.commit()
            logger.info(f"Sale {new_sale.sales_id} committed successfully with customer data")

            # ===== JOURNAL POSTING =====
            try:
                journal_result = JournalService.post_sale_journal(
                    sale=new_sale,
                    sold_items=sold_items,
                    shop_id=shop_id,
                    creditor_id=creditor_id,
                    amount_paid=total_amount_paid
                )
                db.session.commit()
                logger.info(f"Journal posted successfully for sale {new_sale.sales_id}")
            except Exception as e:
                logger.error(f"Journal posting failed: {str(e)}")
                # Don't rollback here - sale is already committed
                # Log the error but continue
                pass

            # ===== BUILD RESPONSE =====
            response_data = {
                'message': 'Sale processed successfully',
                'sale_id': new_sale.sales_id,
                'financial': {
                    'total': total_price,
                    'paid': total_amount_paid,
                    'balance': balance,
                    'purchase_cost': purchase_account
                },
                'items': {
                    'count': len(items),
                    'details': sold_items
                },
                'stock_deductions': {
                    'shop_stock': batch_deductions,
                    'livestock': livestock_deductions
                },
                'payments': {
                    'methods': [pm['method'] for pm in payment_methods],
                    'discounts_applied': [{'method': pm['method'], 'discount': float(pm.get('discount', 0))} for pm in payment_methods]
                },
                'delivery': delivery,
                'customer': None
            }

            # Add customer information to response
            if customer_result:
                response_data['customer'] = {
                    'customer_id': customer_result['customer'].customer_id,
                    'customer_name': customer_result['customer'].customer_name,
                    'is_new_customer': customer_result['is_new'],
                    'action': customer_result['action'],
                    'points_earned': customer_result['points_earned'],
                    'loyalty_points': customer_result['customer'].loyalty_points or 0,
                    'loyalty_tier': customer_result['customer'].loyalty_tier or 'Bronze',
                    'is_loyalty_registered': customer_result['customer'].is_loyalty_registered or False
                }

            # Add auto-discount notification if applied
            if auto_discount_applied:
                response_data['auto_discount'] = {
                    'applied': True,
                    'amount': balance,
                    'reason': f'Balance of {balance} ({balance_percentage:.2f}% of total) was within 3% threshold and converted to discount'
                }

            # Add creditor information to response if applicable
            if creditor:
                response_data['creditor'] = {
                    'creditor_id': creditor.id,
                    'creditor_name': creditor.name,
                    'previous_total_credit': creditor.total_credit - total_sale_amount,
                    'new_total_credit': creditor.total_credit,
                    'previous_credit_amount': creditor.credit_amount - total_sale_amount,
                    'new_credit_amount': creditor.credit_amount
                }

            return response_data, 201

        except Exception as e:
            db.session.rollback()
            logger.error(f"Transaction failed: {str(e)}")
            return {
                'message': 'Transaction failed',
                'error': str(e),
                'debug_info': {
                    'sale_id': new_sale.sales_id if new_sale else "Not created",
                    'processed_payments': [pm['method'] for pm in payment_methods] if payment_methods else [],
                    'delivery': delivery,
                    'creditor_id': creditor_id,
                    'auto_discount_applied': auto_discount_applied
                }
            }, 500

            
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



class GetSale(Resource):
    @jwt_required()
    def get(self):
        try:
            # Query all sales from the Sales table in descending order by created_at
            sales = Sales.query.order_by(Sales.created_at.desc()).all()

            # If no sales found
            if not sales:
                return {"message": "No sales found"}, 404

            # Format sales data into a list of dictionaries
            sales_data = []
            for sale in sales:
                # Fetch username and shop name manually using user_id and shop_id
                user = Users.query.filter_by(users_id=sale.user_id).first()
                shop = Shops.query.filter_by(shops_id=sale.shop_id).first()

                # Handle cases where user or shop may not be found
                username = user.username if user else "Unknown User"
                shopname = shop.shopname if shop else "Unknown Shop"

                # Get all sold items for this sale
                sold_items = []
                for item in sale.items:
                    sold_items.append({
                        "item_name": item.item_name,
                        "quantity": item.quantity,
                        "metric": item.metric,
                        "unit_price": item.unit_price,
                        "total_price": item.total_price,
                        "batch_number": item.BatchNumber,
                        "stock_id": item.stock_id,
                        "cost_of_sale": item.Cost_of_sale,
                        "purchase_account": item.Purchase_account
                    })

                # Process multiple payment methods using the `payment` relationship
                payment_data = [
                    {
                        "payment_method": payment.payment_method,
                        "amount_paid": payment.amount_paid,
                        "created_at": payment.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                        "balance": payment.balance,
                    }
                    for payment in sale.payment
                ]

                # Calculate total amount paid
                total_amount_paid = sum(payment["amount_paid"] for payment in payment_data)

                sales_data.append({
                    "sale_id": sale.sales_id,
                    "user_id": sale.user_id,
                    "username": username,
                    "shop_id": sale.shop_id,
                    "shopname": shopname,
                    "customer_name": sale.customer_name,
                    "status": sale.status,
                    "customer_number": sale.customer_number,
                    "sold_items": sold_items,  # Now includes all items from SoldItem table
                    "total_amount_paid": total_amount_paid,
                    "payment_methods": payment_data,
                    "created_at": sale.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                    "balance": sale.balance,
                    "note": sale.note,
                    "promocode": sale.promocode
                })

            return make_response(jsonify(sales_data), 200)

        except Exception as e:
            return {"error": str(e)}, 500


class GetSales(Resource):
    @jwt_required()
    def get(self):
        try:
            # Pagination
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 50))

            # Filters
            search_query = request.args.get('searchQuery', '')
            selected_date = request.args.get('selectedDate')
            status_filter = request.args.get('status')
            shop_filter = request.args.get('shop_id')
            payment_method_filter = request.args.get('payment_method')
            username_filter = request.args.get('username')
            sort_by = request.args.get('sort_by', 'created_at')
            sort_order = request.args.get('sort_order', 'desc')
            start_date = request.args.get('start_date')  # date range
            end_date = request.args.get('end_date')      # date range

            # Explicit export flag — ONLY the export modal should set this.
            # Previously any request that happened to include start_date/
            # end_date (i.e. normal date-range browsing, not just exports)
            # was treated as an export and returned every matching row with
            # no pagination at all. That's what was making filtered/date
            # requests slow — they weren't paginated.
            export_flag = request.args.get('export', 'false').lower() == 'true'

            # Valid sort fields
            valid_sort_fields = ['created_at', 'username', 'shopname', 'total_amount_paid']
            if sort_by not in valid_sort_fields:
                sort_by = 'created_at'
            if sort_order not in ['asc', 'desc']:
                sort_order = 'desc'

            # Base query
            sales_query = Sales.query.join(Users).join(Shops)

            # Apply filters
            if search_query:
                sales_query = sales_query.filter(
                    or_(
                        Sales.customer_name.ilike(f"%{search_query}%"),
                        Users.username.ilike(f"%{search_query}%"),
                        Shops.shopname.ilike(f"%{search_query}%")
                    )
                )

            # Handle single date filter (backward compatibility)
            if selected_date:
                try:
                    selected_date_obj = datetime.strptime(selected_date, '%Y-%m-%d').date()
                    sales_query = sales_query.filter(func.date(Sales.created_at) == selected_date_obj)
                except ValueError:
                    return {"error": "Invalid date format. Use YYYY-MM-DD."}, 400

            # Handle date range filter
            if start_date and end_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
                    sales_query = sales_query.filter(
                        func.date(Sales.created_at) >= start_date_obj,
                        func.date(Sales.created_at) <= end_date_obj
                    )
                except ValueError:
                    return {"error": "Invalid date format. Use YYYY-MM-DD."}, 400

            if status_filter:
                sales_query = sales_query.filter(Sales.status == status_filter)

            if shop_filter:
                sales_query = sales_query.filter(Sales.shop_id == int(shop_filter))

            if username_filter:
                sales_query = sales_query.filter(Users.username == username_filter)

            # Payment method — filter via a subquery (IN) rather than
            # joining SalesPaymentMethods directly, so a sale with several
            # payment method rows doesn't get duplicated in the result /
            # pagination count.
            if payment_method_filter:
                sales_query = sales_query.filter(
                    Sales.sales_id.in_(
                        db.session.query(SalesPaymentMethods.sale_id)
                        .filter(SalesPaymentMethods.payment_method == payment_method_filter)
                    )
                )

            # Handle sorting
            if sort_by == 'username':
                order_field = Users.username
            elif sort_by == 'shopname':
                order_field = Shops.shopname
            elif sort_by == 'total_amount_paid':
                payment_subquery = (
                    db.session.query(
                        SalesPaymentMethods.sale_id,
                        func.coalesce(func.sum(SalesPaymentMethods.amount_paid), 0).label('total_paid')
                    )
                    .group_by(SalesPaymentMethods.sale_id)
                    .subquery()
                )

                sales_query = sales_query.outerjoin(
                    payment_subquery,
                    payment_subquery.c.sale_id == Sales.sales_id
                )
                order_field = payment_subquery.c.total_paid
            else:
                order_field = Sales.created_at

            # Sort direction
            if sort_order == 'desc':
                sales_query = sales_query.order_by(order_field.desc())
            else:
                sales_query = sales_query.order_by(order_field.asc())

            # Only a genuine export request (explicit `export=true` from the
            # export modal) skips pagination. Every normal request —
            # regardless of which filters are set — is paginated.
            is_export = export_flag or limit > 2000

            if is_export:
                sales_list = sales_query.all()
                total_sales = len(sales_list)
                total_pages = 1
                current_page = 1
            else:
                offset = (page - 1) * limit
                total_sales = sales_query.count()
                sales_list = sales_query.offset(offset).limit(limit).all()
                total_pages = (total_sales + limit - 1) // limit if limit > 0 else 1
                current_page = page

            # Construct response data
            sales_data = []
            for sale in sales_list:
                sold_items = [
                    {
                        "item_name": item.item_name,
                        "quantity": item.quantity,
                        "metric": item.metric,
                        "unit_price": item.unit_price,
                        "total_price": item.total_price,
                        "batch_number": item.BatchNumber
                    }
                    for item in sale.items
                ]

                payments = [
                    {
                        "payment_method": p.payment_method,
                        "amount_paid": p.amount_paid if p.amount_paid is not None else 0,
                        "discount": p.discount if p.discount is not None else 0,
                        "balance": p.balance if p.balance is not None else 0,
                        "created_at": p.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                        "transaction_code": getattr(p, 'transaction_code', None)
                    }
                    for p in sale.payment
                ]

                total_amount_paid = sum(p.get("amount_paid", 0) for p in payments)
                total_discount = sum(p.get("discount", 0) for p in payments)

                sales_data.append({
                    "sale_id": sale.sales_id,
                    "user_id": sale.user_id,
                    "username": sale.users.username if sale.users else "Unknown User",
                    "shop_id": sale.shop_id,
                    "shopname": sale.shops.shopname if sale.shops else "Unknown Shop",
                    "customer_name": sale.customer_name or "Walk-in Customer",
                    "status": sale.status,
                    "customer_number": sale.customer_number,
                    "sold_items": sold_items,
                    "total_amount_paid": total_amount_paid,
                    "total_discount": total_discount,
                    "payment_methods": payments,
                    "created_at": sale.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                    "balance": sale.balance if sale.balance is not None else 0,
                    "note": sale.note,
                    "delivery": sale.delivery,
                    "promocode": sale.promocode
                })

            return {
                "sales_data": sales_data,
                "total_sales": total_sales,
                "total_pages": total_pages,
                "current_page": current_page
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
        

class SalesReport(Resource):
    @jwt_required()
    def get(self):
        try:
            start_date = request.args.get("start_date")
            end_date = request.args.get("end_date")

            if not start_date or not end_date:
                return {
                    "error": "start_date and end_date are required. Format: YYYY-MM-DD"
                }, 400

            try:
                datetime.strptime(start_date, "%Y-%m-%d")
                datetime.strptime(end_date, "%Y-%m-%d")
            except ValueError:
                return {
                    "error": "Invalid date format. Use YYYY-MM-DD"
                }, 400

            sql = text("""
                SELECT
                    s.sales_id                AS sale_id,
                    s.created_at              AS transaction_date,
                    s.customer_name,
                    s.customer_number,
                    s.status,
                    s.balance,
                    s.note,
                    s.delivery,
                    s.promocode,
                    s.user_id,
                    u.username,
                    s.shop_id,
                    sh.shopname,

                    -- Sold item details
                    si.item_name,
                    si.quantity,
                    si.metric,
                    si.unit_price,
                    si.total_price            AS item_total_price,
                    si.BatchNumber            AS batch_number,

                    -- Payment details
                    spm.payment_method,
                    spm.amount_paid,
                    spm.discount,
                    spm.balance               AS payment_balance,
                    spm.created_at            AS payment_created_at,
                    spm.transaction_code,

                    -- Cost of sale
                    csl.amount                AS cost_of_sale

                FROM sales s

                LEFT JOIN users u
                    ON u.users_id = s.user_id

                LEFT JOIN shops sh
                    ON sh.shops_id = s.shop_id

                LEFT JOIN sold_items si
                    ON si.sales_id = s.sales_id

                LEFT JOIN sales_payment_methods spm
                    ON spm.sale_id = s.sales_id

                LEFT JOIN cost_of_sale_ledger csl
                    ON csl.sales_id = s.sales_id

                WHERE s.created_at >= :start_date
                  AND s.created_at < DATE_ADD(:end_date, INTERVAL 1 DAY)

                ORDER BY s.created_at DESC, s.sales_id DESC
            """)

            result = db.session.execute(
                sql,
                {
                    "start_date": start_date,
                    "end_date": end_date
                }
            )

            # Group rows by sale_id so each sale is a single record
            # with nested sold_items, payment_methods, etc.
            sales_map = {}

            for row in result:
                sale_id = row.sale_id

                if sale_id not in sales_map:
                    sales_map[sale_id] = {
                        "sale_id": sale_id,
                        "transaction_date": (
                            row.transaction_date.strftime("%Y-%m-%d %H:%M:%S")
                            if row.transaction_date else None
                        ),
                        "user_id": row.user_id,
                        "username": row.username or "Unknown User",
                        "shop_id": row.shop_id,
                        "shopname": row.shopname or "Unknown Shop",
                        "customer_name": row.customer_name or "Walk-in Customer",
                        "customer_number": row.customer_number,
                        "status": row.status,
                        "balance": float(row.balance or 0),
                        "note": row.note,
                        "delivery": row.delivery,
                        "promocode": row.promocode,
                        "sold_items": [],
                        "payment_methods": [],
                        "cost_of_sale": 0.0,
                        "sale_amount": 0.0,
                        "amount_paid": 0.0,
                        "total_discount": 0.0,
                    }

                sale = sales_map[sale_id]

                # Sold item — only add if not already present
                if row.item_name is not None:
                    item = {
                        "item_name": row.item_name,
                        "quantity": float(row.quantity or 0),
                        "metric": row.metric,
                        "unit_price": float(row.unit_price or 0),
                        "total_price": float(row.item_total_price or 0),
                        "batch_number": row.batch_number,
                    }
                    if item not in sale["sold_items"]:
                        sale["sold_items"].append(item)
                        sale["sale_amount"] += item["total_price"]

                # Payment — only add if not already present
                if row.payment_method is not None:
                    payment = {
                        "payment_method": row.payment_method,
                        "amount_paid": float(row.amount_paid or 0),
                        "discount": float(row.discount or 0),
                        "balance": float(row.payment_balance or 0),
                        "created_at": (
                            row.payment_created_at.strftime("%Y-%m-%d %H:%M:%S")
                            if row.payment_created_at else None
                        ),
                        "transaction_code": row.transaction_code,
                    }
                    if payment not in sale["payment_methods"]:
                        sale["payment_methods"].append(payment)
                        sale["amount_paid"] += payment["amount_paid"]
                        sale["total_discount"] += payment["discount"]

                # Cost of sale — only set once
                if row.cost_of_sale is not None and sale["cost_of_sale"] == 0.0:
                    sale["cost_of_sale"] = float(row.cost_of_sale)

            # Build final list (no profit)
            report_data = []
            for sale in sales_map.values():
                sale["sale_amount"] = round(sale["sale_amount"], 2)
                sale["amount_paid"] = round(sale["amount_paid"], 2)
                sale["total_discount"] = round(sale["total_discount"], 2)
                sale["cost_of_sale"] = round(sale["cost_of_sale"], 2)
                report_data.append(sale)

            # Sort in Python to preserve sale order from SQL (created_at DESC)
            report_data.sort(
                key=lambda x: x["transaction_date"] or "",
                reverse=True
            )

            return {
                "count": len(report_data),
                "start_date": start_date,
                "end_date": end_date,
                "data": report_data
            }, 200

        except Exception as e:
            current_app.logger.error(
                f"Sales profitability report error: {str(e)}"
            )
            return {
                "error": "Failed to generate report"
            }, 500

class GetSalesByShop(Resource):
    @jwt_required()
    def get(self, shop_id):
        try:
            # Query params
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 50))
            search_query = request.args.get('search', '').lower()

            # Date range params
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')

            offset = (page - 1) * limit

            # Base query
            sales_query = Sales.query.filter_by(shop_id=shop_id)

            # Search filter
            if search_query:
                sales_query = sales_query.join(SoldItem).filter(
                    or_(
                        Sales.customer_name.ilike(f'%{search_query}%'),
                        SoldItem.item_name.ilike(f'%{search_query}%')
                    )
                )

            # Date range filter
            if start_date and end_date:
                try:
                    start = datetime.strptime(start_date, '%Y-%m-%d').date()
                    end = datetime.strptime(end_date, '%Y-%m-%d').date()

                    sales_query = sales_query.filter(
                        db.func.date(Sales.created_at).between(start, end)
                    )

                except ValueError:
                    return {"error": "Invalid date format. Use YYYY-MM-DD"}, 400

            elif start_date:
                try:
                    start = datetime.strptime(start_date, '%Y-%m-%d').date()

                    sales_query = sales_query.filter(
                        db.func.date(Sales.created_at) >= start
                    )

                except ValueError:
                    return {"error": "Invalid start_date format"}, 400

            elif end_date:
                try:
                    end = datetime.strptime(end_date, '%Y-%m-%d').date()

                    sales_query = sales_query.filter(
                        db.func.date(Sales.created_at) <= end
                    )

                except ValueError:
                    return {"error": "Invalid end_date format"}, 400

            # Count after filters
            total_sales = sales_query.count()

            # Pagination
            sales = (
                sales_query
                .order_by(Sales.created_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )

            if not sales:
                return {"message": "No sales found for this shop"}, 404

            sales_data = []

            for sale in sales:
                username = sale.users.username if sale.users else "Unknown User"
                shopname = sale.shops.shopname if sale.shops else "Unknown Shop"

                payment_data = [
                    {
                        "payment_method": payment.payment_method,
                        "amount_paid": payment.amount_paid,
                        "balance": payment.balance,
                    }
                    for payment in sale.payment
                ]

                total_amount_paid = sum(
                    p["amount_paid"] for p in payment_data
                )

                sold_items = [
                    {
                        "item_id": item.id,
                        "item_name": item.item_name,
                        "quantity": item.quantity,
                        "metric": item.metric,
                        "unit_price": item.unit_price,
                        "total_price": item.total_price,
                        "batch_number": item.BatchNumber,
                        "stockv2_id": item.stockv2_id,
                        "cost_of_sale": item.Cost_of_sale,
                        "purchase_account": item.Purchase_account
                    }
                    for item in sale.items
                ]

                total_items_price = sum(
                    item["total_price"] for item in sold_items
                )

                sales_data.append({
                    "sale_id": sale.sales_id,
                    "user_id": sale.user_id,
                    "username": username,
                    "shop_id": sale.shop_id,
                    "shop_name": shopname,
                    "customer_name": sale.customer_name,
                    "status": sale.status,
                    "customer_number": sale.customer_number,
                    "items": sold_items,
                    "total_items_price": total_items_price,
                    "total_amount_paid": total_amount_paid,
                    "balance": sale.balance,
                    "payment_methods": payment_data,
                    "created_at": sale.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                    "note": sale.note,
                    "delivery": sale.delivery,
                    "promocode": sale.promocode
                })

            total_pages = (total_sales + limit - 1) // limit

            return {
                "shop_id": shop_id,
                "shop_name": shopname,
                "total_sales": total_sales,
                "sales": sales_data,
                "current_page": page,
                "total_pages": total_pages,
            }, 200

        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}, 500



class SalesResources(Resource):
    @jwt_required()
    def get(self, sales_id):
        try:
            sale = Sales.query.get(sales_id)
            if not sale:
                return {"message": "Sale not found"}, 404

            user = Users.query.filter_by(users_id=sale.user_id).first()
            shop = Shops.query.filter_by(shops_id=sale.shop_id).first()

            username = user.username if user else "Unknown User"
            shopname = shop.shopname if shop else "Unknown Shop"

            # Get all sold items for this sale
            sold_items = [
                {
                    "item_name": item.item_name,
                    "quantity": item.quantity,
                    "metric": item.metric,
                    "unit_price": item.unit_price,
                    "total_price": item.total_price,
                    "batch_number": item.BatchNumber,  # Ensure case matches DB model
                    "stockv2_id": item.stockv2_id
                }
                for item in sale.items  # Assuming relationship: sale.items
            ]

            # Get payment data
            payment_data = [
                {
                    "payment_method": payment.payment_method,
                    "amount_paid": payment.amount_paid,
                    "created_at": payment.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                    "balance": payment.balance,
                }
                for payment in sale.payment
            ]
            total_amount_paid = sum(p["amount_paid"] for p in payment_data)

            sale_data = {
                "sale_id": sale.sales_id,
                "user_id": sale.user_id,
                "username": username,
                "shop_id": sale.shop_id,
                "shopname": shopname,
                "customer_name": sale.customer_name,
                "status": sale.status,
                "customer_number": sale.customer_number,
                "sold_items": sold_items,
                "total_amount_paid": total_amount_paid,
                "payment_methods": payment_data,
                "created_at": sale.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                "balance": sale.balance,
                "note": sale.note,
                "delivery": sale.delivery,
                "promocode": sale.promocode
            }

            return {"sale": sale_data}, 200

        except Exception as e:
            return {"error": str(e)}, 500 
        
    @jwt_required()
    def put(self, sales_id):
        try:
            sale = Sales.query.get(sales_id)
            if not sale:
                return {"message": "Sale not found"}, 404

            data = request.get_json()
            stock_updates = {}  # To track stock quantity changes

            # Update Sale fields
            if 'customer_name' in data:
                sale.customer_name = data['customer_name']
            if 'status' in data:
                sale.status = data['status']
            if 'customer_number' in data:
                sale.customer_number = data['customer_number']
            if 'note' in data:
                sale.note = data['note']
            if 'promocode' in data:
                sale.promocode = data['promocode']
            if 'balance' in data:
                sale.balance = data['balance']

            # Update or create Sold Items
            if 'items' in data:
                # First delete existing items if not in new data
                existing_item_ids = [item.id for item in sale.items]
                new_item_ids = [item.get('id') for item in data['items'] if item.get('id')]
                
                # Delete items not in new data and restore stock
                for item in sale.items:
                    if item.id not in new_item_ids:
                        # Restore the stock quantity before deleting
                        stock = ShopStockV2.query.get(item.stockv2_id)
                        if stock:
                            stock.quantity += item.quantity
                            stock_updates[item.stockv2_id] = stock.quantity
                        SoldItem.query.filter_by(id=item.id).delete()

                # Update or create items
                for item_data in data['items']:
                    if 'id' in item_data and item_data['id'] in existing_item_ids:
                        # Update existing item
                        item = SoldItem.query.get(item_data['id'])
                        stock = ShopStockV2.query.get(item.stockv2_id)
                        
                        # Calculate quantity difference
                        old_quantity = item.quantity
                        new_quantity = item_data.get('quantity', old_quantity)
                        quantity_diff = new_quantity - old_quantity
                        
                        # Update stock if quantity changed
                        if quantity_diff != 0 and stock:
                            # Check if enough stock is available for increase
                            if quantity_diff > 0 and stock.quantity < quantity_diff:
                                return {"error": f"Insufficient stock for item {item.item_name}. Available: {stock.quantity}"}, 400
                            
                            stock.quantity -= quantity_diff
                            stock_updates[item.stockv2_id] = stock.quantity
                        
                        # Update item fields
                        item.item_name = item_data.get('item_name', item.item_name)
                        item.quantity = new_quantity
                        item.metric = item_data.get('metric', item.metric)
                        item.unit_price = item_data.get('unit_price', item.unit_price)
                        item.total_price = item_data.get('total_price', item.total_price)
                        item.BatchNumber = item_data.get('BatchNumber', item.BatchNumber)
                        item.stockv2_id = item_data.get('stockv2_id', item.stockv2_id)
                        item.Cost_of_sale = item_data.get('Cost_of_sale', item.Cost_of_sale)
                        item.Purchase_account = item_data.get('Purchase_account', item.Purchase_account)
                        item.LivestockDeduction = item_data.get('LivestockDeduction', item.LivestockDeduction)
                    else:
                        # Create new item
                        stockv2_id = item_data['stockv2_id']
                        quantity = item_data['quantity']
                        stock = ShopStockV2.query.get(stockv2_id)
                        
                        # Check stock availability
                        if not stock:
                            return {"error": f"Stock item with ID {stockv2_id} not found"}, 404
                        if stock.quantity < quantity:
                            return {"error": f"Insufficient stock for item {item_data['item_name']}. Available: {stock.quantity}"}, 400
                        
                        # Deduct from stock
                        stock.quantity -= quantity
                        stock_updates[stockv2_id] = stock.quantity
                        
                        new_item = SoldItem(
                            sales_id=sales_id,
                            item_name=item_data['item_name'],
                            quantity=quantity,
                            metric=item_data['metric'],
                            unit_price=item_data['unit_price'],
                            total_price=item_data['total_price'],
                            BatchNumber=item_data.get('BatchNumber', ''),
                            stockv2_id=stockv2_id,
                            Cost_of_sale=item_data.get('Cost_of_sale', 0),
                            Purchase_account=item_data.get('Purchase_account', 0),
                            LivestockDeduction=item_data.get('LivestockDeduction', 0)
                        )
                        db.session.add(new_item)

            # Update or create Payment Methods
            if 'payment_methods' in data:
                # First delete existing payment methods if not in new data
                existing_payment_ids = [payment.id for payment in sale.payment]
                new_payment_ids = [pm.get('id') for pm in data['payment_methods'] if pm.get('id')]
                
                # Delete payments not in new data
                for payment_id in existing_payment_ids:
                    if payment_id not in new_payment_ids:
                        SalesPaymentMethods.query.filter_by(id=payment_id).delete()

                # Update or create payment methods
                for pm_data in data['payment_methods']:
                    if 'id' in pm_data and pm_data['id'] in existing_payment_ids:
                        # Update existing payment
                        payment = SalesPaymentMethods.query.get(pm_data['id'])
                        payment.payment_method = pm_data.get('payment_method', payment.payment_method)
                        payment.amount_paid = pm_data.get('amount_paid', payment.amount_paid)
                        payment.balance = pm_data.get('balance', payment.balance)
                        payment.transaction_code = pm_data.get('transaction_code', payment.transaction_code)
                    else:
                        # Create new payment
                        new_payment = SalesPaymentMethods(
                            sale_id=sales_id,
                            payment_method=pm_data['payment_method'],
                            amount_paid=pm_data['amount_paid'],
                            balance=pm_data.get('balance'),
                            transaction_code=pm_data.get('transaction_code'),
                            created_at=datetime.utcnow()
                        )
                        db.session.add(new_payment)

            db.session.commit()
            
            # Return success response with stock updates if any
            response = {
                "message": "Sale updated successfully",
                "stock_updates": stock_updates
            }
            return response, 200

        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 500


    @jwt_required()
    def delete(self, sales_id):
        try:
            sale = Sales.query.filter_by(sales_id=sales_id).first()
            if not sale:
                return {'message': 'Sale not found'}, 404

            # Restore stock quantities for each sold item
            for item in sale.items:  # Ensure `sale.items` is the correct relationship
                if item.stockv2_id:
                    stock = ShopStockV2.query.filter_by(stockv2_id=item.stockv2_id).first()
                    if stock:
                        stock.quantity += item.quantity

            # Delete payment records
            SalesPaymentMethods.query.filter_by(sale_id=sales_id).delete()

            # Delete customer
            customer = Customers.query.filter_by(sales_id=sales_id).first()
            if customer:
                db.session.delete(customer)

            # Delete sold items (assuming cascade is not set)
            for item in sale.items:
                db.session.delete(item)

            # Delete the sale
            db.session.delete(sale)

            db.session.commit()
            return {'message': 'Sale deleted, stock restored, and customer removed successfully'}, 200

        except Exception as e:
            db.session.rollback()
            return {'message': 'Error deleting sale', 'error': str(e)}, 500




class GetPaymentTotals(Resource):
    @jwt_required()
    def get(self):
        try:
            # Get query parameters for date range
            start_date_str = request.args.get('start_date')
            end_date_str = request.args.get('end_date')

            # Parse date strings to datetime objects if provided
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d') if start_date_str else None
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d') if end_date_str else None

            # Initialize totals dictionary
            totals = {"cash": 0, "bank": 0, "mpesa": 0, "sasapay": 0}

            # Build the query to calculate payment totals
            query = db.session.query(
                SalesPaymentMethods.payment_method,
                db.func.sum(SalesPaymentMethods.amount_paid).label('total_paid')
            ).join(
                Sales, Sales.sales_id == SalesPaymentMethods.sale_id
            ).filter(
                Sales.status != 'paid'  # Include unpaid and partially paid sales
            )

            # Apply date filters if provided
            if start_date:
                query = query.filter(Sales.created_at >= start_date)
            if end_date:
                query = query.filter(Sales.created_at <= end_date)

            # Group by payment method
            query = query.group_by(SalesPaymentMethods.payment_method)

            # Execute query and process results
            results = query.all()
            for payment_method, total_paid in results:
                if payment_method in totals:
                    totals[payment_method] = round(total_paid, 2)

            # Format the totals with currency
            formatted_totals = {method: f"ksh. {amount:,.2f}" for method, amount in totals.items()}

            return {"totals": formatted_totals}, 200

        except SQLAlchemyError as e:
            db.session.rollback()
            return {"error": "Database error occurred", "details": str(e)}, 500

        except Exception as e:
            return {"error": "An unexpected error occurred", "details": str(e)}, 500


class SalesBalanceResource(Resource):
    @jwt_required()
    def get(self):
        try:
            # Fetch all sales records
            all_sales = Sales.query.all()

            # Sum up all balances, ensuring non-None values, and ensure the result is positive
            total_balance = abs(sum(sale.balance for sale in all_sales if sale.balance is not None))

            return {"total_balance": f"ksh. {total_balance:,.2f}"}, 200

        except Exception as e:
            return {"error": str(e)}, 500

class TotalBalanceSummary(Resource):
    @jwt_required()
    @check_role('manager')
    def get(self):
        try:
            # Get start_date and end_date from query parameters
            start_date_str = request.args.get('start_date')
            end_date_str = request.args.get('end_date')

            # Parse dates if provided
            start_date = datetime.strptime(start_date_str.strip(), '%Y-%m-%d') if start_date_str else None
            end_date = datetime.strptime(end_date_str.strip(), '%Y-%m-%d') if end_date_str else None

            # Query expenses and filter by date range if specified
            query = Expenses.query
            if start_date:
                query = query.filter(Expenses.created_at >= start_date)
            if end_date:
                query = query.filter(Expenses.created_at <= end_date)

            expenses = query.all()
            total_expense_balance = sum(max(expense.totalPrice - expense.amountPaid, 0) for expense in expenses)

            # Query inventory items and filter by date range if specified
            inventory_query = Inventory.query
            if start_date:
                inventory_query = inventory_query.filter(Inventory.created_at >= start_date)
            if end_date:
                inventory_query = inventory_query.filter(Inventory.created_at <= end_date)

            inventory_items = inventory_query.all()
            total_inventory_balance = sum(max(item.totalCost - item.amountPaid, 0) for item in inventory_items)

            # Aggregate both balances
            total_balance = total_expense_balance + total_inventory_balance

            # Return the total balance as JSON with currency format
            return {"total_balance": f"ksh. {total_balance:,.2f}"}, 200

        except SQLAlchemyError as e:
            db.session.rollback()
            return {"error": "Database error occurred", "details": str(e)}, 500
        except Exception as e:
            return {"error": "An unexpected error occurred", "details": str(e)}, 500


class TotalBalance(Resource):
    @jwt_required()
    @check_role('manager')
    def get(self):
        try:
            # Get start_date and end_date from query parameters
            start_date_str = request.args.get('start_date')
            end_date_str = request.args.get('end_date')

            # Convert date strings to datetime objects if provided
            if start_date_str:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            else:
                start_date = None

            if end_date_str:
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
            else:
                end_date = None

            # Query expenses, possibly filtering by date range using created_at
            query = Expenses.query
            if start_date:
                query = query.filter(Expenses.created_at >= start_date)
            if end_date:
                query = query.filter(Expenses.created_at <= end_date)

            expenses = query.all()

            # Calculate the total balance
            total_balance = sum(max(expense.totalPrice - expense.amountPaid, 0) for expense in expenses)

            # Return the total balance
            return make_response(jsonify({"total_balance": total_balance}), 200)

        except SQLAlchemyError as e:
            db.session.rollback()
            return make_response(jsonify({"error": "Database error occurred", "details": str(e)}), 500)
        except Exception as e:
            return make_response(jsonify({"error": "An unexpected error occurred", "details": str(e)}), 500)
       

class UpdateSalePayment(Resource):
    
    @jwt_required()
    @check_role('manager')

    def put(self, sale_id):
        current_user_id = get_jwt_identity()
        data = request.get_json()

        # Check if sale exists
        sale = Sales.query.filter_by(sales_id=sale_id).first()
        if not sale:
            return make_response(jsonify({"message": "Sale not found"}), 404)

        payment_methods = data.get("payment_methods", [])
        payment_date = data.get("payment_date", datetime.utcnow().strftime("%Y-%m-%d"))  # Allow manual input or default to today

        # Validate payment methods format
        if not isinstance(payment_methods, list) or not all(
            isinstance(pm, dict) and 'method' in pm and 'amount' in pm for pm in payment_methods
        ):
            return make_response(jsonify({"message": "Invalid payment methods format"}), 400)

        try:
            # Convert payment_date string to datetime object
            try:
                payment_date_obj = datetime.strptime(payment_date, "%Y-%m-%d")
            except ValueError:
                return make_response(jsonify({"message": "Invalid date format. Use YYYY-MM-DD"}), 400)

            # ✅ Step 1: Fetch Existing Payments for the Sale
            existing_payments = SalesPaymentMethods.query.filter_by(sale_id=sale_id).all()
            total_paid = sum(payment.amount_paid for payment in existing_payments)  # Get total already paid

            # ✅ Step 2: Process new payment methods
            new_total_paid = total_paid  # Start with previous total

            for payment in payment_methods:
                payment_method = payment["method"]
                amount_paid = float(payment["amount"])
                transaction_code = payment.get("transaction_code", "N/A")  # Default transaction code

                # ✅ If the new payment amount is zero, update an existing payment method
                if amount_paid == 0 and existing_payments:
                    for existing_payment in existing_payments:
                        if existing_payment.payment_method == payment_method:
                            existing_payment.transaction_code = transaction_code  # Update only transaction_code
                            existing_payment.created_at = payment_date_obj  # Update payment date
                            db.session.add(existing_payment)  # Save changes
                            break  # Stop once an update is done
                else:
                    new_total_paid += amount_paid  # Add new payment amount

                    # ✅ Step 3: Insert new payment if it's greater than 0
                    new_payment = SalesPaymentMethods(
                        sale_id=sale_id,
                        payment_method=payment_method,
                        amount_paid=amount_paid,
                        transaction_code=transaction_code,
                        created_at=payment_date_obj  # Use the provided payment date
                    )
                    db.session.add(new_payment)

            # ✅ Step 4: Update Sale Balance
            new_balance = sale.total_price - new_total_paid
            sale.balance = new_balance
            sale.status = "paid" if sale.balance <= 0 else "unpaid"

            db.session.commit()

            return make_response(jsonify({
                "message": "Payment updated successfully",
                "new_balance": sale.balance,
                "status": sale.status,
                "updated_payment_date": payment_date  # ✅ Return updated payment date
            }), 200)

        except Exception as e:
            db.session.rollback()
            return make_response(jsonify({"message": "Error updating payment method", "error": str(e)}), 500)
        
class GetUnpaidSales(Resource):
    @jwt_required()
    @check_role('manager')
    def get(self):
        try:
            # Get page and limit from query parameters, defaulting to 1 and 50
            page = int(request.args.get('page', 1))  # Default to page 1 if not provided
            limit = int(request.args.get('limit', 50))  # Default to 50 items per request

            search_query = request.args.get('searchQuery', '')
            selected_date = request.args.get('selectedDate', None)

            # Start building the query for unpaid and partially paid sales
            sales_query = Sales.query.filter(Sales.status.in_(["unpaid", "partially_paid"]))

            # If a search query is provided, add it to the query
            if search_query:
                sales_query = sales_query.join(Shops).join(Users).filter(
                    Sales.customer_name.ilike(f"%{search_query}%") |
                    Users.username.ilike(f"%{search_query}%") |
                    Shops.shopname.ilike(f"%{search_query}%")
                )
            
            # If a selected date is provided, add date filter
            if selected_date:
                try:
                    selected_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
                    sales_query = sales_query.filter(db.func.date(Sales.created_at) == selected_date)
                except ValueError:
                    return {"error": "Invalid date format. Use YYYY-MM-DD."}, 400

            # Apply sorting by created_at and then pagination
            sales_query = sales_query.order_by(Sales.created_at.desc())

            # Handle pagination
            offset = (page - 1) * limit
            sales_query = sales_query.offset(offset).limit(limit)

            # Fetch sales data
            sales = sales_query.all()
            total_sales = Sales.query.filter(Sales.status.in_(["unpaid", "partially_paid"])).count()  # Total count for pagination
            total_pages = (total_sales + limit - 1) // limit  # Calculate total pages

            # Prepare the sales data to return
            sales_data = []
            for sale in sales:
                user = Users.query.filter_by(users_id=sale.user_id).first()
                shop = Shops.query.filter_by(shops_id=sale.shop_id).first()
                username = user.username if user else "Unknown User"
                shopname = shop.shopname if shop else "Unknown Shop"
                
                # Get all sold items for this sale
                sold_items = []
                for item in sale.items:
                    sold_items.append({
                        "item_name": item.item_name,
                        "quantity": item.quantity,
                        "metric": item.metric,
                        "unit_price": item.unit_price,
                        "total_price": item.total_price,
                        "batch_number": item.BatchNumber
                    })
                
                # Get payment data
                payment_data = [
                    {
                        "payment_method": payment.payment_method,
                        "amount_paid": payment.amount_paid,
                        "created_at": payment.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                        "balance": payment.balance,
                    }
                    for payment in sale.payment
                ]
                total_amount_paid = sum(payment["amount_paid"] for payment in payment_data)

                sales_data.append({
                    "sale_id": sale.sales_id,
                    "user_id": sale.user_id,
                    "username": username,
                    "shop_id": sale.shop_id,
                    "shopname": shopname,
                    "customer_name": sale.customer_name,
                    "status": sale.status,
                    "customer_number": sale.customer_number,
                    "sold_items": sold_items,
                    "total_amount_paid": total_amount_paid,
                    "payment_methods": payment_data,
                    "created_at": sale.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                    "balance": sale.balance,
                    "note": sale.note,
                    "delivery": sale.delivery,
                    "promocode": sale.promocode
                })

            return {
                "sales_data": sales_data,
                "total_sales": total_sales,
                "total_pages": total_pages,
                "current_page": page,
            }, 200

        except Exception as e:
            return {"error": str(e)}, 500


        

class PaymentMethodsResource(Resource):
    @jwt_required()
    def get(self, sale_id):
        try:
            # Fetch all payment methods for this sale
            payment_methods = SalesPaymentMethods.query.filter_by(sale_id=sale_id).all()

            # If no payment methods found
            if not payment_methods:
                return {"message": "No payment methods found for this sale"}, 404

            # Format the payment data
            payment_data = [
                {
                    "payment_method": payment.payment_method,
                    "amount_paid": payment.amount_paid,
                    "balance": payment.balance,
                    "transaction_code": payment.transaction_code,
                    "created_at": payment.created_at.strftime('%Y-%m-%d %H:%M:%S') 
                    if isinstance(payment.created_at, datetime) else payment.created_at
                }
                for payment in payment_methods
            ]

            return make_response(jsonify(payment_data), 200)

        except Exception as e:
            return {"error": str(e)}, 500
        


class CapturePaymentResource(Resource):
    @jwt_required()
    def post(self, sale_id):
        try:
            data = request.get_json()
            payment_method = data.get("payment_method")
            amount_paid = data.get("amount_paid")
            transaction_code = data.get("transaction_code", "NONE")  # Default to "NONE"

            # Validate required fields
            if not payment_method or amount_paid is None:
                return {"message": "Payment method and amount_paid are required"}, 400

            # Check if the sale exists
            sale = Sales.query.filter_by(sales_id=sale_id).first()
            if not sale:
                return {"message": "Sale not found"}, 404
            
            # FUNCTION: Check if customer exists in Creditors and deduct from credit if needed
            self.deduct_from_creditor_if_exists(sale.customer_name, amount_paid, sale.shop_id)

            # Remove the "not payed" record if it exists
            unpaid_payment = SalesPaymentMethods.query.filter_by(
                sale_id=sale_id, payment_method="not payed"
            ).first()
            if unpaid_payment:
                db.session.delete(unpaid_payment)

            # Check if a payment record already exists for this sale & method
            existing_payment = SalesPaymentMethods.query.filter_by(
                sale_id=sale_id,
                payment_method=payment_method
            ).first()

            if existing_payment:
                # Update the existing payment method
                existing_payment.amount_paid += amount_paid
                existing_payment.transaction_code = transaction_code
            else:
                # Create a new payment record
                new_payment = SalesPaymentMethods(
                    sale_id=sale_id,
                    payment_method=payment_method,
                    amount_paid=amount_paid,
                    balance=None,  # Balance managed at the sale level
                    transaction_code=transaction_code,
                    created_at=datetime.utcnow(),
                )
                db.session.add(new_payment)

            # Recalculate total amount paid for the sale
            total_paid = db.session.query(
                db.func.sum(SalesPaymentMethods.amount_paid)
            ).filter_by(sale_id=sale_id).scalar() or 0

            # ✅ Use the balance field from sales instead of sold_items total_price
            # Assume sales.balance is always kept up to date at creation
            new_balance = max(0, sale.balance - amount_paid)
            sale.balance = new_balance

            # Update sale status
            if sale.balance == 0:
                sale.status = "paid"
            elif total_paid > 0 and sale.balance > 0:
                sale.status = "partially_paid"

            # Commit changes
            db.session.commit()

            # Get updated payment records
            updated_payments = SalesPaymentMethods.query.filter_by(sale_id=sale_id).all()
            payment_data = [
                {
                    "payment_method": pm.payment_method,
                    "amount_paid": pm.amount_paid,
                    "balance": pm.balance,
                    "transaction_code": pm.transaction_code,
                    "created_at": pm.created_at.strftime('%Y-%m-%d %H:%M:%S') 
                    if isinstance(pm.created_at, datetime) else pm.created_at
                }
                for pm in updated_payments
            ]

            return make_response(jsonify({
                "message": "Payment recorded successfully",
                "sale_id": sale_id,
                "customer_name": sale.customer_name,
                "customer_number": sale.customer_number,
                "sale_status": sale.status,
                "remaining_balance": sale.balance,
                "payment_methods": payment_data,
                "created_at": sale.created_at.strftime('%Y-%m-%d %H:%M:%S') 
                if isinstance(sale.created_at, datetime) else sale.created_at,
                "note": sale.note,
                "delivery": sale.delivery,
                "promocode": sale.promocode
            }), 200)

        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 500

    def deduct_from_creditor_if_exists(self, customer_name, amount_paid, shop_id):
        """
        Check if customer exists in Creditors table and deduct payment from their credit amount.
        
        Args:
            customer_name (str): Name of the customer to search for
            amount_paid (float): Amount paid to deduct from creditor's credit
            shop_id (int): Shop ID to match the correct creditor record
        """
        try:
            # Search for creditor by name and shop_id (case-insensitive)
            creditor = Creditors.query.filter(
                func.lower(Creditors.name) == func.lower(customer_name),
                Creditors.shop_id == shop_id
            ).first()
            
            if creditor:
                # Check if creditor has available credit
                if creditor.credit_amount and creditor.credit_amount > 0:
                    # Calculate how much can be deducted (min of amount_paid and available credit)
                    deduction_amount = min(amount_paid, creditor.credit_amount)
                    
                    # Deduct from credit_amount
                    creditor.credit_amount -= deduction_amount
                    
                    # Ensure credit_amount doesn't go below 0
                    creditor.credit_amount = max(0, creditor.credit_amount)
                    
                    # Log the deduction (optional - you might want to create a transaction log)
                    print(f"Deducted {deduction_amount} from creditor {creditor.name}. "
                          f"Remaining credit: {creditor.credit_amount}")
                    
                    return {
                        "success": True,
                        "creditor_name": creditor.name,
                        "amount_deducted": deduction_amount,
                        "remaining_credit": creditor.credit_amount,
                        "shop_id": shop_id
                    }
                else:
                    print(f"Creditor {creditor.name} exists but has no available credit.")
                    return {
                        "success": False,
                        "message": "No available credit",
                        "creditor_name": creditor.name
                    }
            else:
                print(f"No creditor found with name '{customer_name}' in shop {shop_id}")
                return {
                    "success": False,
                    "message": "Creditor not found"
                }
                
        except Exception as e:
            print(f"Error deducting from creditor: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }


class CreditHistoryResource(Resource):
    @jwt_required()
    def get(self):
        try:
            # Query sales with payments where the timestamps do not match and status is "paid"
            sales_with_payments = db.session.query(Sales).join(SalesPaymentMethods).filter(Sales.status == "paid").all()

            credit_sales = []
            for sale in sales_with_payments:
                # Handle invalid timestamps
                if sale.created_at in ["0000-00-00 00:00:00", None]:
                    continue  # Skip invalid sale records

                # Convert sale.created_at to datetime
                sale_created_at = sale.created_at
                if isinstance(sale_created_at, str):
                    sale_created_at = datetime.strptime(sale_created_at, '%Y-%m-%d %H:%M:%S')

                # Get all payments linked to the sale
                payments = SalesPaymentMethods.query.filter_by(sale_id=sale.sales_id).all()

                # Check if any payment timestamp is different from the sale timestamp
                mismatched_payments = []
                for payment in payments:
                    if payment.created_at in ["0000-00-00 00:00:00", None]:
                        continue  # Skip invalid payment records

                    # Convert payment.created_at to datetime
                    payment_created_at = payment.created_at
                    if isinstance(payment_created_at, str):
                        payment_created_at = datetime.strptime(payment_created_at, '%Y-%m-%d %H:%M:%S')

                    if payment_created_at.date() != sale_created_at.date():
                        mismatched_payments.append({
                            "payment_method": payment.payment_method,
                            "amount_paid": payment.amount_paid,
                            "payment_created_at": payment_created_at.strftime('%Y-%m-%d %H:%M:%S'),
                            "sale_created_at": sale_created_at.strftime('%Y-%m-%d %H:%M:%S'),
                        })

                if mismatched_payments:
                    credit_sales.append({
                        "sale_id": sale.sales_id,
                        "customer_name": sale.customer_name,
                        "shop_id": sale.shop_id,
                        "total_price": sale.total_price,
                        "balance": sale.balance,
                        "status": sale.status,
                        "sale_created_at": sale_created_at.strftime('%Y-%m-%d %H:%M:%S'),
                        "mismatched_payments": mismatched_payments,
                    })

            if not credit_sales:
                return {"message": "No credit sales found"}, 404

            return make_response(jsonify(credit_sales), 200)

        except Exception as e:
            return {"error": str(e)}, 500



class GetSingleSaleByShop(Resource):
    @jwt_required()
    def get(self, shop_id, sales_id):
        try:
            # Query the Sales table for the specific sale related to the given shop_id and sales_id
            sale = Sales.query.filter_by(shop_id=shop_id, sales_id=sales_id).first()

            # If no sale is found
            if not sale:
                return {"message": "Sale not found for this shop"}, 404

            # Fetch username and shop name using relationships
            username = sale.users.username if sale.users else "Unknown User"
            shopname = sale.shops.shopname if sale.shops else "Unknown Shop"

            # Debug: Print data types of created_at fields
            print(f"Sale created_at type: {type(sale.created_at)}, value: {sale.created_at}")
            
            # Ensure sale.created_at is a datetime object before calling strftime
            sale_created_at = sale.created_at
            if isinstance(sale_created_at, str):
                sale_created_at = datetime.strptime(sale_created_at, '%Y-%m-%d %H:%M:%S')

            # Process multiple payment methods and calculate total amount paid
            payment_data = []
            total_amount_paid = 0

            for payment in sale.payment:
                print(f"Payment created_at type: {type(payment.created_at)}, value: {payment.created_at}")
                
                # Ensure payment.created_at is a datetime object before calling strftime
                payment_created_at = payment.created_at
                if isinstance(payment_created_at, str):
                    payment_created_at = datetime.strptime(payment_created_at, '%Y-%m-%d %H:%M:%S')

                payment_data.append({
                    "payment_method": payment.payment_method,
                    "amount_paid": payment.amount_paid,
                    "balance": payment.balance,
                    "created_at": payment_created_at.strftime('%Y-%m-%d %H:%M:%S') 
                })
                total_amount_paid += payment.amount_paid

            # Process sold items
            sold_items = []
            total_sale_amount = 0
            for item in sale.items:
                sold_items.append({
                    "item_id": item.id,
                    "item_name": item.item_name,
                    "quantity": item.quantity,
                    "metric": item.metric,
                    "unit_price": item.unit_price,
                    "total_price": item.total_price,
                    "batch_number": item.BatchNumber,
                    "stockv2_id": item.stockv2_id,
                    "cost_of_sale": item.Cost_of_sale,
                    "purchase_account": item.Purchase_account
                })
                total_sale_amount += item.total_price

            # Format the sale data
            sale_data = {
                "sale_id": sale.sales_id,
                "user_id": sale.user_id,
                "username": username,
                "shop_id": sale.shop_id,
                "shop_name": shopname,
                "customer_name": sale.customer_name,
                "status": sale.status,
                "customer_number": sale.customer_number,
                "created_at": sale_created_at.strftime('%Y-%m-%d %H:%M:%S'),
                "balance": sale.balance,
                "note": sale.note,
                "promocode": sale.promocode,
                "total_sale_amount": total_sale_amount,
                "total_amount_paid": total_amount_paid,
                "payment_methods": payment_data,
                "sold_items": sold_items
            }

            return {"sale": sale_data}, 200

        except Exception as e:
            return {"error": f"An error occurred while processing the request: {str(e)}"}, 500



#Get unpaid sales by shop
class GetUnpaidSalesByClerk(Resource):
    @jwt_required()
    @check_role('clerk')
    def get(self):
        try:
            # Get the logged-in clerk's user ID
            current_user_id = get_jwt_identity()

            # Fetch only unpaid sales recorded by this specific clerk
            unpaid_sales = Sales.query.filter(
                Sales.user_id == current_user_id,
                Sales.status.in_(["unpaid", "partially_paid"])
            ).order_by(Sales.created_at.desc()).all()

            if not unpaid_sales:
                return {'message': 'No unpaid or partially paid sales found for you'}, 404

            sales_list = []
            for sale in unpaid_sales:
                # Fetch user details
                user = Users.query.filter_by(users_id=sale.user_id).first()
                username = user.username if user else "Unknown User"

                # Fetch shop details
                shop = Shops.query.filter_by(shops_id=sale.shop_id).first()
                shopname = shop.shopname if shop else "Unknown Shop"

                # Calculate total amount paid from payment methods
                total_paid = sum(payment.amount_paid for payment in sale.payment)

                # Get all sold items for this sale
                sold_items = [
                    {
                        "item_id": item.id,
                        "item_name": item.item_name,
                        "quantity": item.quantity,
                        "metric": item.metric,
                        "unit_price": item.unit_price,
                        "total_price": item.total_price,
                        "batch_number": item.BatchNumber,
                        "stockv2_id": item.stockv2_id,
                        "cost_of_sale": item.Cost_of_sale,
                        "purchase_account": item.Purchase_account
                    }
                    for item in sale.items
                ]

                # Calculate total items price
                total_items_price = sum(item["total_price"] for item in sold_items)

                sales_list.append({
                    "sales_id": sale.sales_id,
                    "user_id": sale.user_id,
                    "username": username,
                    "shop_id": sale.shop_id,
                    "shopname": shopname,
                    "customer_name": sale.customer_name,
                    "customer_number": sale.customer_number,
                    "items": sold_items,
                    "total_items_price": total_items_price,
                    "total_paid": total_paid,
                    "balance": sale.balance,
                    "status": sale.status,
                    "created_at": sale.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "payment_methods": [
                        {
                            "method": payment.payment_method,
                            "amount_paid": payment.amount_paid,
                            "balance": payment.balance
                        }
                        for payment in sale.payment
                    ],
                    "note": sale.note,
                    "delivery": sale.delivery,
                    "promocode": sale.promocode
                })
            
            return {
                "count": len(sales_list),
                "total_balance": sum(sale["balance"] for sale in sales_list),
                "unpaid_sales": sales_list
            }, 200
        
        except Exception as e:
            return {"message": f"An error occurred: {str(e)}"}, 500


class SalesByEmployeeResource(Resource):
    @jwt_required()
    def get(self, username):
        try:
            # Get pagination parameters
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 50))
            offset = (page - 1) * limit

            # Use only the first name segment of the username
            first_name = username.split()[0]

            # Find the user by username to get users_id
            user = Users.query.filter(Users.username.like(f"{first_name}%")).first()
            if not user:
                return {"message": "Employee not found"}, 404

            users_id = user.users_id

            # Base query for filtering sales by users_id
            base_query = Sales.query.filter(
                Sales.user_id == users_id
            ).order_by(Sales.created_at.desc())

            total_sales = base_query.count()  # Total records
            total_pages = (total_sales + limit - 1) // limit

            # Apply pagination
            sales = base_query.offset(offset).limit(limit).all()

            if not sales:
                return {"message": "No sales found for this employee."}, 404

            sales_data = []
            for sale in sales:
                user = Users.query.filter_by(users_id=sale.user_id).first()
                shop = Shops.query.filter_by(shops_id=sale.shop_id).first()

                username = user.username if user else "Unknown User"
                shopname = shop.shopname if shop else "Unknown Shop"

                payment_data = [
                    {
                        "payment_method": payment.payment_method,
                        "amount_paid": payment.amount_paid,
                        "balance": payment.balance,
                    }
                    for payment in sale.payment
                ]
                total_amount_paid = sum(payment['amount_paid'] for payment in payment_data)

                sold_items = [
                    {
                        "item_id": item.id,
                        "item_name": item.item_name,
                        "quantity": item.quantity,
                        "metric": item.metric,
                        "unit_price": item.unit_price,
                        "total_price": item.total_price,
                        "batch_number": item.BatchNumber,
                        "stockv2_id": item.stockv2_id,
                        "cost_of_sale": item.Cost_of_sale,
                        "purchase_account": item.Purchase_account
                    }
                    for item in sale.items
                ]

                total_items_price = sum(item["total_price"] for item in sold_items)

                sales_data.append({
                    "sale_id": sale.sales_id,
                    "user_id": sale.user_id,
                    "username": username,
                    "shop_id": sale.shop_id,
                    "shop_name": shopname,
                    "customer_name": sale.customer_name,
                    "status": sale.status,
                    "customer_number": sale.customer_number,
                    "items": sold_items,
                    "total_items_price": total_items_price,
                    "total_amount_paid": total_amount_paid,
                    "balance": sale.balance,
                    "payment_methods": payment_data,
                    "created_at": sale.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                    "note": sale.note,
                    "delivery": sale.delivery,
                    "promocode": sale.promocode
                })

            return {
                "employee": username,
                "employee_id": users_id,
                "total_sales": total_sales,
                "total_amount": sum(sale['total_amount_paid'] for sale in sales_data),
                "current_page": page,
                "total_pages": total_pages,
                "sales": sales_data
            }, 200

        except Exception as e:
            return {"error": str(e)}, 500


class CashSalesByUser(Resource):
    def get(self, user_id):
        query = (
            Sales.query
            .join(SalesPaymentMethods, Sales.sales_id == SalesPaymentMethods.sale_id)
            .filter(
                Sales.user_id == user_id,
                SalesPaymentMethods.payment_method == 'cash'
            )
        )

        # Date filtering
        date_str = request.args.get('date')
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')

        try:
            if date_str:
                date = datetime.strptime(date_str, "%Y-%m-%d").date()
                query = query.filter(db.func.date(Sales.created_at) == date)
            elif start_date_str and end_date_str:
                start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
                query = query.filter(db.func.date(Sales.created_at).between(start_date, end_date))
        except ValueError:
            return {"error": "Invalid date format. Use YYYY-MM-DD."}, 400

        sales = query.all()

        results = []
        for sale in sales:
            payments = [p for p in sale.payment if p.payment_method == 'cash']
            for p in payments:
                results.append({
                    "sales_id": sale.sales_id,
                    "user_id": sale.user_id,
                    "shop_id": sale.shop_id,
                    "customer_name": sale.customer_name,
                    "item_name": sale.item_name,
                    "quantity": sale.quantity,
                    "metric": sale.metric,
                    "unit_price": sale.unit_price,
                    "total_price": sale.total_price,
                    "amount_paid": p.amount_paid,
                    "balance": p.balance,
                    "transaction_code": p.transaction_code,
                    "created_at": sale.created_at.strftime('%Y-%m-%d %H:%M:%S')
                })

        return jsonify(results)
         
class CashSales(Resource):
    @jwt_required()
    def get(self):
        shop_id = request.args.get("shop_id")

        # Set the minimum date filter to 2025-05-27
        min_date = datetime(2025, 5, 27).date()

        query = (
            Sales.query
            .join(SalesPaymentMethods, Sales.sales_id == SalesPaymentMethods.sale_id)
            .filter(SalesPaymentMethods.payment_method == 'cash')
            .filter(db.func.date(Sales.created_at) >= min_date)  # Add minimum date filter
        )

        if shop_id:
            query = query.filter(Sales.shop_id == shop_id)

        # Date filtering (optional additional filters)
        date_str = request.args.get('date')
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')

        try:
            if date_str:
                date = datetime.strptime(date_str, "%Y-%m-%d").date()
                if date < min_date:
                    date = min_date  # Ensure we don't go before our minimum date
                query = query.filter(db.func.date(Sales.created_at) == date)
            elif start_date_str and end_date_str:
                start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
                # Adjust start_date if it's before our minimum
                if start_date < min_date:
                    start_date = min_date
                query = query.filter(db.func.date(Sales.created_at).between(start_date, end_date))
        except ValueError:
            return {"error": "Invalid date format. Use YYYY-MM-DD."}, 400

        sales = query.all()

        results = []
        for sale in sales:
            user = Users.query.filter_by(users_id=sale.user_id).first()
            shop = Shops.query.filter_by(shops_id=sale.shop_id).first()

            username = user.username if user else "Unknown User"
            shopname = shop.shopname if shop else "Unknown Shop"

            payments = [p for p in sale.payment if p.payment_method == 'cash']
            for p in payments:
                created_at = sale.created_at.strftime('%Y-%m-%d %H:%M:%S') if sale.created_at else None

                results.append({
                    "sales_id": sale.sales_id,
                    "shop_id": sale.shop_id,
                    "shop_name": shopname,
                    "user_id": sale.user_id,
                    "username": username,
                    "customer_name": sale.customer_name,
                    "item_name": sale.item_name,
                    "quantity": sale.quantity,
                    "metric": sale.metric,
                    "unit_price": sale.unit_price,
                    "total_price": sale.total_price,
                    "amount_paid": p.amount_paid,
                    "balance": p.balance,
                    "transaction_code": p.transaction_code,
                    "created_at": created_at
                })

        return jsonify(results)

    def delete(self, sale_id):
        """Delete a specific sale and its payment records."""
        sale = Sales.query.get(sale_id)
        if not sale:
            return {"message": "Sale not found"}, 404

        db.session.delete(sale)
        db.session.commit()
        return {"message": "Sale deleted successfully"}, 200

    def put(self, sale_id):
        """Update a specific sale (quantity, unit price, total)."""
        sale = Sales.query.get(sale_id)
        if not sale:
            return {"message": "Sale not found"}, 404

        data = request.get_json()
        sale.quantity = data.get("quantity", sale.quantity)
        sale.unit_price = data.get("unit_price", sale.unit_price)
        sale.total_price = sale.quantity * sale.unit_price

        db.session.commit()
        return {"message": "Sale updated successfully"}, 200


    def delete(self, sale_id):
        """Delete a specific sale and its payment records."""
        sale = Sales.query.get(sale_id)
        if not sale:
            return {"message": "Sale not found"}, 404

        db.session.delete(sale)
        db.session.commit()
        return {"message": "Sale deleted successfully"}, 200

    def put(self, sale_id):
        """Update a specific sale (quantity, unit price, total)."""
        sale = Sales.query.get(sale_id)
        if not sale:
            return {"message": "Sale not found"}, 404

        data = request.get_json()
        sale.quantity = data.get("quantity", sale.quantity)
        sale.unit_price = data.get("unit_price", sale.unit_price)
        sale.total_price = sale.quantity * sale.unit_price

        db.session.commit()
        return {"message": "Sale updated successfully"}, 200
    
class CashSalesByUser(Resource):
    def get(self, user_id):
        query = (
            Sales.query
            .join(SalesPaymentMethods, Sales.sales_id == SalesPaymentMethods.sale_id)
            .filter(
                Sales.user_id == user_id,
                SalesPaymentMethods.payment_method == 'cash'
            )
        )

        # Date filtering
        date_str = request.args.get('date')
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')

        try:
            if date_str:
                date = datetime.strptime(date_str, "%Y-%m-%d").date()
                query = query.filter(db.func.date(Sales.created_at) == date)
            elif start_date_str and end_date_str:
                start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
                query = query.filter(db.func.date(Sales.created_at).between(start_date, end_date))
        except ValueError:
            return {"error": "Invalid date format. Use YYYY-MM-DD."}, 400

        sales = query.all()

        results = []
        for sale in sales:
            payments = [p for p in sale.payment if p.payment_method == 'cash']
            for p in payments:
                results.append({
                    "sales_id": sale.sales_id,
                    "user_id": sale.user_id,
                    "shop_id": sale.shop_id,
                    "customer_name": sale.customer_name,
                    "item_name": sale.item_name,
                    "quantity": sale.quantity,
                    "metric": sale.metric,
                    "unit_price": sale.unit_price,
                    "total_price": sale.total_price,
                    "amount_paid": p.amount_paid,
                    "balance": p.balance,
                    "transaction_code": p.transaction_code,
                    "created_at": sale.created_at.strftime('%Y-%m-%d %H:%M:%S')
                })

        return jsonify(results)
  
class CashAtHandByUser(Resource):
    @jwt_required()
    def get(self):
        try:
            # Starting point for cash tracking
            start_datetime = datetime(2026, 4, 22, 0, 0, 0)

            # Current date and time
            now = datetime.now()

            users = Users.query.all()

            results = []

            for user in users:

                # Get shop name through User -> Employee -> Shop relationship
                shop_name = (
                    user.employees.shops.shopname
                    if user.employees and user.employees.shops
                    else None
                )

                # Total cash sales up to this moment
                total_cash_sales = (
                    db.session.query(
                        func.coalesce(
                            func.sum(SalesPaymentMethods.amount_paid), 0
                        )
                    )
                    .join(
                        Sales,
                        Sales.sales_id == SalesPaymentMethods.sale_id
                    )
                    .filter(
                        Sales.user_id == user.users_id
                    )
                    .filter(
                        SalesPaymentMethods.payment_method == "cash"
                    )
                    .filter(
                        Sales.created_at >= start_datetime
                    )
                    .filter(
                        Sales.created_at <= now
                    )
                    .scalar()
                )

                # Total deposits up to this moment
                total_deposits = (
                    db.session.query(
                        func.coalesce(
                            func.sum(CashDeposits.amount), 0
                        )
                    )
                    .filter(
                        CashDeposits.user_id == user.users_id
                    )
                    .filter(
                        CashDeposits.created_at >= start_datetime
                    )
                    .filter(
                        CashDeposits.created_at <= now
                    )
                    .scalar()
                )

                # Current cash at hand
                cash_at_hand = max(
                    0,
                    float(total_cash_sales) - float(total_deposits)
                )

                results.append({
                    "user_id": user.users_id,
                    "username": user.username,
                    "shop_name": shop_name,
                    "cash_sales": float(total_cash_sales),
                    "deposits": float(total_deposits),
                    "cash_at_hand": cash_at_hand
                })

            # Sort by highest cash at hand
            results.sort(
                key=lambda x: x["cash_at_hand"],
                reverse=True
            )

            # Total cash at hand across all users
            total_cash_at_hand = sum(
                user["cash_at_hand"] for user in results
            )

            return {
                "generated_at": now.isoformat(),
                "tracking_from": start_datetime.isoformat(),
                "total_cash_at_hand": round(total_cash_at_hand, 2),
                "users": results
            }, 200

        except SQLAlchemyError as e:
            db.session.rollback()

            return {
                "error": "Failed to calculate cash at hand",
                "details": str(e)
            }, 500

        except Exception as e:
            return {
                "error": "Unexpected error",
                "details": str(e)
            }, 500


  
class TotalCashSalesByUser(Resource):
    @jwt_required()
    def get(self, username, shop_id):
        try:
            # ===============================
            # 1. Fixed start date (16/02/2026)
            # ===============================
            start_date = datetime.strptime("2026-04-22", "%Y-%m-%d").date()
            today = datetime.now().date()

            # ===============================
            # 2. Get user
            # ===============================
            user = Users.query.filter_by(username=username).first()
            if not user:
                return {"message": f"User '{username}' not found"}, 404

            # ===============================
            # 3. Total CASH sales from 31/01/2026
            # ===============================
            total_cash_sales = (
                db.session.query(
                    func.coalesce(func.sum(SalesPaymentMethods.amount_paid), 0)
                )
                .join(Sales, Sales.sales_id == SalesPaymentMethods.sale_id)
                .filter(Sales.user_id == user.users_id)
                .filter(Sales.shop_id == shop_id)
                .filter(SalesPaymentMethods.payment_method == "cash")
                .filter(func.date(Sales.created_at) >= start_date)
                .filter(func.date(Sales.created_at) <= today)
                .scalar()
            )

            # ===============================
            # 4. Total CASH deposits from 31/01/2026
            # ===============================
            total_deposits = (
                db.session.query(
                    func.coalesce(func.sum(CashDeposits.amount), 0)
                )
                .filter(CashDeposits.user_id == user.users_id)
                .filter(CashDeposits.shop_id == shop_id)
                .filter(func.date(CashDeposits.created_at) >= start_date)
                .filter(func.date(CashDeposits.created_at) <= today)
                .scalar()
            )

            # ===============================
            # 5. Net cash (cash - deposits)
            # ===============================
            net_cash = total_cash_sales - total_deposits
            net_cash = max(0, net_cash)

            return {
                "net_cash": f"Ksh {net_cash:,.2f}",
                "raw_net_cash": float(net_cash),
                "cash_sales": float(total_cash_sales),
                "deposits": float(total_deposits),
                "from_date": start_date.isoformat(),
                "to_date": today.isoformat()
            }, 200

        except SQLAlchemyError as e:
            db.session.rollback()
            return {
                "error": "Failed to calculate net cash",
                "details": str(e)
            }, 500




class GenerateSalesReport(Resource):
    @jwt_required()
    def post(self):
        import pandas as pd
        try:
            filters = request.get_json() or {}

            # Build the base query
            sales_query = Sales.query.order_by(Sales.created_at.desc()).join(Shops).join(Users)

            # Apply filters
            if filters.get('search_query'):
                search = f"%{filters['search_query']}%"
                sales_query = sales_query.filter(
                    Sales.customer_name.ilike(search) |
                    Users.username.ilike(search) |
                    Shops.shopname.ilike(search)
                )

            if filters.get('start_date'):
                try:
                    start_date = datetime.strptime(filters['start_date'], '%Y-%m-%d').date()
                    sales_query = sales_query.filter(db.func.date(Sales.created_at) >= start_date)
                except ValueError:
                    return {"error": "Invalid start date format. Use YYYY-MM-DD."}, 400

            if filters.get('end_date'):
                try:
                    end_date = datetime.strptime(filters['end_date'], '%Y-%m-%d').date()
                    sales_query = sales_query.filter(db.func.date(Sales.created_at) <= end_date)
                except ValueError:
                    return {"error": "Invalid end date format. Use YYYY-MM-DD."}, 400

            if filters.get('shopname'):
                sales_query = sales_query.filter(Shops.shopname.ilike(f"%{filters['shopname']}%"))

            if filters.get('status'):
                sales_query = sales_query.filter(Sales.status == filters['status'])

            sales = sales_query.all()

            # Create Excel file in memory
            output = BytesIO()
            
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                # === Sheet 1: All Sales ===
                all_shops_data = []
                for sale in sales:
                    user = Users.query.get(sale.user_id)
                    shop = Shops.query.get(sale.shop_id)
                    
                    # Get payment information including transaction codes
                    payment_methods = []
                    transaction_codes = []
                    total_amount = 0
                    
                    for payment in sale.payment:
                        total_amount += payment.amount_paid
                        payment_methods.append(payment.payment_method)
                        if payment.transaction_code:
                            transaction_codes.append(payment.transaction_code)
                    
                    for item in sale.items:
                        all_shops_data.append({
                            "Sale ID": sale.sales_id,
                            "Date": sale.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                            "User": user.username if user else "Unknown",
                            "Shop": shop.shopname if shop else "Unknown",
                            "Customer": sale.customer_name,
                            "Status": sale.status,
                            "Item Name": item.item_name,
                            "Quantity": item.quantity,
                            "Metric": item.metric,
                            "Unit Price": item.unit_price,
                            "Total Price": item.total_price,
                            "Batch Number": item.BatchNumber,
                            "Amount Paid": total_amount, 
                            "Balance": sale.balance,
                            "Payment Methods": ", ".join(set(payment_methods)),
                            "Transaction Codes": ", ".join(transaction_codes) if transaction_codes else "N/A",
                            "Note": sale.note or ""
                        })

                # Create DataFrame and write to Excel
                if all_shops_data:
                    df_all_shops = pd.DataFrame(all_shops_data)
                    df_all_shops.to_excel(writer, sheet_name='All Sales', index=False)
                    
                    # Auto-adjust columns' width
                    worksheet = writer.sheets['All Sales']
                    for idx, col in enumerate(df_all_shops.columns):
                        max_len = max(df_all_shops[col].astype(str).map(len).max(), len(col)) + 2
                        worksheet.set_column(idx, idx, max_len)
                else:
                    # Create empty sheet if no data
                    empty_df = pd.DataFrame(columns=[
                        "Sale ID", "Date", "User", "Shop", "Customer", "Status", 
                        "Item Name", "Quantity", "Metric", "Unit Price", "Total Price",
                        "Batch Number", "Amount Paid", "Balance", "Payment Methods", 
                        "Transaction Codes", "Note"
                    ])
                    empty_df.to_excel(writer, sheet_name='All Sales', index=False)

                # === Sheet 2: Item Details ===
                detailed_items_data = []
                for sale in sales:
                    user = Users.query.get(sale.user_id)
                    shop = Shops.query.get(sale.shop_id)
                    for item in sale.items:
                        detailed_items_data.append({
                            "Sale ID": sale.sales_id,
                            "Date": sale.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                            "Shop": shop.shopname if shop else "Unknown",
                            "User": user.username if user else "Unknown",
                            "Customer": sale.customer_name,
                            "Status": sale.status,
                            "Item Name": item.item_name,
                            "Quantity": item.quantity,
                            "Metric": item.metric,
                            "Unit Price": item.unit_price,
                            "Total Price": item.total_price,
                            "Batch Number": item.BatchNumber,
                            "Cost of Sale": item.Cost_of_sale,
                            "Purchase Account": item.Purchase_account,
                            "Payment Methods": ", ".join(set(p.payment_method for p in sale.payment)),
                            "Note": sale.note or ""
                        })

                if detailed_items_data:
                    df_detailed = pd.DataFrame(detailed_items_data)
                    df_detailed.to_excel(writer, sheet_name='Item Details', index=False)
                    
                    # Auto-adjust columns' width
                    worksheet = writer.sheets['Item Details']
                    for idx, col in enumerate(df_detailed.columns):
                        max_len = max(df_detailed[col].astype(str).map(len).max(), len(col)) + 2
                        worksheet.set_column(idx, idx, max_len)
                else:
                    # Create empty sheet if no data
                    empty_df = pd.DataFrame(columns=[
                        "Sale ID", "Date", "Shop", "User", "Customer", "Status",
                        "Item Name", "Quantity", "Metric", "Unit Price", "Total Price",
                        "Batch Number", "Cost of Sale", "Purchase Account", "Payment Methods", "Note"
                    ])
                    empty_df.to_excel(writer, sheet_name='Item Details', index=False)

                # === Sheet 3: Summary Statistics ===
                summary_stats = []
                shop_totals = {}
                
                if sales:
                    for sale in sales:
                        shop = Shops.query.get(sale.shop_id)
                        name = shop.shopname if shop else f"Shop_{sale.shop_id}"
                        total = sum(p.amount_paid for p in sale.payment)
                        if name not in shop_totals:
                            shop_totals[name] = {'sales': 0, 'txs': 0, 'items': 0}
                        shop_totals[name]['sales'] += total
                        shop_totals[name]['txs'] += 1
                        shop_totals[name]['items'] += len(sale.items)

                    for name, t in shop_totals.items():
                        summary_stats.append({
                            "Shop": name,
                            "Total Sales": t['sales'],
                            "Transactions": t['txs'],
                            "Items Sold": t['items']
                        })

                    summary_stats.append({
                        "Shop": "ALL SHOPS",
                        "Total Sales": sum(s['sales'] for s in shop_totals.values()),
                        "Transactions": sum(s['txs'] for s in shop_totals.values()),
                        "Items Sold": sum(s['items'] for s in shop_totals.values()),
                    })
                else:
                    # Add empty summary when no data
                    summary_stats.append({
                        "Shop": "No Data",
                        "Total Sales": 0,
                        "Transactions": 0,
                        "Items Sold": 0
                    })

                df_summary = pd.DataFrame(summary_stats)
                df_summary.to_excel(writer, sheet_name='Summary Statistics', index=False)
                
                # Auto-adjust columns' width
                worksheet = writer.sheets['Summary Statistics']
                for idx, col in enumerate(df_summary.columns):
                    max_len = max(df_summary[col].astype(str).map(len).max(), len(col)) + 2
                    worksheet.set_column(idx, idx, max_len)

            # Get the Excel data as bytes
            excel_data = output.getvalue()
            output.close()

            # Create response with direct bytes to avoid fileno error
            response = Response(
                excel_data,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                headers={
                    "Content-Disposition": f"attachment; filename=sales_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    "Content-Length": str(len(excel_data))
                }
            )
            
            return response

        except Exception as e:
            return {"error": f"Failed to generate report: {str(e)}"}, 500

class ItemsSoldSummary(Resource):
    @jwt_required()
    def get(self, shop_id=None):
        try:
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')

            try:
                if start_date:
                    start_date = datetime.strptime(start_date, '%Y-%m-%d')
                if end_date:
                    end_date = datetime.strptime(end_date, '%Y-%m-%d')
            except ValueError:
                return {"error": "Invalid date format. Use YYYY-MM-DD"}, 400

            query = (
                db.session.query(
                    SoldItem.item_name,
                    SoldItem.metric,
                    func.sum(SoldItem.quantity).label("total_sold"),
                    func.sum(SoldItem.total_price).label("total_amount"),
                )
                .join(Sales, SoldItem.sales_id == Sales.sales_id)
            )

            if shop_id is not None:
                query = query.filter(Sales.shop_id == shop_id)

            if start_date:
                query = query.filter(Sales.created_at >= start_date)

            if end_date:
                query = query.filter(Sales.created_at <= end_date)

            result = (
                query.group_by(
                    SoldItem.item_name,
                    SoldItem.metric
                )
                .all()
            )

            sold_items_summary = [
                {
                    "item_name": item_name,
                    "metric": metric,
                    "total_sold": round(float(total_sold or 0), 2),
                    "amount_paid": round(float(total_amount or 0), 2),
                }
                for item_name, metric, total_sold, total_amount in result
            ]

            response = {
                "shop_id": shop_id,
                "total_items_sold": len(sold_items_summary),
                "items": sold_items_summary
            }

            return make_response(jsonify(response), 200)

        except SQLAlchemyError as e:
            db.session.rollback()
            return {
                "error": "An error occurred while fetching sold item data",
                "details": str(e)
            }, 500
            
class DeliverySalesSummary(Resource):
    @jwt_required()
    def get(self, shop_id=None):
        try:
            # Query params
            start_date = request.args.get('start_date')  # YYYY-MM-DD
            end_date = request.args.get('end_date')      # YYYY-MM-DD

            # Validate dates
            try:
                if start_date:
                    start_date = datetime.strptime(start_date, '%Y-%m-%d')

                if end_date:
                    end_date = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            except ValueError:
                return {
                    "error": "Invalid date format. Use YYYY-MM-DD"
                }, 400

            # Base query
            query = db.session.query(
                SoldItem.item_name,
                SoldItem.metric,
                Shops.shopname,
                func.sum(SoldItem.quantity).label("quantity_sold"),
                func.sum(SoldItem.total_price).label("total_amount_sold")
            ).join(
                Sales, SoldItem.sales_id == Sales.sales_id
            ).join(
                Shops, Sales.shop_id == Shops.shops_id
            ).filter(
                Sales.delivery == True
            )

            # Shop filter
            if shop_id is not None:
                query = query.filter(Sales.shop_id == shop_id)

            # Date filters
            if start_date:
                query = query.filter(Sales.created_at >= start_date)

            if end_date:
                query = query.filter(Sales.created_at < end_date)

            # Group results
            result = query.group_by(
                SoldItem.item_name,
                SoldItem.metric,
                Shops.shopname
            ).all()

            # Format response
            items = [
                {
                    "item_name": item_name,
                    "shop": shopname,
                    "metric": metric,
                    "quantity_sold": round(quantity_sold or 0, 2),
                    "total_amount_sold": round(total_amount_sold or 0, 2)
                }
                for item_name, metric, shopname, quantity_sold, total_amount_sold in result
            ]

            response = {
                "shop_id": shop_id,
                "total_items": len(items),
                "items": items
            }

            return make_response(jsonify(response), 200)

        except SQLAlchemyError as e:
            db.session.rollback()

            return {
                "error": "An error occurred while fetching delivery sales summary",
                "details": str(e)
            }, 500


class ProductEarningsSummary(Resource):
    @jwt_required()
    def get(self, shop_id=None):
        try:
            # Query params
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')

            try:
                if start_date:
                    start_date = datetime.strptime(start_date, '%Y-%m-%d')
                if end_date:
                    end_date = datetime.strptime(end_date, '%Y-%m-%d')
            except ValueError:
                return {"error": "Invalid date format. Use YYYY-MM-DD"}, 400

            query = db.session.query(
                SoldItem.item_name,
                SoldItem.metric,
                func.sum(SoldItem.quantity).label("total_quantity_sold"),
                func.sum(SoldItem.total_price).label("total_revenue"),
                func.avg(SoldItem.unit_price).label("average_unit_price")
            ).join(Sales, SoldItem.sales_id == Sales.sales_id)

            if shop_id is not None:
                query = query.filter(Sales.shop_id == shop_id)
            if start_date:
                query = query.filter(Sales.created_at >= start_date)
            if end_date:
                query = query.filter(Sales.created_at <= end_date.replace(hour=23, minute=59, second=59))

            query = query.group_by(SoldItem.item_name, SoldItem.metric)
            query = query.order_by(func.sum(SoldItem.total_price).desc())
            result = query.all()

            product_earnings_summary = [
                {
                    "item_name": item_name,
                    "metric": metric,
                    "total_quantity_sold": round(total_quantity_sold, 2),
                    "total_revenue": round(total_revenue, 2),
                    "average_unit_price": round(average_unit_price, 2)
                }
                for item_name, metric, total_quantity_sold, total_revenue, average_unit_price in result
            ]

            response = {
                "shop_id": shop_id,
                "period": {
                    "start_date": start_date.strftime('%Y-%m-%d') if start_date else None,
                    "end_date": end_date.strftime('%Y-%m-%d') if end_date else None
                },
                "total_products": len(product_earnings_summary),
                "total_revenue": round(sum(p["total_revenue"] for p in product_earnings_summary), 2),
                "total_quantity_sold": round(sum(p["total_quantity_sold"] for p in product_earnings_summary), 2),
                "products": product_earnings_summary
            }

            return make_response(jsonify(response), 200)

        except SQLAlchemyError as e:
            db.session.rollback()
            return {"error": "Database error", "details": str(e)}, 500


# ---------------- Categories Summary ----------------
class CategoryEarningsSummary(Resource):
    @jwt_required()
    def get(self, shop_id=None):
        try:
            # Support both ?start_date=...&end_date=... and ?start=...&end=...
            start_date = request.args.get('start_date') or request.args.get('start')
            end_date = request.args.get('end_date') or request.args.get('end')

            try:
                if start_date:
                    start_date = datetime.strptime(start_date, '%Y-%m-%d')
                if end_date:
                    end_date = datetime.strptime(end_date, '%Y-%m-%d')
            except ValueError:
                return {"error": "Invalid date format. Use YYYY-MM-DD"}, 400

            category_query = db.session.query(
                StockItems.category,
                func.sum(SoldItem.quantity).label("total_quantity_sold"),
                func.sum(SoldItem.total_price).label("total_revenue")
            ).join(SoldItem, SoldItem.item_name == StockItems.item_name) \
             .join(Sales, SoldItem.sales_id == Sales.sales_id)

            if shop_id is not None:
                category_query = category_query.filter(Sales.shop_id == shop_id)
            if start_date:
                category_query = category_query.filter(Sales.created_at >= start_date)
            if end_date:
                category_query = category_query.filter(Sales.created_at <= end_date.replace(hour=23, minute=59, second=59))

            category_query = category_query.group_by(StockItems.category)
            category_result = category_query.all()

            category_summary = [
                {
                    "category": category or "Uncategorized",
                    "total_quantity_sold": round(total_quantity_sold, 2),
                    "total_revenue": round(total_revenue, 2)
                }
                for category, total_quantity_sold, total_revenue in category_result
            ]

            response = {
                "shop_id": shop_id,
                "period": {
                    "start_date": start_date.strftime('%Y-%m-%d') if start_date else None,
                    "end_date": end_date.strftime('%Y-%m-%d') if end_date else None
                },
                "total_categories": len(category_summary),
                "total_revenue": round(sum(c["total_revenue"] for c in category_summary), 2),
                "total_quantity_sold": round(sum(c["total_quantity_sold"] for c in category_summary), 2),
                "categories": category_summary
            }

            return make_response(jsonify(response), 200)

        except SQLAlchemyError as e:
            db.session.rollback()
            return {"error": "Database error", "details": str(e)}, 500



class SasaPaySaleResource(Resource):
    @jwt_required()
    def post(self):
        """Handle SasaPay-only sales with merchant mapping - Pending callback"""
        data = request.get_json()
        current_user_id = get_jwt_identity()
        new_sale = None
        payment_result = None

        # ===== VALIDATION =====
        required_fields = [
            'shop_id', 'customer_name', 'customer_number',
            'items', 'status', 'delivery', 'sasapay_payment'
        ]
        if not all(field in data for field in required_fields):
            return {
                'message': 'Missing required fields',
                'missing': [f for f in required_fields if f not in data]
            }, 400

        try:
            shop_id = int(data['shop_id'])
            status = data['status'].lower()
            balance = float(data.get('balance', 0))
            delivery = bool(data.get('delivery', 0))
            promocode = data.get('promocode', '')
            creditor_id = data.get('creditor_id')
            created_at = datetime.strptime(data['sale_date'], "%Y-%m-%d") if 'sale_date' in data else datetime.utcnow()

            # SasaPay payment details
            sasapay_payment = data['sasapay_payment']
            required_sasapay_fields = ['amount', 'transaction_reference', 'sender_account_number', 
                                      'account_reference', 'network_code']
            
            for field in required_sasapay_fields:
                if field not in sasapay_payment:
                    return {
                        'message': f'Missing required SasaPay field: {field}',
                        'required_fields': required_sasapay_fields
                    }, 400

            # Validate items
            if not isinstance(data['items'], list) or not data['items']:
                return {'message': 'Items must be a non-empty list'}, 400

            items = []
            total_price = 0.0
            total_quantity = 0.0
            purchase_account = 0.0

            for item in data['items']:
                item_fields = ['item_name', 'quantity', 'metric', 'unit_price']
                if not all(field in item for field in item_fields):
                    return {
                        'message': 'Missing required item fields',
                        'missing': [f for f in item_fields if f not in item]
                    }, 400

                metric = item['metric'].strip().lower()
                if metric not in ['item', 'kg', 'ltrs']:
                    return {
                        'message': f"Invalid metric '{metric}' for item '{item['item_name']}'. Must be one of: item, kg, ltrs",
                        'invalid_item': item
                    }, 400

                items.append({
                    'item_name': item['item_name'],
                    'quantity': float(item['quantity']),
                    'metric': metric,
                    'unit_price': float(item['unit_price']),
                    'total_price': float(item['total_price']) 
                })
                total_quantity += float(item['quantity'])
                total_price += float(item['total_price'])

        except (ValueError, KeyError, TypeError) as e:
            return {'message': f'Invalid data format: {str(e)}'}, 400

        # ===== CREDITOR VALIDATION =====
        creditor = None
        if creditor_id:
            try:
                creditor_id = int(creditor_id)
                creditor = Creditors.query.filter_by(id=creditor_id, shop_id=shop_id).first()
                if not creditor:
                    return {'message': f'Creditor with ID {creditor_id} not found for this shop'}, 404
                
                if status not in ["unpaid", "partially_paid"]:
                    return {'message': 'Creditor sales must have status "unpaid" or "partially paid"'}, 400
                    
            except (ValueError, TypeError):
                return {'message': 'Invalid creditor ID format'}, 400

        # ===== SHOP TO SASAPAY MERCHANT MAPPING =====
        shop_to_merchant_mapping = {
            2: "570257",   # Kuku Zetu - Mirema
            5: "577960",   # Kuku Zetu - Lumumba Drive
            3: "577480",   # Kuku Zetu - Zimmerman
            8: "577668",   # Kukuzetu - Ngoingwa Stockist
            1: "577666",   # KUKUZETU - TRM
            20: "222333",   # Kukuzetu - Kasarani Equity
            19: "577123",   # Kukuzetu - Kasarani Maternity
            16: "577556",   # Kukuzetu - Turi
            9: "570257",   # Kuku Zetu - Mirema
        }

        # Get environment and determine merchant code
        environment = os.getenv("SASAPAY_ENVIRONMENT", "sandbox")
        requested_merchant_code = shop_to_merchant_mapping.get(shop_id)
        
        # ===== SANDBOX OVERRIDE =====
        if environment == "sandbox":
            merchant_code = os.getenv("SASAPAY_SANDBOX_MERCHANT_CODE", "600980")
            current_app.logger.info(f"[SASAPAY] Sandbox mode: Using test merchant {merchant_code} for shop {shop_id}")
        else:
            merchant_code = requested_merchant_code
            if not merchant_code:
                return {
                    'message': f'No SasaPay merchant configured for shop {shop_id}',
                    'shop_id': shop_id
                }, 400

        # ===== STOCK CHECK (Reserve only, don't deduct yet) =====
        stock_errors = []
        batch_reservations = []
        livestock_reservations = []
        stock_ids_used = []
        sold_items = []
        livestock_deductions = []

        try:
            for item in items:
                batches = ShopStockV2.query.filter(
                    ShopStockV2.itemname == item['item_name'],
                    ShopStockV2.shop_id == shop_id,
                    ShopStockV2.quantity > 0
                ).order_by(ShopStockV2.BatchNumber).all()

                remaining_qty = item['quantity']
                item_batch_deductions = []
                item_stock_ids = []
                item_purchase_account = 0.0
                item_livestock_deduction = 0.0

                # Check batch stock availability
                for batch in batches:
                    if remaining_qty <= 0:
                        break

                    deduct_qty = min(batch.quantity, remaining_qty)
                    remaining_qty -= deduct_qty
                    
                    # Store reservation data (don't deduct yet)
                    item_batch_deductions.append({
                        'batch_id': batch.stockv2_id,
                        'batch_number': batch.BatchNumber,
                        'deduct_qty': deduct_qty,
                        'original_quantity': batch.quantity
                    })
                    item_stock_ids.append(str(batch.stockv2_id))

                    inventory = InventoryV2.query.filter_by(inventoryV2_id=batch.inventoryv2_id).first()
                    if inventory:
                        item_purchase_account += inventory.unitCost * deduct_qty

                # Check livestock availability if needed
                if remaining_qty > 0:
                    livestock_entry = LiveStock.query.filter(
                        LiveStock.shop_id == shop_id,
                        func.lower(LiveStock.item_name) == item['item_name'].lower()
                    ).first()

                    if livestock_entry and livestock_entry.current_quantity > 0:
                        deduct_qty = min(livestock_entry.current_quantity, remaining_qty)
                        remaining_qty -= deduct_qty
                        item_livestock_deduction = deduct_qty
                        
                        livestock_reservations.append({
                            'livestock_id': livestock_entry.liveStock_id,
                            'item_name': item['item_name'],
                            'deduct_qty': deduct_qty,
                            'original_quantity': livestock_entry.current_quantity,
                            'original_clock_out': livestock_entry.clock_out_quantity
                        })
                        
                        livestock_deductions.append({
                            'item_name': item['item_name'],
                            'quantity': deduct_qty,
                            'original_current': livestock_entry.current_quantity,
                            'new_current': livestock_entry.current_quantity - deduct_qty
                        })

                if remaining_qty > 0:
                    stock_errors.append(
                        f"Insufficient stock for {item['item_name']}. Needed {item['quantity']}, available {item['quantity'] - remaining_qty}"
                    )
                    continue

                if item_batch_deductions:
                    batch_reservations.extend(item_batch_deductions)
                    stock_ids_used.extend(item_stock_ids)

                purchase_account += item_purchase_account

                sold_items.append({
                    'item_name': item['item_name'],
                    'quantity': item['quantity'],
                    'metric': item['metric'],
                    'unit_price': item['unit_price'],
                    'total_price': item['total_price'],
                    'BatchNumber': ", ".join([f"Batch {r['batch_number']} ({r['deduct_qty']})" for r in item_batch_deductions]) if item_batch_deductions else "From Livestock",
                    'stockv2_id': item_stock_ids[0] if item_stock_ids else None,
                    'Cost_of_sale': item['total_price'],
                    'Purchase_account': item_purchase_account,
                    'LivestockDeduction': item_livestock_deduction,
                    'batch_reservations': item_batch_deductions
                })

            if stock_errors:
                return {'message': 'Stock processing failed', 'errors': stock_errors}, 400

        except Exception as e:
            current_app.logger.error(f"[SASAPAY] Stock check failed: {str(e)}")
            return {'message': 'Stock processing failed', 'error': str(e)}, 500

        # ===== PROCESS SASAPAY PAYMENT =====
        sasapay_amount = float(sasapay_payment['amount'])
        total_sale_amount = total_price
        
        # Auto-discount logic
        auto_discount_applied = False
        balance_percentage = 0
        discount_amount = 0
        final_balance = balance
        
        if balance > 0 and status == "paid":
            balance_percentage = (balance / total_sale_amount) * 100 if total_sale_amount > 0 else 0
            if balance_percentage <= 3.0:
                discount_amount = balance
                auto_discount_applied = True
                final_balance = 0
                current_app.logger.info(f"[SASAPAY] Auto-discount applied: {discount_amount} ({balance_percentage:.2f}%)")

        try:
            # ===== INITIATE SASAPAY PAYMENT =====
            sasapay_service = SasaPayPaymentService()
            
            callback_url = sasapay_payment.get('callback_url')
            if not callback_url:
                merchant_callback_key = f"SASAPAY_MERCHANT_{merchant_code}_CALLBACK_URL"
                callback_url = os.getenv(merchant_callback_key)
                
                if not callback_url:
                    callback_url = sasapay_service._get_merchant_callback_url(merchant_code)
            
            current_app.logger.info(f"[SASAPAY] Using callback URL: {callback_url}")
            
            # Initiate payment
            payment_result = sasapay_service.initiate_payment(
                merchant_code=merchant_code,
                transaction_reference=sasapay_payment['transaction_reference'],
                amount=str(sasapay_amount),
                sender_account_number=sasapay_payment['sender_account_number'],
                receiver_merchant_code=sasapay_payment.get('receiver_merchant_code', merchant_code),
                account_reference=sasapay_payment['account_reference'],
                network_code=sasapay_payment['network_code'],
                callback_url=callback_url,
                reason=sasapay_payment.get('reason', f'Sale for shop {shop_id}')
            )

            if not payment_result or not payment_result.get('status'):
                return {
                    'message': 'SasaPay payment initiation failed',
                    'error': payment_result.get('message', 'Unknown error'),
                    'payment_details': payment_result
                }, 400

            # ===== CREATE SALE WITH STATUS 'pending' =====
            new_sale = Sales(
                user_id=current_user_id,
                shop_id=shop_id,
                customer_name=data['customer_name'],
                customer_number=data['customer_number'],
                status='pending',  # Using the new 'pending' status
                delivery=delivery,
                created_at=created_at,
                balance=final_balance,
                promocode=promocode,
                note=f"SasaPay payment initiated - awaiting confirmation. Ref: {sasapay_payment['transaction_reference']}"
            )
            db.session.add(new_sale)
            db.session.flush()

            # ===== CREDITOR BALANCE UPDATE (if creditor) =====
            if creditor:
                creditor.total_credit = (creditor.total_credit or 0) + total_sale_amount
                creditor.credit_amount = (creditor.credit_amount or 0) + total_sale_amount
                db.session.add(creditor)

            # ===== SAVE SOLD ITEMS =====
            for item in sold_items:
                total_price_item = float(item['total_price'])
                fractional_part = round(total_price_item - int(total_price_item), 2)

                db.session.add(SoldItem(
                    sales_id=new_sale.sales_id,
                    item_name=item['item_name'],
                    quantity=item['quantity'],
                    metric=item['metric'],
                    unit_price=item['unit_price'],
                    total_price=total_price_item,
                    BatchNumber=item['BatchNumber'],
                    stockv2_id=item['stockv2_id'] or 0,
                    Cost_of_sale=item['Cost_of_sale'],
                    Purchase_account=item['Purchase_account'],
                    LivestockDeduction=item['LivestockDeduction'],
                    round_off=fractional_part
                ))

            # ===== SAVE PAYMENT METHOD WITH RESERVATION DATA =====
            checkout_request_id = payment_result.get('data', {}).get('CheckoutRequestID')
            
            # Store all reservation data in payment method's callback_data field
            reservation_data = {
                'batch_reservations': batch_reservations,
                'livestock_reservations': livestock_reservations,
                'sold_items': sold_items,
                'customer_name': data['customer_name'],
                'customer_number': data['customer_number'],
                'creditor_id': creditor_id,
                'auto_discount': {
                    'applied': auto_discount_applied,
                    'amount': discount_amount,
                    'percentage': balance_percentage
                } if auto_discount_applied else None,
                'purchase_account': purchase_account,
                'total_amount': total_sale_amount
            }

            payment_method = SalesPaymentMethods(
                sale_id=new_sale.sales_id,
                payment_method='sasapay',
                amount_paid=sasapay_amount,
                discount=discount_amount,
                balance=final_balance,
                transaction_code=sasapay_payment['transaction_reference'],
                checkout_request_id=checkout_request_id,
                merchant_code=merchant_code,
                payment_status='pending',
                callback_data=json.dumps(reservation_data),  # Store reservations here
                created_at=created_at
            )
            db.session.add(payment_method)

            # ===== SAVE CUSTOMER =====
            if data['customer_name'] or data['customer_number']:
                db.session.add(Customers(
                    customer_name=data['customer_name'],
                    customer_number=data['customer_number'],
                    shop_id=shop_id,
                    sales_id=new_sale.sales_id,
                    user_id=current_user_id,
                    item=", ".join([item['item_name'] for item in items]),
                    amount_paid=sasapay_amount,
                    payment_method="sasapay",
                    created_at=created_at
                ))

            # ===== COMMIT DATABASE =====
            db.session.commit()

            # ===== RESPONSE =====
            response_data = {
                'message': 'SasaPay payment initiated. Awaiting confirmation callback.',
                'sale_id': new_sale.sales_id,
                'status': 'pending',
                'financial': {
                    'total': total_sale_amount,
                    'paid': sasapay_amount,
                    'balance': final_balance,
                    'purchase_cost': purchase_account
                },
                'sasapay_payment': {
                    'status': 'initiated',
                    'checkout_request_id': checkout_request_id,
                    'merchant_code': merchant_code,
                    'merchant_reference': payment_result.get('data', {}).get('MerchantRequestID'),
                    'amount': sasapay_amount,
                    'message': payment_result.get('data', {}).get('ResponseDescription') or 'STK push sent to customer',
                    'customer_message': payment_result.get('data', {}).get('CustomerMessage'),
                    'payment_gateway': payment_result.get('data', {}).get('PaymentGateway')
                },
                'items': {
                    'count': len(items),
                    'details': sold_items
                },
                'stock_reserved': {
                    'shop_stock': len(batch_reservations),
                    'livestock': len(livestock_reservations)
                },
                'delivery': delivery,
                'shop_id': shop_id,
                'environment': environment,
                'next_steps': 'Wait for callback to confirm payment and finalize sale'
            }

            if auto_discount_applied:
                response_data['auto_discount'] = {
                    'applied': True,
                    'amount': discount_amount,
                    'reason': f'Balance of {discount_amount} ({balance_percentage:.2f}% of total) was within 3% threshold and converted to discount'
                }

            if creditor:
                response_data['creditor'] = {
                    'creditor_id': creditor.id,
                    'creditor_name': creditor.name,
                    'previous_total_credit': creditor.total_credit - total_sale_amount,
                    'new_total_credit': creditor.total_credit
                }

            return response_data, 201

        except Exception as e:
            db.session.rollback()
            error_msg = str(e)
            clean_error = ''.join(char for char in error_msg if ord(char) < 128)
            
            if clean_error != error_msg:
                current_app.logger.error(f"Original error with unicode: {error_msg}")
                error_msg = clean_error
            
            current_app.logger.error(f"SasaPay sale transaction failed: {error_msg}", exc_info=True)
            
            return {
                'message': 'Transaction failed',
                'error': error_msg,
                'debug_info': {
                    'sale_id': new_sale.sales_id if new_sale else "Not created",
                    'merchant_code': merchant_code if 'merchant_code' in locals() else "Unknown",
                    'checkout_request_id': payment_result.get('data', {}).get('CheckoutRequestID') if payment_result else None,
                    'delivery': delivery if 'delivery' in locals() else False,
                    'creditor_id': creditor_id if 'creditor_id' in locals() else None,
                    'environment': environment if 'environment' in locals() else "Unknown"
                }
            }, 500
            
            

class SasaPayPaymentStatusResource(Resource):
    @jwt_required()
    def get(self, checkout_request_id):
        """
        Check the status of a SasaPay payment by checkout_request_id.
        GET /api/sasapay/payment/status/<checkout_request_id>
        """
        try:
            if not checkout_request_id:
                return {
                    'status': 'error',
                    'message': 'Checkout request ID is required'
                }, 400

            # Find the payment method
            payment_method = SalesPaymentMethods.query.filter_by(
                checkout_request_id=checkout_request_id
            ).first()

            if not payment_method:
                return {
                    'status': 'error',
                    'message': 'Payment not found',
                    'checkout_request_id': checkout_request_id
                }, 404

            # Get the sale for additional info
            sale = payment_method.related_sale if payment_method.related_sale else None

            response_data = {
                'status': 'success',
                'payment_status': payment_method.payment_status,  # pending, success, failed
                'checkout_request_id': payment_method.checkout_request_id,
                'amount_paid': payment_method.amount_paid,
                'transaction_code': payment_method.transaction_code,
                'sasapay_transaction_id': payment_method.sasapay_transaction_id,
                'result_code': payment_method.result_code,
                'result_desc': payment_method.result_desc,
                'failure_reason': payment_method.failure_reason,
                'created_at': payment_method.created_at.isoformat() if payment_method.created_at else None,
                'callback_received_at': payment_method.callback_received_at.isoformat() if payment_method.callback_received_at else None,
            }

            # Add sale info if available
            if sale:
                response_data['sale'] = {
                    'sale_id': sale.sales_id,
                    'status': sale.status,
                    'total_amount': sale.total_amount if hasattr(sale, 'total_amount') else None,
                    'balance': sale.balance,
                    'shop_id': sale.shop_id,
                    'customer_name': sale.customer_name,
                    'customer_number': sale.customer_number
                }

            return response_data, 200

        except Exception as e:
            current_app.logger.error(f"[SASAPAY] Error checking payment status: {str(e)}")
            return {
                'status': 'error',
                'message': f'Error checking payment status: {str(e)}'
            }, 500



# Add these imports near the top of the file:
from sqlalchemy import func
import calendar

class GetSalesGraphData(Resource):
    @jwt_required()
    def get(self):
        """
        Sales data endpoint — aggregated in SQL instead of in Python.
        Now includes total_paid and total_unpaid calculations based on actual payments vs sale totals.
        """
        try:
            shop_id = request.args.get('shop_id')
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            payment_method = request.args.get('payment_method')
            year = request.args.get('year')

            shop_name = "All Shops"
            if shop_id:
                shop = Shops.query.filter_by(shops_id=shop_id).first()
                if not shop:
                    return {"error": "Shop not found"}, 404
                shop_name = shop.shopname

            # --- Shared filters, applied identically to every aggregate query ---
            def apply_common_filters(query, date_column):
                if shop_id:
                    query = query.filter(Sales.shop_id == shop_id)
                if start_date:
                    query = query.filter(date_column >= start_date)
                if end_date:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
                    query = query.filter(date_column < end_date_obj)
                if year:
                    query = query.filter(db.extract('year', date_column) == int(year))
                return query

            yr = func.extract('year', Sales.created_at)
            mo = func.extract('month', Sales.created_at)

            # --- 1. Monthly summary: sales count + total income + total paid + total unpaid ---
            # Calculate total sale amounts from items
            sale_totals_q = (
                db.session.query(
                    yr.label('yr'), mo.label('mo'),
                    Sales.sales_id,
                    func.coalesce(func.sum(SoldItem.total_price), 0).label('sale_total')
                )
                .join(SoldItem, SoldItem.sales_id == Sales.sales_id)
            )
            sale_totals_q = apply_common_filters(sale_totals_q, Sales.created_at)
            sale_totals = sale_totals_q.group_by('yr', 'mo', Sales.sales_id).subquery()

            # Calculate total paid per sale from payment methods
            paid_totals_q = (
                db.session.query(
                    yr.label('yr'), mo.label('mo'),
                    Sales.sales_id,
                    func.coalesce(func.sum(SalesPaymentMethods.amount_paid), 0).label('total_paid')
                )
                .join(SalesPaymentMethods, SalesPaymentMethods.sale_id == Sales.sales_id)
            )
            paid_totals_q = apply_common_filters(paid_totals_q, Sales.created_at)
            paid_totals = paid_totals_q.group_by('yr', 'mo', Sales.sales_id).subquery()

            # Combine sale totals and paid amounts
            combined_q = (
                db.session.query(
                    sale_totals.c.yr.label('yr'),
                    sale_totals.c.mo.label('mo'),
                    func.count().label('sales_count'),
                    func.coalesce(func.sum(sale_totals.c.sale_total), 0).label('total_income'),
                    func.coalesce(func.sum(paid_totals.c.total_paid), 0).label('total_paid'),
                    func.coalesce(func.sum(sale_totals.c.sale_total - paid_totals.c.total_paid), 0).label('total_unpaid')
                )
                .outerjoin(
                    paid_totals,
                    (sale_totals.c.sales_id == paid_totals.c.sales_id) &
                    (sale_totals.c.yr == paid_totals.c.yr) &
                    (sale_totals.c.mo == paid_totals.c.mo)
                )
                .group_by(sale_totals.c.yr, sale_totals.c.mo)
                .order_by(sale_totals.c.yr, sale_totals.c.mo)
            )

            summary_rows = combined_q.all()

            if not summary_rows:
                return {"message": "No sales data found", "data": []}, 200

            def month_key(y, m):
                return f"{int(y):04d}-{int(m):02d}"

            def month_label(y, m):
                return f"{calendar.month_name[int(m)]} {int(y)}"

            months_order = [month_key(r.yr, r.mo) for r in summary_rows]
            monthly = {}
            for r in summary_rows:
                mk = month_key(r.yr, r.mo)
                monthly[mk] = {
                    'month': month_label(r.yr, r.mo),
                    'month_key': mk,
                    'sales_count': r.sales_count,
                    'total_income': float(r.total_income or 0),
                    'total_paid': float(r.total_paid or 0),
                    'total_unpaid': float(r.total_unpaid or 0),
                    'shops': [],
                    'payment_methods': [],
                    'top_items': [],
                    'status_distribution': {},
                }

            # --- 2. Shop breakdown, per month ---
            # Calculate sale totals per shop
            shop_sale_totals_q = (
                db.session.query(
                    yr.label('yr'), mo.label('mo'),
                    Shops.shopname.label('shop_name'),
                    Shops.shops_id,
                    Sales.sales_id,
                    func.coalesce(func.sum(SoldItem.total_price), 0).label('sale_total')
                )
                .join(Shops, Shops.shops_id == Sales.shop_id)
                .join(SoldItem, SoldItem.sales_id == Sales.sales_id)
            )
            shop_sale_totals_q = apply_common_filters(shop_sale_totals_q, Sales.created_at)
            shop_sale_totals = shop_sale_totals_q.group_by('yr', 'mo', 'shop_name', Shops.shops_id, Sales.sales_id).subquery()

            # Calculate paid amounts per shop
            shop_paid_totals_q = (
                db.session.query(
                    yr.label('yr'), mo.label('mo'),
                    Shops.shopname.label('shop_name'),
                    Shops.shops_id,
                    Sales.sales_id,
                    func.coalesce(func.sum(SalesPaymentMethods.amount_paid), 0).label('total_paid')
                )
                .join(Shops, Shops.shops_id == Sales.shop_id)
                .join(SalesPaymentMethods, SalesPaymentMethods.sale_id == Sales.sales_id)
            )
            shop_paid_totals_q = apply_common_filters(shop_paid_totals_q, Sales.created_at)
            shop_paid_totals = shop_paid_totals_q.group_by('yr', 'mo', 'shop_name', Shops.shops_id, Sales.sales_id).subquery()

            # Combine shop totals
            shop_combined_q = (
                db.session.query(
                    shop_sale_totals.c.yr.label('yr'),
                    shop_sale_totals.c.mo.label('mo'),
                    shop_sale_totals.c.shop_name.label('shop_name'),
                    func.count().label('sales_count'),
                    func.coalesce(func.sum(shop_sale_totals.c.sale_total), 0).label('income'),
                    func.coalesce(func.sum(shop_paid_totals.c.total_paid), 0).label('paid'),
                    func.coalesce(func.sum(shop_sale_totals.c.sale_total - shop_paid_totals.c.total_paid), 0).label('unpaid')
                )
                .outerjoin(
                    shop_paid_totals,
                    (shop_sale_totals.c.sales_id == shop_paid_totals.c.sales_id) &
                    (shop_sale_totals.c.yr == shop_paid_totals.c.yr) &
                    (shop_sale_totals.c.mo == shop_paid_totals.c.mo) &
                    (shop_sale_totals.c.shops_id == shop_paid_totals.c.shops_id)
                )
                .group_by(shop_sale_totals.c.yr, shop_sale_totals.c.mo, shop_sale_totals.c.shop_name)
                .order_by(shop_sale_totals.c.yr, shop_sale_totals.c.mo)
            )

            for r in shop_combined_q.all():
                mk = month_key(r.yr, r.mo)
                if mk not in monthly:
                    continue
                income = float(r.income or 0)
                paid = float(r.paid or 0)
                unpaid = float(r.unpaid or 0)
                total = monthly[mk]['total_income']
                monthly[mk]['shops'].append({
                    'name': r.shop_name,
                    'income': round(income, 2),
                    'paid': round(paid, 2),
                    'unpaid': round(unpaid, 2),
                    'sales_count': r.sales_count,
                    'percentage': round((income / total * 100) if total > 0 else 0, 2),
                })

            # --- 3. Payment method breakdown, per month (payment_method filter applies here only) ---
            pm_q = (
                db.session.query(
                    yr.label('yr'), mo.label('mo'), 
                    SalesPaymentMethods.payment_method.label('method'),
                    func.sum(SalesPaymentMethods.amount_paid).label('amount'),
                    func.count().label('count'),
                )
                .join(Sales, Sales.sales_id == SalesPaymentMethods.sale_id)
            )
            pm_q = apply_common_filters(pm_q, Sales.created_at)
            if payment_method:
                pm_q = pm_q.filter(SalesPaymentMethods.payment_method == payment_method)
            for r in pm_q.group_by('yr', 'mo', SalesPaymentMethods.payment_method).all():
                mk = month_key(r.yr, r.mo)
                if mk not in monthly:
                    continue
                amount = float(r.amount or 0)
                total = monthly[mk]['total_income']
                monthly[mk]['payment_methods'].append({
                    'method': r.method,
                    'amount': round(amount, 2),
                    'count': r.count,
                    'percentage': round((amount / total * 100) if total > 0 else 0, 2),
                })

            # --- 4. Item breakdown, per month — top 10 by revenue ---
            item_q = (
                db.session.query(
                    yr.label('yr'), mo.label('mo'), 
                    SoldItem.item_name.label('item_name'),
                    func.sum(SoldItem.quantity).label('quantity'),
                    func.sum(SoldItem.total_price).label('revenue'),
                    func.count().label('sales_count'),
                )
                .join(Sales, Sales.sales_id == SoldItem.sales_id)
            )
            item_q = apply_common_filters(item_q, Sales.created_at)
            item_rows_by_month = defaultdict(list)
            for r in item_q.group_by('yr', 'mo', SoldItem.item_name).all():
                mk = month_key(r.yr, r.mo)
                if mk not in monthly:
                    continue
                item_rows_by_month[mk].append({
                    'name': r.item_name,
                    'quantity': round(float(r.quantity or 0), 2),
                    'revenue': round(float(r.revenue or 0), 2),
                    'sales_count': r.sales_count,
                })
            for mk, items in item_rows_by_month.items():
                monthly[mk]['top_items'] = sorted(items, key=lambda x: x['revenue'], reverse=True)[:10]

            # --- 5. Status distribution, per month ---
            status_q = db.session.query(
                yr.label('yr'), mo.label('mo'), 
                Sales.status.label('status'),
                func.count(Sales.sales_id).label('count'),
            )
            status_q = apply_common_filters(status_q, Sales.created_at)
            for r in status_q.group_by('yr', 'mo', Sales.status).all():
                mk = month_key(r.yr, r.mo)
                if mk not in monthly:
                    continue
                monthly[mk]['status_distribution'][r.status] = r.count

            # --- Format final response (same shape as before) ---
            response_data = []
            for mk in months_order:
                m = monthly[mk]
                avg = round(m['total_income'] / m['sales_count'], 2) if m['sales_count'] > 0 else 0
                response_data.append({
                    'month': m['month'],
                    'month_key': m['month_key'],
                    'summary': {
                        'total_sales': m['sales_count'],
                        'total_income': round(m['total_income'], 2),
                        'total_paid': round(m['total_paid'], 2),
                        'total_unpaid': round(m['total_unpaid'], 2),
                        'average_sale': avg,
                    },
                    'shops': m['shops'],
                    'payment_methods': m['payment_methods'],
                    'top_items': m['top_items'],
                    'status_distribution': m['status_distribution'],
                })

            total_income = sum(month['summary']['total_income'] for month in response_data)
            total_paid = sum(month['summary']['total_paid'] for month in response_data)
            total_unpaid = sum(month['summary']['total_unpaid'] for month in response_data)
            total_sales = sum(month['summary']['total_sales'] for month in response_data)

            return make_response(jsonify({
                'data': response_data,
                'totals': {
                    'total_income': round(total_income, 2),
                    'total_paid': round(total_paid, 2),
                    'total_unpaid': round(total_unpaid, 2),
                    'total_sales': total_sales,
                    'months_count': len(response_data),
                },
                'filters_applied': {
                    'shop_id': shop_id or 'all',
                    'shop_name': shop_name,
                    'start_date': start_date,
                    'end_date': end_date,
                    'payment_method': payment_method,
                    'year': year,
                }
            }), 200)

        except Exception as e:
            return {"error": str(e)}, 500


"""
SasaPay <-> Sales reconciliation endpoint.

User journey: pick a shop (or "all") + a date/period. For each shop, its
sales (payment_method='sasapay') are matched against that shop's SasaPay
merchant statement, primarily on transaction_code, falling back to
last-4-digit suffix match, then finally date+amount when a sale's
transaction_code wasn't captured.
"""

from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import request
from flask_jwt_extended import jwt_required

# shop_id -> SasaPay merchant_code. Two shops can share a merchant_code
# (same physical account) — matching is done per merchant_code so their
# sales are reconciled against one shared statement, not double-checked.
SHOP_TO_MERCHANT_MAPPING = {
    2: "570257",   # Kuku Zetu - Mirema
    5: "577960",   # Kuku Zetu - Lumumba Drive
    3: "577480",   # Kuku Zetu - Zimmerman
    8: "577668",   # Kukuzetu - Ngoingwa Stockist
    1: "577666",   # KUKUZETU - TRM
    20: "222333",  # Kukuzetu - Kasarani Equity
    19: "577123",  # Kukuzetu - Kasarani Maternity
    16: "577556",  # Kukuzetu - Turi
    9: "570257",   # Kuku Zetu - Mirema (second account/till on same shop)
}


class SasaPayFetchError(Exception):
    pass


class SasaPayReconciliationResource(SasaPayTransactionStatementResource):
    """
    GET /api/reconciliation/sasapay

    Query params:
      shop_id           required - a shop id from SHOP_TO_MERCHANT_MAPPING, or "all"
      date              optional - single day, YYYY-MM-DD
      start_date        optional - range start, YYYY-MM-DD (used if 'date' not given)
      end_date          optional - range end, YYYY-MM-DD
      payment_method    optional - default 'sasapay'
      amount_tolerance  optional - default 1 (KES). Abs diff above this -> mismatch, not silent match.

    Matching order (per sale):
      1. Exact full transaction_code match (most reliable)
      2. Last-4-digit suffix match, disambiguated by sale date + amount
      3. Same-day + same-amount fallback (when sale has no txn code)
    """

    @jwt_required()
    def get(self):
        raw_shop_id = request.args.get('shop_id')
        if not raw_shop_id:
            return {"error": "shop_id is required (a shop id, or 'all')"}, 400

        payment_method = request.args.get('payment_method', 'sasapay')

        try:
            amount_tolerance = Decimal(request.args.get('amount_tolerance', '1'))
        except InvalidOperation:
            return {"error": "amount_tolerance must be numeric"}, 400

        # ---- resolve shop_id(s) ----
        if raw_shop_id.lower() == 'all':
            shop_ids = list(SHOP_TO_MERCHANT_MAPPING.keys())
        else:
            try:
                shop_id = int(raw_shop_id)
            except ValueError:
                return {"error": "shop_id must be an integer or 'all'"}, 400
            if shop_id not in SHOP_TO_MERCHANT_MAPPING:
                return {"error": f"shop_id {shop_id} has no SasaPay merchant mapping"}, 400
            shop_ids = [shop_id]

        # ---- resolve date range ----
        single_date = request.args.get('date')
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')

        try:
            if single_date:
                start_date = end_date = datetime.strptime(single_date, '%Y-%m-%d').date()
            elif start_date_str and end_date_str:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            else:
                return {"error": "Provide either 'date' or both 'start_date' and 'end_date' (YYYY-MM-DD)"}, 400
        except ValueError:
            return {"error": "Invalid date format. Use YYYY-MM-DD."}, 400

        if start_date > end_date:
            return {"error": "start_date must be before end_date"}, 400

        # ---- group shops by merchant_code (shared statement per merchant) ----
        shops_by_merchant = defaultdict(list)
        for sid in shop_ids:
            shops_by_merchant[SHOP_TO_MERCHANT_MAPPING[sid]].append(sid)

        rows = []
        per_shop_summary = defaultdict(lambda: {"matched": 0, "unmatched": 0, "amount_mismatches": 0})
        unmatched_statement_all = []
        errors = []

        for merchant_code, merchant_shop_ids in shops_by_merchant.items():
            try:
                statement_transactions = self._fetch_statement_range(
                    merchant_code, merchant_code, start_date, end_date
                )
            except SasaPayFetchError as e:
                errors.append({"merchant_code": merchant_code, "shop_ids": merchant_shop_ids, "error": str(e)})
                continue

            sale_payment_rows = self._get_sale_payment_rows(
                merchant_shop_ids, payment_method, start_date, end_date
            )

            # ---- build indexes ----
            # full code -> [tx, ...]
            by_code = defaultdict(list)
            # last 4 chars of code -> [tx, ...]
            by_suffix4 = defaultdict(list)
            for tx in statement_transactions:
                code = (tx.get('code') or '').strip()
                if code:
                    by_code[code].append(tx)
                    if len(code) >= 4:
                        by_suffix4[code[-4:]].append(tx)

            used_tx_ids = set()

            for sale, payment, shop in sale_payment_rows:
                tx_code = getattr(payment, 'transaction_code', None)
                sale_amount = Decimal(str(payment.amount_paid or 0))

                match, match_basis = self._find_match(
                    tx_code, sale, sale_amount, statement_transactions,
                    by_code, by_suffix4, used_tx_ids, amount_tolerance
                )

                item_names = ", ".join(i.item_name for i in sale.items) if sale.items else None

                if match:
                    used_tx_ids.add(id(match))
                    diff = match['amount'] - sale_amount
                    mismatch = abs(diff) > amount_tolerance
                    rows.append({
                        "shop_id": shop.shops_id,
                        "shop_name": shop.shopname,
                        "sale_id": sale.sales_id,
                        "sale_date": sale.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                        "item_name": item_names,
                        "amount": float(sale_amount),
                        "payment_method": payment_method,
                        "match_status": "mismatch" if mismatch else "matched",
                        "matched_by": match_basis,
                        "transaction_amount": float(match['amount']),
                        "transaction_code": match['code'],
                        "reason": (
                            f"matched but amounts differ by {float(diff)}" if mismatch else None
                        ),
                    })
                    per_shop_summary[shop.shops_id]["matched"] += 1
                    if mismatch:
                        per_shop_summary[shop.shops_id]["amount_mismatches"] += 1
                else:
                    if not tx_code:
                        reason = ("no transaction_code recorded and no statement entry "
                                  "with matching date/amount")
                    else:
                        tail = str(tx_code).strip()[-4:]
                        reason = (f"transaction_code ending '{tail}' not found in statement "
                                  f"for this date range")
                    rows.append({
                        "shop_id": shop.shops_id,
                        "shop_name": shop.shopname,
                        "sale_id": sale.sales_id,
                        "sale_date": sale.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                        "item_name": item_names,
                        "amount": float(sale_amount),
                        "payment_method": payment_method,
                        "match_status": "not_matched",
                        "matched_by": None,
                        "transaction_amount": None,
                        "transaction_code": tx_code,
                        "reason": reason,
                    })
                    per_shop_summary[shop.shops_id]["unmatched"] += 1

            unmatched_statement_all.extend({
                "merchant_code": merchant_code,
                "shop_ids": merchant_shop_ids,
                "transaction_code": tx['code'],
                "date": tx['date'].strftime('%Y-%m-%d'),
                "amount": float(tx['amount']),
                "channel": tx['channel'],
                "reference": tx['reference'],
                "status": tx['status'],
                "reason": "no sale with this date/amount/code found — verify manually "
                          "(could be a deposit not tied to a sale, or an unrecorded sale)",
            } for tx in statement_transactions if id(tx) not in used_tx_ids)

        summary = {
            "shops_checked": len(shop_ids),
            "total_rows": len(rows),
            "matched": sum(v["matched"] for v in per_shop_summary.values()),
            "amount_mismatches": sum(v["amount_mismatches"] for v in per_shop_summary.values()),
            "unmatched_sales": sum(v["unmatched"] for v in per_shop_summary.values()),
            "unmatched_statement_transactions": len(unmatched_statement_all),
            "per_shop": {
                sid: {"shop_id": sid, **stats} for sid, stats in per_shop_summary.items()
            },
        }

        return {
            "shop_ids": shop_ids,
            "date_range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
            "payment_method": payment_method,
            "summary": summary,
            "rows": rows,
            "unmatched_statement": unmatched_statement_all,
            "errors": errors,
        }, 200

    # ------------------------------------------------------------------
    def _get_sale_payment_rows(self, shop_ids, payment_method, start_date, end_date):
        sales_query = (
            Sales.query.join(Users).join(Shops)
            .join(SalesPaymentMethods, SalesPaymentMethods.sale_id == Sales.sales_id)
            .filter(SalesPaymentMethods.payment_method == payment_method)
            .filter(Sales.shop_id.in_(shop_ids))
            .filter(db.func.date(Sales.created_at) >= start_date)
            .filter(db.func.date(Sales.created_at) <= end_date)
        )
        sales = sales_query.all()

        rows = []
        for sale in sales:
            shop = sale.shops
            for p in sale.payment:
                if p.payment_method != payment_method:
                    continue
                rows.append((sale, p, shop))
        return rows

    # ------------------------------------------------------------------
    @staticmethod
    def _find_match(tx_code, sale, sale_amount, statement_transactions,
                    by_code, by_suffix4, used_tx_ids, amount_tolerance):
        """
        Try, in order:
          1. Exact full-code match.
          2. Last-4-digit suffix match, disambiguated by sale date + amount.
          3. Same-day + same-amount fallback.
        Returns (matched_tx_or_None, basis_string_or_None).
        """
        sale_date = sale.created_at.date()

        if tx_code:
            code = str(tx_code).strip()

            # 1. exact full-code match
            for candidate in by_code.get(code, []):
                if id(candidate) not in used_tx_ids:
                    return candidate, "transaction_code"

            # 2. last-4-digit suffix match
            if len(code) >= 4:
                suffix = code[-4:]
                candidates = [c for c in by_suffix4.get(suffix, [])
                              if id(c) not in used_tx_ids]

                if candidates:
                    # Prefer candidates on the same day AND within amount tolerance
                    preferred = [
                        c for c in candidates
                        if c['date'] == sale_date
                        and abs(c['amount'] - sale_amount) <= amount_tolerance
                    ]
                    if preferred:
                        return preferred[0], "transaction_code_suffix"

                    # No amount+date match; only accept if unambiguous
                    if len(candidates) == 1:
                        return candidates[0], "transaction_code_suffix"

                    # Ambiguous — don't guess; fall through to date+amount
                    # (which is basically same-day + same-amount anyway)

        # 3. fallback: same date + same amount, first unused candidate
        for candidate in statement_transactions:
            if id(candidate) in used_tx_ids:
                continue
            if candidate['date'] != sale_date:
                continue
            if abs(candidate['amount'] - sale_amount) <= amount_tolerance:
                return candidate, "date_and_amount_fallback"

        return None, None

    # ------------------------------------------------------------------
    # Statement fetching (paginates the SasaPay API, filters to date range)
    # ------------------------------------------------------------------
    def _fetch_statement_range(self, merchant_code, account_number, start_date, end_date):
        import os
        import requests

        sasapay_env = os.getenv("SASAPAY_ENVIRONMENT", "sandbox")

        if sasapay_env != "production":
            raise SasaPayFetchError(
                "Transaction statements are only available in PRODUCTION environment"
            )

        merchants = self._get_all_merchant_configs(sasapay_env)
        merchant = next((m for m in merchants if m['code'] == merchant_code), None)
        if not merchant:
            raise SasaPayFetchError(f"Merchant {merchant_code} not found or not configured")

        access_token = self._get_access_token(
            merchant['base_url'], merchant['client_id'], merchant['client_secret']
        )
        if not access_token:
            raise SasaPayFetchError("Failed to obtain SasaPay access token")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        transactions_url = "https://api.sasapay.app/api/v2/waas/transactions/"

        results = []
        page = 1
        page_size = 100
        max_pages = 200  # safety cap

        # Statement rows are date-desc. Stop once a page's oldest row is
        # older than start_date.
        while page <= max_pages:
            params = {
                "merchantCode": merchant_code,
                "accountNumber": account_number,
                "page": page,
                "page_size": page_size,
            }
            resp = requests.get(transactions_url, headers=headers, params=params, timeout=30)
            if resp.status_code != 200:
                raise SasaPayFetchError(
                    f"Statement fetch failed (HTTP {resp.status_code}): {resp.text[:200]}"
                )

            data = resp.json()
            raw_txs = (
                data.get('data', {}).get('transactions')
                if isinstance(data.get('data'), dict)
                else data.get('transactions', [])
            ) or []

            if not raw_txs:
                break

            page_min_date = None
            for tx in raw_txs:
                tx_date = self._parse_statement_date(tx.get('transaction_date') or tx.get('Date'))
                if tx_date is None:
                    continue
                page_min_date = tx_date if page_min_date is None else min(page_min_date, tx_date)

                if start_date <= tx_date <= end_date:
                    results.append({
                        "date": tx_date,
                        "amount": Decimal(str(tx.get('transaction_amount', tx.get('Amount', 0)))),
                        "code": tx.get('transaction_code') or tx.get('Code'),
                        "reference": tx.get('transaction_reference') or tx.get('Reference'),
                        "channel": (tx.get('payment_details') or {}).get('channel_name') or tx.get('Channel'),
                        "status": tx.get('result_description') or tx.get('Status'),
                    })

            total_pages = data.get('pages', 1)
            if page_min_date and page_min_date < start_date:
                break
            if page >= total_pages:
                break
            page += 1

        return results

    @staticmethod
    def _parse_statement_date(raw):
        if not raw:
            return None
        for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
            try:
                return datetime.strptime(raw[:19] if 'T' in raw else raw, fmt).date()
            except ValueError:
                continue
        return None