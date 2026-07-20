import logging
import json
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from sqlalchemy.exc import IntegrityError

from Server.Models.ETimsSales import ETimsSale, ETimsSaleItem, ETimsSaleStatus
from Server.Models.StockItems import StockItems
from Server.Views.Services.etims_services import etims_service
from app import db

logger = logging.getLogger(__name__)


class ETimsSaleService:
    """Service for managing eTims sales with bulk publishing"""
    
    @staticmethod
    def create_etims_sale_from_sale(sale_data: Dict, local_sale_id: int, shop_id: int) -> Tuple[bool, Dict]:
        """
        Create an eTims sale record from an existing sale (DOES NOT publish to eTims yet)
        
        Args:
            sale_data: The sale data from your AddSale endpoint
            local_sale_id: The ID of the sale in your local Sales table
            shop_id: The shop ID
            
        Returns:
            Tuple of (success, result_data)
        """
        try:
            # Generate trader invoice number (unique)
            # Format: SHOP{shop_id}-{timestamp}-{sale_id}
            timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
            trader_invoice_no = f"SHOP{shop_id}-{timestamp}-{local_sale_id}"
            
            # Get eTims item codes for each item
            etims_items = []
            total_amount = 0
            
            for item in sale_data.get('items', []):
                # Find the eTims item code for this item
                stock_item = StockItems.query.filter_by(
                    item_name=item.get('item_name')
                ).first()
                
                # Check if we have an eTims code
                etims_item_code = None
                if stock_item and stock_item.etims_synced:
                    etims_item_code = stock_item.etims_item_code
                    logger.info(f"✅ Found eTims code {etims_item_code} for '{item.get('item_name')}'")
                else:
                    logger.warning(f"⚠️  No eTims code found for '{item.get('item_name')}'")
                    # Skip this item if no eTims code
                    continue
                
                item_total = float(item.get('total_price', 0))
                total_amount += item_total
                
                etims_items.append({
                    'item_code': etims_item_code,
                    'item_name': item.get('item_name'),
                    'qty': float(item.get('quantity', 1)),
                    'pkg': 0,
                    'unit_price': float(item.get('unit_price', 0)),
                    'amount': item_total,
                    'discount_amount': 0,
                    'tax_amount': 0,
                    'taxable_amount': item_total
                })
            
            if not etims_items:
                return False, {
                    'error': 'No valid eTims items found for this sale. Please ensure items have eTims codes.'
                }
            
            # Format sale date
            sale_date = sale_data.get('sale_date')
            if sale_date:
                try:
                    dt = datetime.strptime(sale_date, "%Y-%m-%d")
                    sales_date = dt.strftime('%Y%m%d') + '000000'
                except:
                    sales_date = datetime.utcnow().strftime('%Y%m%d%H%M%S')
            else:
                sales_date = datetime.utcnow().strftime('%Y%m%d%H%M%S')
            
            # Determine payment type
            payment_methods = sale_data.get('payment_methods', [])
            if payment_methods:
                method = payment_methods[0].get('method', '').lower()
                if method == 'cash':
                    payment_type = '01'
                elif method in ['card', 'sasapay']:
                    payment_type = '02'
                elif method == 'mobile':
                    payment_type = '03'
                else:
                    payment_type = '01'
            else:
                payment_type = '01'
            
            # Get customer PIN from data (if available)
            customer_pin = sale_data.get('customer_pin', None)
            customer_name = sale_data.get('customer_name', '')
            customer_phone = sale_data.get('customer_number', '')
            
            # Create eTims sale record
            etims_sale = ETimsSale(
                local_sale_id=local_sale_id,
                shop_id=shop_id,
                trader_invoice_no=trader_invoice_no,
                total_amount=total_amount,
                payment_type=payment_type,
                sales_type_code='N',  # Normal sale
                receipt_type_code='S',  # Sales receipt
                sales_status_code='01',  # Final
                sales_date=sales_date,
                currency='KES',
                exchange_rate=1.0,
                customer_pin=customer_pin,
                customer_name=customer_name,
                customer_phone=customer_phone,
                sync_status=ETimsSaleStatus.PENDING
            )
            
            db.session.add(etims_sale)
            db.session.flush()  # Get ID without committing
            
            # Add eTims sale items
            for item in etims_items:
                # ✅ FIX: Remove stock_item_id from ETimsSaleItem creation
                etims_item = ETimsSaleItem(
                    etims_sale_id=etims_sale.id,
                    item_code=item['item_code'],
                    item_name=item['item_name'],
                    qty=item['qty'],
                    pkg=item.get('pkg', 0),
                    unit_price=item['unit_price'],
                    amount=item['amount'],
                    discount_amount=item.get('discount_amount', 0),
                    tax_amount=item.get('tax_amount', 0),
                    taxable_amount=item.get('taxable_amount', item['amount'])
                )
                db.session.add(etims_item)
            
            db.session.commit()
            
            return True, {
                'message': 'eTims sale record created successfully (pending publish)',
                'etims_sale': {
                    'id': etims_sale.id,
                    'trader_invoice_no': etims_sale.trader_invoice_no,
                    'total_amount': etims_sale.total_amount,
                    'sync_status': etims_sale.sync_status,
                    'items_count': len(etims_items)
                }
            }
            
        except IntegrityError as e:
            db.session.rollback()
            logger.error(f"Integrity error creating eTims sale: {str(e)}")
            return False, {'error': 'Duplicate trader invoice number'}
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating eTims sale: {str(e)}")
            return False, {'error': str(e)}
    
    @staticmethod
    def get_pending_sales(shop_id: int = None) -> List[ETimsSale]:
        """
        Get all pending eTims sales
        
        Args:
            shop_id: Optional shop ID to filter
            
        Returns:
            List of ETimsSale objects
        """
        try:
            query = ETimsSale.query.filter_by(sync_status=ETimsSaleStatus.PENDING)
            if shop_id:
                query = query.filter_by(shop_id=shop_id)
            return query.order_by(ETimsSale.created_at).all()
        except Exception as e:
            logger.error(f"Error getting pending eTims sales: {str(e)}")
            return []
    
    @staticmethod
    def get_published_sales(shop_id: int = None) -> List[ETimsSale]:
        """
        Get all published eTims sales
        
        Args:
            shop_id: Optional shop ID to filter
            
        Returns:
            List of ETimsSale objects
        """
        try:
            query = ETimsSale.query.filter_by(sync_status=ETimsSaleStatus.PUBLISHED)
            if shop_id:
                query = query.filter_by(shop_id=shop_id)
            return query.order_by(ETimsSale.published_at.desc()).all()
        except Exception as e:
            logger.error(f"Error getting published eTims sales: {str(e)}")
            return []
    
    @staticmethod
    def get_failed_sales(shop_id: int = None) -> List[ETimsSale]:
        """
        Get all failed eTims sales
        
        Args:
            shop_id: Optional shop ID to filter
            
        Returns:
            List of ETimsSale objects
        """
        try:
            query = ETimsSale.query.filter_by(sync_status=ETimsSaleStatus.FAILED)
            if shop_id:
                query = query.filter_by(shop_id=shop_id)
            return query.order_by(ETimsSale.created_at).all()
        except Exception as e:
            logger.error(f"Error getting failed eTims sales: {str(e)}")
            return []
    
    @staticmethod
    def get_sale_by_id(sale_id: int) -> Optional[ETimsSale]:
        """
        Get an eTims sale by ID
        
        Args:
            sale_id: ETimsSale ID
            
        Returns:
            ETimsSale object or None
        """
        try:
            return ETimsSale.query.get(sale_id)
        except Exception as e:
            logger.error(f"Error getting eTims sale: {str(e)}")
            return None
    
    @staticmethod
    def get_sale_by_trader_no(trader_invoice_no: str) -> Optional[ETimsSale]:
        """
        Get an eTims sale by trader invoice number
        
        Args:
            trader_invoice_no: Trader invoice number
            
        Returns:
            ETimsSale object or None
        """
        try:
            return ETimsSale.query.filter_by(
                trader_invoice_no=trader_invoice_no
            ).first()
        except Exception as e:
            logger.error(f"Error getting eTims sale: {str(e)}")
            return None
    
    @staticmethod
    def publish_single_sale(etims_sale: ETimsSale) -> Tuple[bool, str]:
        """
        Publish a single eTims sale to KRA
        
        Args:
            etims_sale: ETimsSale object
            
        Returns:
            Tuple of (success, message)
        """
        try:
            # Update sync attempt
            etims_sale.sync_attempts += 1
            etims_sale.last_sync_attempt = datetime.utcnow()
            
            # Prepare payload
            payload = etims_sale.to_etims_payload()
            
            logger.info(f"📤 Publishing sale {etims_sale.trader_invoice_no} to eTims")
            logger.debug(f"Payload: {json.dumps(payload, indent=2)}")
            
            # Send to eTims
            response = etims_service.generate_invoice(payload)
            
            if not response['success']:
                error_msg = response.get('error', 'Unknown error')
                etims_sale.sync_status = ETimsSaleStatus.FAILED
                etims_sale.sync_error = error_msg
                etims_sale.etims_response = json.dumps(response.get('data', {}))
                db.session.commit()
                return False, error_msg
            
            # Extract eTims response
            etims_data = response.get('data', {})
            etims_receipt_code = (
                etims_data.get('receiptCode') or 
                etims_data.get('invoiceCode') or 
                etims_data.get('receiptCode') or
                etims_data.get('data', {}).get('receiptCode')
            )
            
            # Update sale with eTims data
            etims_sale.etims_receipt_code = etims_receipt_code
            etims_sale.etims_invoice_no = etims_data.get('invoiceNo') or etims_data.get('invoiceNumber')
            etims_sale.etims_response = json.dumps(etims_data)
            etims_sale.sync_status = ETimsSaleStatus.PUBLISHED
            etims_sale.published_at = datetime.utcnow()
            etims_sale.sync_error = None
            
            db.session.commit()
            
            logger.info(f"✅ Sale {etims_sale.trader_invoice_no} published successfully: {etims_receipt_code}")
            return True, f'Successfully published: {etims_receipt_code}'
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error publishing sale {etims_sale.id}: {str(e)}")
            etims_sale.sync_status = ETimsSaleStatus.FAILED
            etims_sale.sync_error = str(e)
            db.session.commit()
            return False, str(e)
    
    @staticmethod
    def bulk_publish_sales(shop_id: int = None, limit: int = None) -> Dict:
        """
        Bulk publish all pending eTims sales
        
        Args:
            shop_id: Optional shop ID to filter
            limit: Optional limit on number of sales to publish
            
        Returns:
            Dictionary with publish results
        """
        results = {
            'total': 0,
            'published': 0,
            'failed': 0,
            'skipped': 0,
            'details': []
        }
        
        try:
            pending_sales = ETimsSaleService.get_pending_sales(shop_id)
            
            if limit:
                pending_sales = pending_sales[:limit]
            
            results['total'] = len(pending_sales)
            
            if results['total'] == 0:
                return {
                    'message': 'No pending eTims sales to publish',
                    'results': results
                }
            
            logger.info(f"📤 Starting bulk publish for {results['total']} sales...")
            
            for sale in pending_sales:
                success, message = ETimsSaleService.publish_single_sale(sale)
                
                results['details'].append({
                    'sale_id': sale.id,
                    'local_sale_id': sale.local_sale_id,
                    'trader_invoice_no': sale.trader_invoice_no,
                    'total_amount': sale.total_amount,
                    'success': success,
                    'message': message
                })
                
                if success:
                    results['published'] += 1
                else:
                    results['failed'] += 1
            
            return {
                'message': f'Bulk publish completed: {results["published"]} published, {results["failed"]} failed',
                'results': results
            }
            
        except Exception as e:
            logger.error(f"Error in bulk publish: {str(e)}")
            return {
                'error': str(e),
                'results': results
            }
    
    @staticmethod
    def retry_failed_sales(shop_id: int = None) -> Dict:
        """
        Retry all failed eTims sales
        
        Args:
            shop_id: Optional shop ID to filter
            
        Returns:
            Dictionary with retry results
        """
        failed_sales = ETimsSaleService.get_failed_sales(shop_id)
        
        results = {
            'total': len(failed_sales),
            'retried': 0,
            'failed': 0,
            'details': []
        }
        
        if results['total'] == 0:
            return {
                'message': 'No failed eTims sales to retry',
                'results': results
            }
        
        for sale in failed_sales:
            # Reset to pending and try again
            sale.sync_status = ETimsSaleStatus.PENDING
            sale.sync_attempts += 1
            db.session.commit()
            
            success, message = ETimsSaleService.publish_single_sale(sale)
            
            results['details'].append({
                'sale_id': sale.id,
                'trader_invoice_no': sale.trader_invoice_no,
                'success': success,
                'message': message
            })
            
            if success:
                results['retried'] += 1
            else:
                results['failed'] += 1
        
        return {
            'message': f'Retry completed: {results["retried"]} retried, {results["failed"]} failed',
            'results': results
        }
    
    @staticmethod
    def get_sale_status(sale_id: int) -> Dict:
        """
        Get the status of an eTims sale
        
        Args:
            sale_id: ETimsSale ID
            
        Returns:
            Dictionary with sale status information
        """
        try:
            sale = ETimsSale.query.get(sale_id)
            
            if not sale:
                return {'error': 'Sale not found'}
            
            return {
                'sale_id': sale.id,
                'local_sale_id': sale.local_sale_id,
                'trader_invoice_no': sale.trader_invoice_no,
                'total_amount': sale.total_amount,
                'sync_status': sale.sync_status,
                'sync_attempts': sale.sync_attempts,
                'last_sync_attempt': sale.last_sync_attempt.isoformat() if sale.last_sync_attempt else None,
                'published_at': sale.published_at.isoformat() if sale.published_at else None,
                'error': sale.sync_error,
                'etims_receipt_code': sale.etims_receipt_code,
                'etims_invoice_no': sale.etims_invoice_no,
                'created_at': sale.created_at.isoformat() if sale.created_at else None,
                'items_count': sale.items.count()
            }
            
        except Exception as e:
            logger.error(f"Error getting sale status: {str(e)}")
            return {'error': str(e)}
    
    @staticmethod
    def get_stats(shop_id: int = None) -> Dict:
        """
        Get eTims sale statistics
        
        Args:
            shop_id: Optional shop ID to filter
            
        Returns:
            Dictionary with statistics
        """
        try:
            from sqlalchemy import func
            
            query = ETimsSale.query
            if shop_id:
                query = query.filter_by(shop_id=shop_id)
            
            total = query.count()
            pending = query.filter_by(sync_status=ETimsSaleStatus.PENDING).count()
            published = query.filter_by(sync_status=ETimsSaleStatus.PUBLISHED).count()
            failed = query.filter_by(sync_status=ETimsSaleStatus.FAILED).count()
            
            # Get total amounts
            pending_total = query.filter_by(
                sync_status=ETimsSaleStatus.PENDING
            ).with_entities(func.sum(ETimsSale.total_amount)).scalar() or 0
            
            published_total = query.filter_by(
                sync_status=ETimsSaleStatus.PUBLISHED
            ).with_entities(func.sum(ETimsSale.total_amount)).scalar() or 0
            
            # Get last published date
            last_published = ETimsSale.query.filter(
                ETimsSale.sync_status == ETimsSaleStatus.PUBLISHED
            ).order_by(ETimsSale.published_at.desc()).first()
            
            return {
                'total': total,
                'pending': pending,
                'pending_total_amount': float(pending_total),
                'published': published,
                'published_total_amount': float(published_total),
                'failed': failed,
                'last_published_at': last_published.published_at.isoformat() if last_published and last_published.published_at else None,
                'last_published_sale': {
                    'id': last_published.id,
                    'trader_invoice_no': last_published.trader_invoice_no,
                    'total_amount': last_published.total_amount
                } if last_published else None
            }
            
        except Exception as e:
            logger.error(f"Error getting eTims sale stats: {str(e)}")
            return {
                'total': 0,
                'pending': 0,
                'pending_total_amount': 0,
                'published': 0,
                'published_total_amount': 0,
                'failed': 0,
                'last_published_at': None,
                'last_published_sale': None,
                'error': str(e)
            }
    
    @staticmethod
    def delete_sale(sale_id: int, force: bool = False) -> Tuple[bool, Dict]:
        """
        Delete an eTims sale record
        
        Args:
            sale_id: ETimsSale ID
            force: If True, delete even if published
            
        Returns:
            Tuple of (success, result_data)
        """
        try:
            sale = ETimsSale.query.get(sale_id)
            
            if not sale:
                return False, {'error': 'Sale not found'}
            
            # Check if published and not forced
            if sale.sync_status == ETimsSaleStatus.PUBLISHED and not force:
                return False, {
                    'error': 'Cannot delete published sale. Use force=True to override.'
                }
            
            # Delete items first (cascade should handle this)
            # But we'll do it explicitly
            ETimsSaleItem.query.filter_by(etims_sale_id=sale_id).delete()
            
            db.session.delete(sale)
            db.session.commit()
            
            return True, {
                'message': f'eTims sale {sale.trader_invoice_no} deleted successfully'
            }
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error deleting eTims sale: {str(e)}")
            return False, {'error': str(e)}


# Create a global instance
etims_sale_service = ETimsSaleService()