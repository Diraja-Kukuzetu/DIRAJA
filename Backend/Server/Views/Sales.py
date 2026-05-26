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
from flask import jsonify, request, Response
from functools import wraps
from Server.Models.Creditors import Creditors
from datetime import datetime, timedelta
from Server.Models.Transactions import TranscationType
from Server.Models.BankAccounts import BankAccount
from Server.Models.CashDeposit import CashDeposits
from flask import current_app
from fuzzywuzzy import process
from collections import defaultdict
from sqlalchemy import func, and_
import logging
from math import modf
import threading
from Server.Views.Services.sasapay_service import SasaPayPaymentService
from Server.Views.Services.etims_sale_service import etims_sale_service
from Server.Views.Services.journal_service import JournalService
from flask import send_file
from io import BytesIO

logger = logging.getLogger(__name__)


# def check_role(allowed_roles):
#     def wrapper(fn):
#         @wraps(fn)
#         def decorator(*args, **kwargs):
#             current_user_id = get_jwt_identity()
#             user = Users.query.get(current_user_id)
#             if user and user.role not in allowed_roles:
#                 return make_response(jsonify({"error": "Unauthorized access"}), 403)
#             return fn(*args, **kwargs)
#         return decorator
#     return wrapper


# class TotalBalanceSummary(Resource):
#     @jwt_required()
#     @check_role(['manager', 'clerk'])
#     def get(self):
#         # Your endpoint logic here
#         return jsonify({"message": "Success"})


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
            created_at = datetime.strptime(data['sale_date'], "%Y-%m-%d") if 'sale_date' in data else datetime.utcnow()

            if not isinstance(data['items'], list) or not data['items']:
                return {'message': 'Items must be a non-empty list'}, 400

            items = []
            total_price = 0.0
            total_quantity = 0.0
            purchase_account = 0.0
            etims_items_data = []  # For eTims sync

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

                # ===== GET STOCK ITEM AND ETIMS CODE =====
                stock_item = StockItems.query.filter_by(
                    item_name=item['item_name']
                ).first()

                if not stock_item:
                    logger.warning(f"Item '{item['item_name']}' not found in StockItems")
                
                # Get eTims item code if available
                etims_item_code = None
                if stock_item and stock_item.etims_synced:
                    etims_item_code = stock_item.etims_item_code
                    logger.info(f"✅ Found eTims code {etims_item_code} for '{item['item_name']}'")
                else:
                    logger.warning(f"⚠️  No eTims code found for '{item['item_name']}'")

                # ===== CHECK IF ITEM IS A SERVICE =====
                is_service = False
                if stock_item:
                    is_service = stock_item.stock_item_type == "Service"
                    logger.info(f"Item '{item['item_name']}' is {'Service' if is_service else 'Product'} - {'SKIP' if is_service else 'PROCESS'} stock deduction")
                else:
                    logger.warning(f"Item '{item['item_name']}' not found in StockItems, treating as Product")

                # Build item data with stock reference
                item_data = {
                    'item_name': item['item_name'],
                    'quantity': float(item['quantity']),
                    'metric': metric,
                    'unit_price': float(item['unit_price']),
                    'total_price': float(item['total_price']),
                    'item_id': stock_item.id if stock_item else None,
                    'etims_item_code': etims_item_code,
                    'stock_item': stock_item,  # Keep reference for later
                    'is_service': is_service  # Flag for stock processing
                }
                items.append(item_data)
                
                # Store for eTims sync
                etims_items_data.append({
                    'item_name': item['item_name'],
                    'quantity': float(item['quantity']),
                    'metric': metric,
                    'unit_price': float(item['unit_price']),
                    'total_price': float(item['total_price']),
                    'etims_item_code': etims_item_code,
                    'item_id': stock_item.id if stock_item else None,
                    'is_service': is_service  # Store service flag
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
                # ===== SKIP STOCK DEDUCTION FOR SERVICE ITEMS =====
                if item.get('is_service', False):
                    logger.info(f"⏭️ Skipping stock deduction for service item: {item['item_name']}")
                    
                    # Build sold item WITHOUT stock deduction
                    sold_item = {
                        'item_name': item['item_name'],
                        'quantity': item['quantity'],
                        'metric': item['metric'],
                        'unit_price': item['unit_price'],
                        'total_price': item['total_price'],
                        'BatchNumber': "Service Item - No Stock Deduction",
                        'stockv2_id': None,
                        'item_id': item.get('item_id'),
                        'etims_item_code': item.get('etims_item_code'),
                        'Cost_of_sale': item['total_price'],
                        'Purchase_account': 0.0,  # No purchase cost for services
                        'LivestockDeduction': 0.0,
                        'is_service': True  # Flag for SoldItem
                    }
                    sold_items.append(sold_item)
                    
                    # Record that this was a service item (no stock deduction)
                    batch_deductions.append({
                        'item_name': item['item_name'],
                        'item_id': item.get('item_id'),
                        'etims_item_code': item.get('etims_item_code'),
                        'deductions': [("Service Item", 0)],
                        'is_service': True
                    })
                    
                    continue  # Skip to next item

                # ===== PROCESS PRODUCT ITEMS (WITH STOCK DEDUCTION) =====
                # Process from ShopStockV2 using shop_id
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
                        'etims_item_code': item.get('etims_item_code'),
                        'deductions': item_batch_deductions,
                        'is_service': False
                    })
                    stock_ids_used.extend(item_stock_ids)

                purchase_account += item_purchase_account

                # Build sold item with references
                sold_item = {
                    'item_name': item['item_name'],
                    'quantity': item['quantity'],
                    'metric': item['metric'],
                    'unit_price': item['unit_price'],
                    'total_price': item['total_price'],
                    'BatchNumber': ", ".join(f"{bn} ({q})" for bn, q in item_batch_deductions) if item_batch_deductions else "From Livestock",
                    'stockv2_id': item_stock_ids[0] if item_stock_ids else None,
                    'item_id': item.get('item_id'),
                    'etims_item_code': item.get('etims_item_code'),
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
                    stockv2_id=item.get('stockv2_id'),  # Will be None for services
                    item_id=item.get('item_id'),  # Link to StockItems
                    etims_item_code=item.get('etims_item_code'),  # Store eTims code
                    Cost_of_sale=item['Cost_of_sale'],
                    Purchase_account=item.get('Purchase_account', 0.0),  # 0 for services
                    LivestockDeduction=item.get('LivestockDeduction', 0.0),  # 0 for services
                    round_off=fractional_part,
                    is_service=item.get('is_service', False)  # Add service flag to SoldItem
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

                # REMOVED: Bank account deposit logic for SASAPAY
                # Previously had code here that would update bank accounts
                # Now just records the payment method without affecting account balances

                db.session.add(SalesPaymentMethods(
                    sale_id=new_sale.sales_id,
                    payment_method=method,
                    amount_paid=amount,
                    transaction_code=transaction_code,
                    discount=discount,
                    created_at=created_at
                ))

            # ===== CUSTOMER RECORD =====
            if data['customer_name'] or data['customer_number']:
                db.session.add(Customers(
                    customer_name=data['customer_name'],
                    customer_number=data['customer_number'],
                    shop_id=shop_id,
                    sales_id=new_sale.sales_id,
                    user_id=current_user_id,
                    item=", ".join([item['item_name'] for item in items]),
                    amount_paid=total_amount_paid,
                    payment_method=", ".join(pm['method'] for pm in payment_methods),
                    created_at=created_at
                ))

            # ===== COMMIT LOCAL SALE FIRST =====
            db.session.commit()

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
            except Exception as e:
                db.session.rollback()
                return {
                    "message": "Sale saved but journal posting failed",
                    "error": str(e),
                    "sale_id": new_sale.sales_id
                }, 500

            # ===== CREATE ETIMS SALE RECORD (PENDING SYNC) =====
            etims_success = False
            etims_result = None
            
            try:
                # Check if we have eTims codes for all items
                has_etims_codes = all(item.get('etims_item_code') for item in etims_items_data)
                
                if has_etims_codes:
                    # Prepare data for eTims sale record
                    etims_sale_data = {
                        'items': etims_items_data,
                        'customer_name': data['customer_name'],
                        'customer_number': data['customer_number'],
                        'sale_date': data.get('sale_date'),
                        'payment_methods': payment_methods,
                        'shop_id': shop_id
                    }
                    
                    # Create eTims sale record (pending)
                    etims_success, etims_result = etims_sale_service.create_etims_sale_from_sale(
                        etims_sale_data,
                        new_sale.sales_id,
                        shop_id
                    )
                    
                    if etims_success:
                        logger.info(f"✅ eTims sale record created: {etims_result.get('etims_sale', {}).get('trader_invoice_no')}")
                    else:
                        logger.warning(f"⚠️  Failed to create eTims sale record: {etims_result.get('error') if etims_result else 'Unknown error'}")
                else:
                    missing_etims_items = [item['item_name'] for item in etims_items_data if not item.get('etims_item_code')]
                    logger.warning(f"⚠️  Skipping eTims record - missing eTims codes for: {missing_etims_items}")
                    etims_result = {
                        'error': f'Missing eTims codes for: {", ".join(missing_etims_items)}',
                        'skipped': True
                    }
                    
            except Exception as e:
                logger.error(f"Error creating eTims sale record: {str(e)}")
                etims_result = {'error': str(e), 'skipped': True}

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
                # Add eTims info
                'etims': {
                    'record_created': etims_success,
                    'status': 'pending' if etims_success else 'skipped',
                    'trader_invoice_no': etims_result.get('etims_sale', {}).get('trader_invoice_no') if etims_success else None,
                    'message': etims_result.get('message', 'Sale will be published during bulk sync') if etims_success else etims_result.get('error', 'No eTims record created')
                }
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
            return {
                'message': 'Transaction failed',
                'error': str(e),
                'debug_info': {
                    'sale_id': new_sale.sales_id if new_sale else "Not created",
                    'processed_payments': [pm['method'] for pm in payment_methods],
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
            sort_by = request.args.get('sort_by', 'created_at')
            sort_order = request.args.get('sort_order', 'desc')
            start_date = request.args.get('start_date')  # Added for date range
            end_date = request.args.get('end_date')      # Added for date range

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

            # Handle date range filter (for exports)
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

            # For exports, always get all data without pagination
            # Check if this is an export request (large limit or specific parameters)
            is_export = limit > 500 or start_date or end_date
            
            if is_export:
                # Get all sales without pagination
                sales_list = sales_query.all()
                total_sales = len(sales_list)
                total_pages = 1
            else:
                # Decide pagination for normal requests
                use_pagination = not (
                    search_query or
                    selected_date or
                    status_filter or
                    shop_filter or
                    sort_by != 'created_at' or
                    sort_order != 'desc'
                )

                if use_pagination:
                    offset = (page - 1) * limit
                    sales_list = sales_query.offset(offset).limit(limit).all()
                    total_sales = sales_query.count()
                    total_pages = (total_sales + limit - 1) // limit
                else:
                    sales_list = sales_query.all()
                    total_sales = len(sales_list)
                    total_pages = 1

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
                        "discount": p.discount if p.discount is not None else 0,  # Handle None values
                        "balance": p.balance if p.balance is not None else 0,    # Handle None values
                        "created_at": p.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                        "transaction_code": getattr(p, 'transaction_code', None)
                    }
                    for p in sale.payment
                ]

                # Safely calculate totals with None checks
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
                "current_page": page if not is_export else 1
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


class GetSalesByShop(Resource):
    @jwt_required()
    def get(self, shop_id):
        try:
            # Get query parameters
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 50))
            search_query = request.args.get('search', '').lower()
            date_filter = request.args.get('date', '')

            offset = (page - 1) * limit

            # Base query
            sales_query = Sales.query.filter_by(shop_id=shop_id)

            # Apply search filter if provided
            if search_query:
                sales_query = sales_query.join(SoldItem).filter(
                    or_(
                        Sales.customer_name.ilike(f'%{search_query}%'),
                        SoldItem.item_name.ilike(f'%{search_query}%')
                    )
                )

            # Apply date filter if provided
            if date_filter:
                try:
                    filter_date = datetime.strptime(date_filter, '%Y-%m-%d').date()
                    sales_query = sales_query.filter(
                        db.func.date(Sales.created_at) == filter_date
                    )
                except ValueError:
                    pass

            # Get total count before pagination
            total_sales = sales_query.count()

            # Apply pagination and ordering
            sales = sales_query.order_by(Sales.created_at.desc()) \
                              .offset(offset).limit(limit).all()

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
                total_amount_paid = sum(payment["amount_paid"] for payment in payment_data)

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
  
    
class TotalCashSalesByUser(Resource):
    @jwt_required()
    def get(self, username, shop_id):
        try:
            # ===============================
            # 1. Fixed start date (16/02/2026)
            # ===============================
            start_date = datetime.strptime("2026-03-23", "%Y-%m-%d").date()
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
            # Query params
            start_date = request.args.get('start_date')  # format: 'YYYY-MM-DD'
            end_date = request.args.get('end_date')      # format: 'YYYY-MM-DD'

            # Parse and validate dates
            try:
                if start_date:
                    start_date = datetime.strptime(start_date, '%Y-%m-%d')
                if end_date:
                    end_date = datetime.strptime(end_date, '%Y-%m-%d')
            except ValueError:
                return {"error": "Invalid date format. Use YYYY-MM-DD"}, 400

            # Base query
            query = db.session.query(
                SoldItem.item_name,
                SoldItem.metric,
                func.sum(SoldItem.quantity).label("total_sold")
            ).join(Sales, SoldItem.sales_id == Sales.sales_id)

            # Apply filters
            if shop_id is not None:
                query = query.filter(Sales.shop_id == shop_id)
            if start_date:
                query = query.filter(Sales.created_at >= start_date)
            if end_date:
                query = query.filter(Sales.created_at <= end_date)

            # Group and fetch
            result = query.group_by(SoldItem.item_name, SoldItem.metric).all()

            sold_items_summary = [
                {
                    "item_name": item_name,
                    "metric": metric,
                    "total_sold": round(total_sold, 2)
                }
                for item_name, metric, total_sold in result
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


class GetSalesGraphData(Resource):
    @jwt_required()
    def get(self):
        """
        Comprehensive sales graph data endpoint
        Query params:
        - shop_id: optional (if not provided, returns data for all shops)
        - start_date: optional (YYYY-MM-DD)
        - end_date: optional (YYYY-MM-DD)
        - payment_method: optional (cash, mpesa, sasapay, bank)
        - status: optional (paid, unpaid, partially_paid, pending)
        - group_by: optional (day, week, month, year) - default: month
        """
        try:
            # Get query parameters
            shop_id = request.args.get('shop_id')
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            payment_method = request.args.get('payment_method')
            status = request.args.get('status')
            group_by = request.args.get('group_by', 'month')
            
            # Base query for sales - start with all sales
            sales_query = Sales.query
            
            # Apply shop filter if provided
            shop_name = "All Shops"
            if shop_id:
                # Validate shop exists
                shop = Shops.query.filter_by(shops_id=shop_id).first()
                if not shop:
                    return {"error": "Shop not found"}, 404
                shop_name = shop.shopname
                sales_query = sales_query.filter_by(shop_id=shop_id)
            
            # Apply date filters
            if start_date:
                sales_query = sales_query.filter(Sales.created_at >= start_date)
            if end_date:
                # Add one day to include the end date
                end_date_obj = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
                sales_query = sales_query.filter(Sales.created_at < end_date_obj)
            
            # Apply status filter
            if status:
                sales_query = sales_query.filter(Sales.status == status)
            
            # Get sales ordered by created_at
            sales = sales_query.order_by(Sales.created_at.asc()).all()
            
            if not sales:
                return {
                    "message": "No sales data found for the given criteria",
                    "time_series": {
                        "categories": [],
                        "series": []
                    },
                    "summary": {},
                    "popular_items": {"items": []},
                    "payment_distribution": {"distribution": []},
                    "daily_trends": {"days": [], "income": [], "transactions": [], "items_sold": []},
                    "filters_applied": {
                        "shop_id": shop_id or "all",
                        "shop_name": shop_name,
                        "start_date": start_date,
                        "end_date": end_date,
                        "payment_method": payment_method,
                        "status": status,
                        "group_by": group_by
                    }
                }, 200
            
            # Prepare all data
            grouped_data = self.group_sales_by_period(sales, group_by)
            time_series_data = self.prepare_time_series_data(grouped_data)
            summary = self.calculate_summary(sales, payment_method)
            popular_items = self.get_popular_items(sales)
            payment_distribution = self.get_payment_distribution(sales)
            daily_trends = self.get_daily_trends(sales)
            
            return make_response(jsonify({
                "time_series": time_series_data,
                "summary": summary,
                "popular_items": popular_items,
                "payment_distribution": payment_distribution,
                "daily_trends": daily_trends,
                "filters_applied": {
                    "shop_id": shop_id or "all",
                    "shop_name": shop_name,
                    "start_date": start_date,
                    "end_date": end_date,
                    "payment_method": payment_method,
                    "status": status,
                    "group_by": group_by
                }
            }), 200)
            
        except Exception as e:
            return {"error": str(e)}, 500
    
    def group_sales_by_period(self, sales, group_by):
        """Group sales by day, week, month, or year"""
        grouped = defaultdict(lambda: {
            'sales': [],
            'total_income': 0,
            'total_cashflow': 0,
            'total_revenue': 0,
            'transactions': 0,
            'total_discount': 0,
            'total_balance': 0,
            'sold_items': []
        })
        
        for sale in sales:
            # Determine period key
            if group_by == 'day':
                period_key = sale.created_at.strftime('%Y-%m-%d')
            elif group_by == 'week':
                year = sale.created_at.isocalendar()[0]
                week = sale.created_at.isocalendar()[1]
                period_key = f"{year}-W{week:02d}"
            elif group_by == 'year':
                period_key = sale.created_at.strftime('%Y')
            else:  # month (default)
                period_key = sale.created_at.strftime('%Y-%m')
            
            # Get payment methods for this sale
            payment_methods = SalesPaymentMethods.query.filter_by(sale_id=sale.sales_id).all()
            
            # Handle None values with safe fallbacks
            total_paid = sum(pm.amount_paid or 0 for pm in payment_methods)
            total_discount = sum(pm.discount or 0 for pm in payment_methods)
            
            # Get sold items for this sale
            sold_items = SoldItem.query.filter_by(sales_id=sale.sales_id).all()
            total_items_revenue = sum(item.total_price or 0 for item in sold_items)
            total_cost = sum(item.Cost_of_sale or 0 for item in sold_items)
            
            # Group data with safe None handling
            grouped[period_key]['sales'].append(sale)
            grouped[period_key]['total_income'] += total_paid
            grouped[period_key]['total_cashflow'] += total_paid - (sale.balance or 0)
            grouped[period_key]['total_revenue'] += total_items_revenue
            grouped[period_key]['transactions'] += 1
            grouped[period_key]['total_discount'] += total_discount
            grouped[period_key]['total_balance'] += sale.balance or 0
            grouped[period_key]['sold_items'].extend(sold_items)
        
        return grouped
    
    def prepare_time_series_data(self, grouped_data):
        """Prepare data for time series charts"""
        sorted_periods = sorted(grouped_data.keys())
        
        income_data = []
        cashflow_data = []
        revenue_data = []
        transaction_count = []
        average_order_value = []
        discount_data = []
        profit_data = []
        balance_data = []
        
        for period in sorted_periods:
            data = grouped_data[period]
            
            # Calculate profit (revenue - cost) with safe None handling
            total_cost = sum(item.Cost_of_sale or 0 for item in data['sold_items'])
            profit = data['total_revenue'] - total_cost
            
            income_data.append(round(data['total_income'] or 0, 2))
            cashflow_data.append(round(data['total_cashflow'] or 0, 2))
            revenue_data.append(round(data['total_revenue'] or 0, 2))
            transaction_count.append(data['transactions'] or 0)
            discount_data.append(round(data['total_discount'] or 0, 2))
            profit_data.append(round(profit or 0, 2))
            balance_data.append(round(data['total_balance'] or 0, 2))
            
            if data['transactions'] > 0:
                avg_order = (data['total_income'] or 0) / data['transactions']
                average_order_value.append(round(avg_order, 2))
            else:
                average_order_value.append(0)
        
        return {
            'categories': sorted_periods,
            'series': [
                {
                    'name': 'Income',
                    'type': 'column',
                    'data': income_data,
                    'color': '#008FFB'
                },
                {
                    'name': 'Cashflow',
                    'type': 'column',
                    'data': cashflow_data,
                    'color': '#00E396'
                },
                {
                    'name': 'Revenue',
                    'type': 'line',
                    'data': revenue_data,
                    'color': '#FEB019'
                },
                {
                    'name': 'Profit',
                    'type': 'line',
                    'data': profit_data,
                    'color': '#FF4560'
                },
                {
                    'name': 'Transactions',
                    'type': 'line',
                    'data': transaction_count,
                    'color': '#775DD0'
                },
                {
                    'name': 'Avg Order Value',
                    'type': 'line',
                    'data': average_order_value,
                    'color': '#3F51B5'
                }
            ],
            'yaxis_labels': {
                'income': 'Income (KES)',
                'cashflow': 'Cashflow (KES)',
                'revenue': 'Revenue (KES)',
                'profit': 'Profit (KES)',
                'transactions': 'Number of Transactions',
                'avg_order': 'Average Order Value (KES)'
            }
        }
    
    def calculate_summary(self, sales, payment_method_filter=None):
        """Calculate summary statistics"""
        total_sales = len(sales)
        total_income = 0
        total_balance = 0
        total_items_sold = 0
        total_revenue = 0
        total_cost = 0
        total_discount = 0
        payment_methods_count = defaultdict(int)
        status_count = defaultdict(int)
        unique_customers = set()
        
        for sale in sales:
            payment_methods = SalesPaymentMethods.query.filter_by(sale_id=sale.sales_id).all()
            
            # Filter by payment method if specified
            if payment_method_filter:
                payment_methods = [pm for pm in payment_methods if pm.payment_method == payment_method_filter]
            
            # Safe sum with None handling
            total_paid = sum(pm.amount_paid or 0 for pm in payment_methods)
            total_discount += sum(pm.discount or 0 for pm in payment_methods)
            total_income += total_paid
            total_balance += sale.balance or 0
            
            # Track unique customers
            if sale.customer_number:
                unique_customers.add(sale.customer_number)
            
            # Count payment methods
            for pm in payment_methods:
                payment_methods_count[pm.payment_method] += 1
            
            # Count status
            status_count[sale.status] += 1
            
            # Get sold items with safe None handling
            sold_items = SoldItem.query.filter_by(sales_id=sale.sales_id).all()
            total_items_sold += sum(item.quantity or 0 for item in sold_items)
            total_revenue += sum(item.total_price or 0 for item in sold_items)
            total_cost += sum(item.Cost_of_sale or 0 for item in sold_items)
        
        profit = total_revenue - total_cost
        
        return {
            'total_sales': total_sales,
            'total_income': round(total_income, 2),
            'total_balance': round(total_balance, 2),
            'total_items_sold': round(total_items_sold, 2),
            'total_revenue': round(total_revenue, 2),
            'total_cost': round(total_cost, 2),
            'total_profit': round(profit, 2),
            'total_discount': round(total_discount, 2),
            'average_sale_value': round(total_income / total_sales if total_sales > 0 else 0, 2),
            'average_items_per_sale': round(total_items_sold / total_sales if total_sales > 0 else 0, 2),
            'unique_customers': len(unique_customers),
            'payment_methods': dict(payment_methods_count),
            'status_distribution': dict(status_count)
        }
    
    def get_popular_items(self, sales):
        """Get most popular items across all sales"""
        item_sales = defaultdict(lambda: {
            'total_quantity': 0,
            'total_revenue': 0,
            'total_cost': 0,
            'sales_count': 0,
            'total_profit': 0
        })
        
        for sale in sales:
            sold_items = SoldItem.query.filter_by(sales_id=sale.sales_id).all()
            for item in sold_items:
                # Safe None handling for all numeric fields
                quantity = item.quantity or 0
                total_price = item.total_price or 0
                cost_of_sale = item.Cost_of_sale or 0
                
                item_sales[item.item_name]['total_quantity'] += quantity
                item_sales[item.item_name]['total_revenue'] += total_price
                item_sales[item.item_name]['total_cost'] += cost_of_sale
                item_sales[item.item_name]['sales_count'] += 1
                item_sales[item.item_name]['total_profit'] += total_price - cost_of_sale
        
        # Sort by total revenue
        sorted_items = sorted(
            item_sales.items(),
            key=lambda x: x[1]['total_revenue'],
            reverse=True
        )[:10]  # Top 10 items
        
        return {
            'items': [
                {
                    'name': item_name,
                    'total_quantity': round(data['total_quantity'] or 0, 2),
                    'total_revenue': round(data['total_revenue'] or 0, 2),
                    'total_cost': round(data['total_cost'] or 0, 2),
                    'total_profit': round(data['total_profit'] or 0, 2),
                    'sales_count': data['sales_count'] or 0,
                    'average_price': round((data['total_revenue'] or 0) / (data['total_quantity'] or 1) if data['total_quantity'] > 0 else 0, 2),
                    'profit_margin': round(((data['total_profit'] or 0) / (data['total_revenue'] or 1)) * 100 if data['total_revenue'] > 0 else 0, 2)
                }
                for item_name, data in sorted_items
            ]
        }
    
    def get_payment_distribution(self, sales):
        """Get payment method distribution"""
        payment_stats = defaultdict(lambda: {
            'count': 0,
            'total_amount': 0,
            'sales_count': 0,
            'total_discount': 0
        })
        
        for sale in sales:
            payment_methods = SalesPaymentMethods.query.filter_by(sale_id=sale.sales_id).all()
            for pm in payment_methods:
                # Safe None handling
                amount = pm.amount_paid or 0
                discount = pm.discount or 0
                
                payment_stats[pm.payment_method]['count'] += 1
                payment_stats[pm.payment_method]['total_amount'] += amount
                payment_stats[pm.payment_method]['sales_count'] += 1
                payment_stats[pm.payment_method]['total_discount'] += discount
        
        total_amount = sum(d['total_amount'] for d in payment_stats.values())
        
        return {
            'distribution': [
                {
                    'payment_method': method,
                    'count': data['count'] or 0,
                    'total_amount': round(data['total_amount'] or 0, 2),
                    'sales_count': data['sales_count'] or 0,
                    'total_discount': round(data['total_discount'] or 0, 2),
                    'percentage': round(
                        ((data['total_amount'] or 0) / (total_amount or 1)) * 100 if total_amount > 0 else 0,
                        2
                    )
                }
                for method, data in sorted(payment_stats.items(), key=lambda x: x[1]['total_amount'], reverse=True)
            ]
        }
    
    def get_daily_trends(self, sales):
        """Get daily sales trends"""
        daily_data = defaultdict(lambda: {
            'income': 0,
            'transactions': 0,
            'items_sold': 0,
            'revenue': 0,
            'profit': 0,
            'discount': 0
        })
        
        for sale in sales:
            day_key = sale.created_at.strftime('%Y-%m-%d')
            
            payment_methods = SalesPaymentMethods.query.filter_by(sale_id=sale.sales_id).all()
            total_paid = sum(pm.amount_paid or 0 for pm in payment_methods)
            total_discount = sum(pm.discount or 0 for pm in payment_methods)
            
            sold_items = SoldItem.query.filter_by(sales_id=sale.sales_id).all()
            total_items = sum(item.quantity or 0 for item in sold_items)
            total_revenue = sum(item.total_price or 0 for item in sold_items)
            total_cost = sum(item.Cost_of_sale or 0 for item in sold_items)
            
            daily_data[day_key]['income'] += total_paid
            daily_data[day_key]['transactions'] += 1
            daily_data[day_key]['items_sold'] += total_items
            daily_data[day_key]['revenue'] += total_revenue
            daily_data[day_key]['profit'] += total_revenue - total_cost
            daily_data[day_key]['discount'] += total_discount
        
        sorted_days = sorted(daily_data.keys())
        
        return {
            'days': sorted_days,
            'income': [round(daily_data[day]['income'] or 0, 2) for day in sorted_days],
            'transactions': [daily_data[day]['transactions'] or 0 for day in sorted_days],
            'items_sold': [round(daily_data[day]['items_sold'] or 0, 2) for day in sorted_days],
            'revenue': [round(daily_data[day]['revenue'] or 0, 2) for day in sorted_days],
            'profit': [round(daily_data[day]['profit'] or 0, 2) for day in sorted_days],
            'discount': [round(daily_data[day]['discount'] or 0, 2) for day in sorted_days]
        }