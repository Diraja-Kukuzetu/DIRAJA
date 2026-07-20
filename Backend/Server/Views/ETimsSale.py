from flask_restful import Resource
from flask import request, jsonify, make_response
from flask_jwt_extended import jwt_required, get_jwt_identity
from app import db
from Server.Models.Users import Users
from Server.Models.ETimsSales import ETimsSale, ETimsSaleStatus
from Server.Views.Services.etims_sale_service import etims_sale_service
from functools import wraps
import logging
import json

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


class BulkPublishSalesResource(Resource):
    """
    POST /api/diraja/etims-sales/bulk-publish
    Bulk publish all pending eTims sales to KRA
    """
    @jwt_required()
    @check_role('manager')
    def post(self):
        try:
            # Optional: filter by shop
            shop_id = request.args.get('shop_id', type=int)
            
            results = etims_sale_service.bulk_publish_sales(shop_id)
            return results, 200
            
        except Exception as e:
            logger.error(f"Error in bulk publish: {str(e)}")
            return {"error": str(e)}, 500


class PublishSingleSaleResource(Resource):
    """
    POST /api/diraja/etims-sales/<sale_id>/publish
    Publish a single eTims sale to KRA
    """
    @jwt_required()
    @check_role('manager')
    def post(self, sale_id):
        try:
            etims_sale = ETimsSale.query.get(sale_id)
            
            if not etims_sale:
                return {"error": "eTims sale not found"}, 404
            
            if etims_sale.sync_status == ETimsSaleStatus.PUBLISHED:
                return {
                    "message": "Sale already published",
                    "etims_receipt_code": etims_sale.etims_receipt_code
                }, 200
            
            success, message = etims_sale_service.publish_single_sale(etims_sale)
            
            if success:
                return {
                    "message": message,
                    "sale_id": etims_sale.id,
                    "trader_invoice_no": etims_sale.trader_invoice_no,
                    "sync_status": etims_sale.sync_status,
                    "etims_receipt_code": etims_sale.etims_receipt_code
                }, 200
            else:
                return {
                    "error": message,
                    "sale_id": etims_sale.id
                }, 400
                
        except Exception as e:
            logger.error(f"Error publishing sale: {str(e)}")
            return {"error": str(e)}, 500

class GetETimsSalesResource(Resource):
    """
    GET /api/diraja/etims-sales
    Get all eTims sales with full details including items and receipt data
    """
    @jwt_required()
    def get(self):
        try:
            # Query parameters
            sync_status = request.args.get('sync_status')
            shop_id = request.args.get('shop_id', type=int)
            limit = request.args.get('limit', 100, type=int)
            page = request.args.get('page', 1, type=int)
            search = request.args.get('search', '')
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            sort_by = request.args.get('sort_by', 'created_at')
            sort_order = request.args.get('sort_order', 'desc')
            
            # Build query
            query = ETimsSale.query
            
            # Apply filters
            if sync_status:
                query = query.filter_by(sync_status=sync_status)
            if shop_id:
                query = query.filter_by(shop_id=shop_id)
            
            if search:
                query = query.filter(
                    db.or_(
                        ETimsSale.trader_invoice_no.ilike(f'%{search}%'),
                        ETimsSale.customer_name.ilike(f'%{search}%'),
                        ETimsSale.customer_phone.ilike(f'%{search}%'),
                        ETimsSale.etims_receipt_code.ilike(f'%{search}%')
                    )
                )
            
            if start_date:
                query = query.filter(ETimsSale.created_at >= start_date)
            if end_date:
                query = query.filter(ETimsSale.created_at <= end_date)
            
            # Apply sorting
            if sort_order == 'desc':
                query = query.order_by(getattr(ETimsSale, sort_by).desc())
            else:
                query = query.order_by(getattr(ETimsSale, sort_by).asc())
            
            # Pagination
            total = query.count()
            offset = (page - 1) * limit
            sales = query.offset(offset).limit(limit).all()
            
            results = []
            for sale in sales:
                # Get all items with full details
                items = sale.items.all() if sale.items else []
                items_data = []
                for item in items:
                    items_data.append({
                        'id': item.id,
                        'item_code': item.item_code,
                        'item_name': item.item_name,
                        'qty': item.qty,
                        'pkg': item.pkg,
                        'unit_price': item.unit_price,
                        'amount': item.amount,
                        'discount_amount': item.discount_amount,
                        'tax_amount': item.tax_amount,
                        'taxable_amount': item.taxable_amount,
                        'created_at': item.created_at.isoformat() if item.created_at else None
                    })
                
                # Parse etims_response if it exists
                etims_response_data = None
                if sale.etims_response:
                    try:
                        etims_response_data = json.loads(sale.etims_response)
                    except:
                        etims_response_data = sale.etims_response
                
                results.append({
                    'id': sale.id,
                    'local_sale_id': sale.local_sale_id,
                    'shop_id': sale.shop_id,
                    'trader_invoice_no': sale.trader_invoice_no,
                    'total_amount': sale.total_amount,
                    'payment_type': sale.payment_type,
                    'sales_type_code': sale.sales_type_code,
                    'receipt_type_code': sale.receipt_type_code,
                    'sales_status_code': sale.sales_status_code,
                    'sales_date': sale.sales_date,
                    'currency': sale.currency,
                    'exchange_rate': sale.exchange_rate,
                    'customer_pin': sale.customer_pin,
                    'customer_name': sale.customer_name,
                    'customer_phone': sale.customer_phone,
                    'etims_receipt_code': sale.etims_receipt_code,
                    'etims_invoice_no': sale.etims_invoice_no,
                    'etims_response': etims_response_data,
                    'sync_status': sale.sync_status,
                    'sync_attempts': sale.sync_attempts,
                    'last_sync_attempt': sale.last_sync_attempt.isoformat() if sale.last_sync_attempt else None,
                    'sync_error': sale.sync_error,
                    'published_at': sale.published_at.isoformat() if sale.published_at else None,
                    'created_at': sale.created_at.isoformat() if sale.created_at else None,
                    'updated_at': sale.updated_at.isoformat() if sale.updated_at else None,
                    'items_count': len(items_data),
                    'items': items_data
                })
            
            # Get statistics for the filtered results
            stats = {
                'total': total,
                'page': page,
                'limit': limit,
                'total_pages': (total + limit - 1) // limit if limit > 0 else 1,
                'sync_status_counts': {
                    ETimsSaleStatus.PENDING: query.filter_by(sync_status=ETimsSaleStatus.PENDING).count(),
                    ETimsSaleStatus.PUBLISHED: query.filter_by(sync_status=ETimsSaleStatus.PUBLISHED).count(),
                    ETimsSaleStatus.FAILED: query.filter_by(sync_status=ETimsSaleStatus.FAILED).count(),
                    ETimsSaleStatus.RETRY: query.filter_by(sync_status=ETimsSaleStatus.RETRY).count()
                }
            }
            
            return {
                'sales': results,
                'stats': stats
            }, 200
            
        except Exception as e:
            logger.error(f"Error fetching eTims sales: {str(e)}")
            return {"error": str(e)}, 500

class GetETimsSaleStatusResource(Resource):
    """
    GET /api/diraja/etims-sales/<sale_id>/status
    Get publish status of a specific eTims sale
    """
    @jwt_required()
    def get(self, sale_id):
        try:
            sale = ETimsSale.query.get(sale_id)
            
            if not sale:
                return {"error": "eTims sale not found"}, 404
            
            return {
                'sale_id': sale.id,
                'local_sale_id': sale.local_sale_id,
                'trader_invoice_no': sale.trader_invoice_no,
                'sync_status': sale.sync_status,
                'sync_attempts': sale.sync_attempts,
                'published_at': sale.published_at.isoformat() if sale.published_at else None,
                'error': sale.sync_error,
                'etims_receipt_code': sale.etims_receipt_code
            }, 200
            
        except Exception as e:
            logger.error(f"Error getting sale status: {str(e)}")
            return {"error": str(e)}, 500


class RetryFailedSalesResource(Resource):
    """
    POST /api/diraja/etims-sales/retry-failed
    Retry all failed eTims sales
    """
    @jwt_required()
    @check_role('manager')
    def post(self):
        try:
            shop_id = request.args.get('shop_id', type=int)
            results = etims_sale_service.retry_failed_sales(shop_id)
            return results, 200
            
        except Exception as e:
            logger.error(f"Error retrying failed sales: {str(e)}")
            return {"error": str(e)}, 500


class GetETimsSaleStatsResource(Resource):
    """
    GET /api/diraja/etims-sales/stats
    Get eTims sale statistics
    """
    @jwt_required()
    @check_role('manager')
    def get(self):
        try:
            from Server.Models.ETimsSales import ETimsSale, ETimsSaleStatus
            from sqlalchemy import func
            
            shop_id = request.args.get('shop_id', type=int)
            
            query = ETimsSale.query
            if shop_id:
                query = query.filter_by(shop_id=shop_id)
            
            total = query.count()
            pending = query.filter_by(sync_status=ETimsSaleStatus.PENDING).count()
            published = query.filter_by(sync_status=ETimsSaleStatus.PUBLISHED).count()
            failed = query.filter_by(sync_status=ETimsSaleStatus.FAILED).count()
            
            # Get total amount of pending sales
            pending_total = query.filter_by(
                sync_status=ETimsSaleStatus.PENDING
            ).with_entities(func.sum(ETimsSale.total_amount)).scalar() or 0
            
            return {
                'total': total,
                'pending': pending,
                'pending_total_amount': float(pending_total),
                'published': published,
                'failed': failed,
                'last_published': ETimsSale.query.filter(
                    ETimsSale.published_at.isnot(None)
                ).order_by(ETimsSale.published_at.desc()).first().published_at if ETimsSale.query.filter(
                    ETimsSale.published_at.isnot(None)
                ).first() else None
            }, 200
            
        except Exception as e:
            logger.error(f"Error getting eTims sale stats: {str(e)}")
            return {"error": str(e)}, 500


class GetETimsSaleReceiptResource(Resource):
    @jwt_required()
    def get(self, sale_id):
        """GET /api/diraja/etims-sales/<sale_id>/receipt"""
        try:
            sale = ETimsSale.query.get(sale_id)
            if not sale:
                return {"error": "Sale not found"}, 404
            
            if sale.sync_status != ETimsSaleStatus.PUBLISHED:
                return {"error": "Sale has not been published to eTims"}, 400
            
            # Return the stored response
            if sale.etims_response:
                return {
                    "status": 200,
                    "statusCode": "SUCCESS",
                    "message": "Receipt retrieved successfully",
                    "data": json.loads(sale.etims_response)
                }, 200
            else:
                return {"error": "No receipt data available"}, 404
                
        except Exception as e:
            logger.error(f"Error fetching receipt: {str(e)}")
            return {"error": str(e)}, 500