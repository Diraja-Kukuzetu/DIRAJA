import requests
import json
import logging
from datetime import datetime
from requests.auth import HTTPBasicAuth
from typing import Dict, Optional, Tuple, List
from sqlalchemy.exc import IntegrityError

from Server.Models.StockItems import StockItems, EtimsItem
from app import db

logger = logging.getLogger(__name__)

class ETimsService:
    def __init__(self):
        self.base_url = None
        self.username = None
        self.password = None
        self.initialize_config()
    
    def initialize_config(self):
        """Initialize configuration from Flask app config"""
        try:
            from flask import current_app
            self.base_url = current_app.config.get('ETIMS_BASE_URL', 'http://197.232.172.26:8888')
            self.username = current_app.config.get('ETIMS_USERNAME', 'admin')
            self.password = current_app.config.get('ETIMS_PASSWORD', 'admin')
        except RuntimeError:
            import os
            self.base_url = os.getenv('ETIMS_BASE_URL', 'http://197.232.172.26:8888')
            self.username = os.getenv('ETIMS_USERNAME', 'admin')
            self.password = os.getenv('ETIMS_PASSWORD', 'admin')
    
    def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Dict:
        """Make HTTP request to eTims API with Basic Auth"""
        if not endpoint.startswith('/'):
            endpoint = '/' + endpoint
        
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = requests.request(
                method=method,
                url=url,
                auth=HTTPBasicAuth(self.username, self.password),
                json=data,
                headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
                timeout=30
            )
            
            # Try to parse JSON response
            try:
                result = response.json()
            except:
                result = {'message': response.text}
            
            # Check for error status
            if response.status_code >= 400:
                error_msg = result.get('message', result.get('error', response.text[:200]))
                logger.error(f"eTims API Error {response.status_code}: {error_msg}")
                return {
                    'success': False,
                    'error': error_msg,
                    'status_code': response.status_code,
                    'data': result
                }
            
            return {
                'success': True,
                'status_code': response.status_code,
                'data': result
            }
            
        except requests.exceptions.Timeout:
            logger.error("eTims API Timeout")
            return {'success': False, 'error': 'Request timeout'}
        except requests.exceptions.ConnectionError:
            logger.error("eTims API Connection Error")
            return {'success': False, 'error': 'Connection error'}
        except Exception as e:
            logger.error(f"eTims API Error: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    # ==========================================================
    # REFERENCE DATA ENDPOINTS
    # ==========================================================
    
    def get_countries(self) -> Dict:
        return self._make_request('GET', '/countries')
    
    def get_currencies(self) -> Dict:
        return self._make_request('GET', '/currencies')
    
    def get_qty_unit_codes(self) -> Dict:
        return self._make_request('GET', '/qtyunitcodes')
    
    def get_pkg_unit_codes(self) -> Dict:
        return self._make_request('GET', '/pkgunitcodes')
    
    def get_item_codes(self) -> Dict:
        return self._make_request('GET', '/itemcodes')
    
    def get_branches(self) -> Dict:
        return self._make_request('GET', '/branches')
    
    def get_notices(self) -> Dict:
        return self._make_request('GET', '/notices')
    
    # ==========================================================
    # ITEMS ENDPOINTS
    # ==========================================================
    
    def create_item(self, item_data: Dict) -> Dict:
        return self._make_request('POST', '/items', item_data)
    
    def get_items(self) -> Dict:
        return self._make_request('GET', '/items')
    
    def get_item_by_code(self, item_code: str) -> Dict:
        return self._make_request('GET', f'/items/{item_code}')
    
    def update_item(self, item_code: str, item_data: Dict) -> Dict:
        return self._make_request('PUT', f'/items/{item_code}', item_data)
    
    def delete_item(self, item_code: str) -> Dict:
        return self._make_request('DELETE', f'/items/{item_code}')
    
    # ==========================================================
    # INVOICE/INVOICE ENDPOINTS (SALES)
    # ==========================================================
    
    def generate_invoice(self, invoice_data: Dict) -> Dict:
        """
        Generate an invoice in eTims (for sales)
        
        Args:
            invoice_data: Invoice payload matching eTims format
            
        Returns:
            Dict with success status and response data
        """
        return self._make_request('POST', '/invoices', invoice_data)
    
    def get_invoices(self) -> Dict:
        """Fetch all invoices from eTims"""
        return self._make_request('GET', '/invoices')
    
    def get_invoice_by_trader_no(self, trader_invoice_no: str) -> Dict:
        """Fetch a specific invoice by trader invoice number"""
        return self._make_request('GET', f'/invoices/{trader_invoice_no}')
    
    # ==========================================================
    # CUSTOMERS ENDPOINTS
    # ==========================================================
    
    def create_customer(self, customer_data: Dict) -> Dict:
        return self._make_request('POST', '/customers', customer_data)
    
    def get_customers(self) -> Dict:
        return self._make_request('GET', '/customers')
    
    # ==========================================================
    # PURCHASES ENDPOINTS
    # ==========================================================
    
    def query_purchases(self, last_request_date: str) -> Dict:
        """Query purchases from KRA"""
        return self._make_request('GET', f'/purchases/queries?last_request_date={last_request_date}')
    
    def save_converted_purchases(self, purchase_data: Dict) -> Dict:
        """Save converted purchases"""
        return self._make_request('POST', '/purchases/queries/converted', purchase_data)
    
    # ==========================================================
    # STOCK ENDPOINTS
    # ==========================================================
    
    def get_stock_transfers(self, last_request_date: str) -> Dict:
        """Get stock transfers of branch"""
        return self._make_request('GET', f'/stock/transfer/queries?last_request_date={last_request_date}')
    
    def save_stock_movements(self, stock_data: Dict) -> Dict:
        """Save stock movements"""
        return self._make_request('POST', '/stock/transfer/queries/receive', stock_data)
    
    def move_stock(self, stock_data: Dict) -> Dict:
        """Move stock"""
        return self._make_request('POST', '/stock/transfers', stock_data)
    
    # ==========================================================
    # IMPORTS ENDPOINTS
    # ==========================================================
    
    def query_imports(self, last_request_date: str) -> Dict:
        """Query imports from KRA"""
        return self._make_request('GET', f'/imports/queries?last_request_date={last_request_date}')
    
    def save_converted_imports(self, import_data: Dict) -> Dict:
        """Save converted imports"""
        return self._make_request('POST', '/imports/queries/converted', import_data)
    
    # ==========================================================
    # BUSINESS LOGIC METHODS - ITEMS
    # ==========================================================
    
    def prepare_etims_payload(self, stock_item: StockItems) -> Dict:
        """Convert StockItems model to eTims API payload"""
        return {
            "name": stock_item.item_name,
            "orgCountryCode": getattr(stock_item, 'org_country_code', 'KE'),
            "unitPrice": float(stock_item.unit_price or 0),
            "itemTypeCode": getattr(stock_item, 'item_type_code', '1'),
            "taxCode": getattr(stock_item, 'tax_code', 'A'),
            "qtyUnitCode": getattr(stock_item, 'qty_unit_code', 'U'),
            "pkgUnitCode": getattr(stock_item, 'pkg_unit_code', 'CT'),
            "itemClassCode": getattr(stock_item, 'item_class_code', '99000000'),
            "initialStock": getattr(stock_item, 'initial_stock', 0)
        }
    
    def _save_etims_item(self, stock_item: StockItems, etims_response_data: Dict, etims_item_code: str) -> bool:
        """
        Save eTims item to EtimsItem model
        
        Args:
            stock_item: The local StockItems object
            etims_response_data: The full response from eTims API
            etims_item_code: The eTims item code extracted from response
        
        Returns:
            bool: True if saved successfully
        """
        try:
            # Check if EtimsItem already exists
            existing = EtimsItem.query.filter_by(item_code=etims_item_code).first()
            if existing:
                logger.info(f"EtimsItem already exists for code: {etims_item_code}")
                return True
            
            # Create new EtimsItem
            etims_item = EtimsItem(
                item_code=etims_item_code,
                name=stock_item.item_name,
                org_country_code=stock_item.org_country_code,
                unit_price=stock_item.unit_price,
                item_type_code=stock_item.item_type_code,
                tax_code=stock_item.tax_code,
                qty_unit_code=stock_item.qty_unit_code,
                pkg_unit_code=stock_item.pkg_unit_code,
                item_class_code=stock_item.item_class_code,
                stock=stock_item.initial_stock or 0,
                local_item_id=stock_item.id,
            )
            
            db.session.add(etims_item)
            db.session.commit()
            logger.info(f"✅ EtimsItem saved successfully: {etims_item_code}")
            return True
            
        except IntegrityError:
            db.session.rollback()
            logger.warning(f"EtimsItem already exists (integrity error): {etims_item_code}")
            return True
        except Exception as e:
            db.session.rollback()
            logger.error(f"❌ Failed to save EtimsItem: {str(e)}")
            return False
    
    def create_and_sync_item(self, stock_item_data: Dict) -> Tuple[bool, Dict]:
        """
        Create a new stock item locally AND sync to eTims, then save to EtimsItem
        
        Args:
            stock_item_data: Dictionary with stock item fields
            
        Returns:
            Tuple of (success, result_data)
        """
        try:
            # Create local stock item first
            new_item = StockItems(
                item_name=stock_item_data.get('item_name'),
                item_code=stock_item_data.get('item_code'),
                unit_price=stock_item_data.get('unit_price'),
                pack_price=stock_item_data.get('pack_price'),
                pack_quantity=stock_item_data.get('pack_quantity'),
                category=stock_item_data.get('category'),
                org_country_code=stock_item_data.get('org_country_code', 'KE'),
                item_type_code=stock_item_data.get('item_type_code', '1'),
                tax_code=stock_item_data.get('tax_code', 'A'),
                qty_unit_code=stock_item_data.get('qty_unit_code', 'U'),
                pkg_unit_code=stock_item_data.get('pkg_unit_code', 'CT'),
                item_class_code=stock_item_data.get('item_class_code', '99000000'),
                initial_stock=stock_item_data.get('initial_stock', 0)
            )
            
            db.session.add(new_item)
            db.session.flush()  # Get ID without committing
            
            # Prepare eTims payload
            etims_payload = self.prepare_etims_payload(new_item)
            
            # Send to eTims
            logger.info(f"📤 Sending to eTims: {json.dumps(etims_payload)}")
            etims_response = self.create_item(etims_payload)
            
            if not etims_response['success']:
                # Rollback local item if eTims sync fails
                db.session.rollback()
                return False, {
                    'error': f'eTims sync failed: {etims_response.get("error")}',
                    'etims_response': etims_response.get('data')
                }
            
            # Extract item code from response
            etims_data = etims_response['data']
            etims_item_code = (
                etims_data.get('itemCode') or 
                etims_data.get('code') or 
                etims_data.get('item_code') or
                etims_data.get('data', {}).get('itemCode')
            )
            
            if not etims_item_code:
                logger.warning(f"Could not extract item code from response: {etims_data}")
                etims_item_code = "UNKNOWN"
            
            # Update local item with eTims code
            new_item.etims_item_code = etims_item_code
            new_item.etims_synced = True
            new_item.etims_sync_date = datetime.utcnow()
            
            # ✅ SAVE TO ETIMSITEM MODEL
            etims_saved = self._save_etims_item(new_item, etims_data, etims_item_code)
            
            if not etims_saved:
                logger.warning(f"⚠️  Failed to save EtimsItem, but item was synced to eTims")
            
            db.session.commit()
            
            return True, {
                'message': 'Stock item created successfully and synced to eTims',
                'stock_item': {
                    'id': new_item.id,
                    'item_name': new_item.item_name,
                    'item_code': new_item.item_code,
                    'unit_price': new_item.unit_price,
                    'pack_price': new_item.pack_price,
                    'pack_quantity': new_item.pack_quantity,
                    'category': new_item.category,
                    'etims_synced': new_item.etims_synced,
                    'etims_item_code': new_item.etims_item_code,
                    'etims_saved': etims_saved
                },
                'etims_response': etims_data
            }
            
        except IntegrityError as e:
            db.session.rollback()
            logger.error(f"Database integrity error: {str(e)}")
            return False, {'error': 'Item already exists'}
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating and syncing item: {str(e)}")
            return False, {'error': str(e)}
    
    def sync_item_to_etims(self, stock_item: StockItems) -> Tuple[bool, Dict]:
        """
        Sync an existing stock item to eTims and save to EtimsItem
        
        Args:
            stock_item: StockItems object to sync
            
        Returns:
            Tuple of (success, result_data)
        """
        try:
            # Check if already synced
            if getattr(stock_item, 'etims_synced', False):
                return False, {
                    'error': 'Item already synced to eTims',
                    'etims_item_code': getattr(stock_item, 'etims_item_code', None)
                }
            
            # Prepare payload
            payload = self.prepare_etims_payload(stock_item)
            
            # Send to eTims
            logger.info(f"📤 Syncing to eTims: {json.dumps(payload)}")
            response = self.create_item(payload)
            
            if not response['success']:
                return False, {
                    'error': f'eTims sync failed: {response.get("error")}',
                    'etims_response': response.get('data')
                }
            
            # Extract item code from response
            etims_data = response['data']
            etims_item_code = (
                etims_data.get('itemCode') or 
                etims_data.get('code') or 
                etims_data.get('item_code') or
                etims_data.get('data', {}).get('itemCode')
            )
            
            if not etims_item_code:
                logger.warning(f"Could not extract item code from response: {etims_data}")
                etims_item_code = "UNKNOWN"
            
            # Update stock item with eTims data
            stock_item.etims_item_code = etims_item_code
            stock_item.etims_synced = True
            stock_item.etims_sync_date = datetime.utcnow()
            
            # ✅ SAVE TO ETIMSITEM MODEL
            etims_saved = self._save_etims_item(stock_item, etims_data, etims_item_code)
            
            db.session.commit()
            
            return True, {
                'success': True,
                'message': 'Item synced to eTims successfully',
                'etims_item_code': etims_item_code,
                'etims_saved': etims_saved,
                'etims_response': etims_data
            }
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error syncing item to eTims: {str(e)}")
            return False, {'error': str(e)}
    
    def sync_all_unsynced_items(self) -> Dict:
        """
        Sync all items that haven't been synced to eTims yet
        
        Returns:
            Dictionary with sync results
        """
        results = {
            'total': 0,
            'synced': 0,
            'failed': 0,
            'errors': []
        }
        
        try:
            # Find all unsynced items
            unsynced_items = StockItems.query.filter_by(etims_synced=False).all()
            results['total'] = len(unsynced_items)
            
            for item in unsynced_items:
                success, result = self.sync_item_to_etims(item)
                if success:
                    results['synced'] += 1
                else:
                    results['failed'] += 1
                    results['errors'].append({
                        'item_id': item.id,
                        'item_name': item.item_name,
                        'error': result.get('error', 'Unknown error')
                    })
            
            return results
            
        except Exception as e:
            logger.error(f"Error in bulk sync: {str(e)}")
            return {
                'error': str(e),
                **results
            }
    
    # ==========================================================
    # BUSINESS LOGIC METHODS - INVOICES (SALES)
    # ==========================================================
    
    def prepare_invoice_payload(self, sale_data: Dict, items: List[Dict], customer_pin: str = None) -> Dict:
        """
        Prepare invoice payload for eTims API
        
        Args:
            sale_data: Sale data dictionary
            items: List of sale items with eTims item codes
            customer_pin: Customer PIN (optional for B2C)
            
        Returns:
            Dict with eTims invoice payload
        """
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
        
        # Calculate total
        total_amount = sum(float(item.get('total_price', 0)) for item in items)
        
        # Prepare sales items
        sales_items = []
        for item in items:
            sales_items.append({
                "itemCode": item.get('etims_item_code', item.get('item_code')),
                "qty": float(item.get('quantity', 1)),
                "pkg": float(item.get('pkg', 0)),
                "unitPrice": float(item.get('unit_price', 0)),
                "amount": float(item.get('total_price', 0)),
                "discountAmount": float(item.get('discount_amount', 0))
            })
        
        return {
            "traderInvoiceNo": sale_data.get('trader_invoice_no'),
            "totalAmount": total_amount,
            "paymentType": payment_type,
            "salesTypeCode": "N",
            "receiptTypeCode": "S",
            "salesStatusCode": "01",
            "salesDate": sales_date,
            "currency": "KES",
            "exchangeRate": 1.0,
            "customerPin": customer_pin or "",
            "salesItems": sales_items
        }
    
    def create_and_sync_invoice(self, sale_data: Dict, local_sale_id: int, shop_id: int, items: List[Dict]) -> Tuple[bool, Dict]:
        """
        Create an eTims invoice from a sale and immediately publish to eTims
        
        NOTE: This is for immediate sync. For bulk sync, use the ETimsSale model instead.
        
        Args:
            sale_data: Sale data dictionary
            local_sale_id: Local sale ID
            shop_id: Shop ID
            items: List of sale items
            
        Returns:
            Tuple of (success, result_data)
        """
        try:
            from Server.Models.ETimsSales import ETimsSale, ETimsSaleStatus
            
            # Generate trader invoice number
            timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
            trader_invoice_no = f"SHOP{shop_id}-{timestamp}-{local_sale_id}"
            
            # Get eTims item codes for each item
            from Server.Models.StockItems import StockItems
            
            etims_items = []
            for item in items:
                stock_item = StockItems.query.filter_by(
                    item_name=item.get('item_name'),
                    shop_id=shop_id
                ).first()
                
                if stock_item and stock_item.etims_item_code:
                    etims_items.append({
                        **item,
                        'etims_item_code': stock_item.etims_item_code
                    })
                else:
                    logger.warning(f"Item '{item.get('item_name')}' has no eTims code")
                    # Use a default code if needed
                    etims_items.append({
                        **item,
                        'etims_item_code': '99000000'  # Default code
                    })
            
            # Prepare payload
            payload = self.prepare_invoice_payload(
                sale_data={**sale_data, 'trader_invoice_no': trader_invoice_no},
                items=etims_items,
                customer_pin=sale_data.get('customer_pin')
            )
            
            # Send to eTims
            logger.info(f"📤 Publishing invoice to eTims: {trader_invoice_no}")
            response = self.generate_invoice(payload)
            
            if not response['success']:
                return False, {
                    'error': f'eTims invoice failed: {response.get("error")}',
                    'etims_response': response.get('data')
                }
            
            # Extract eTims response
            etims_data = response['data']
            etims_receipt_code = (
                etims_data.get('receiptCode') or 
                etims_data.get('invoiceCode') or 
                etims_data.get('receiptCode')
            )
            
            return True, {
                'message': 'Invoice published to eTims successfully',
                'trader_invoice_no': trader_invoice_no,
                'etims_receipt_code': etims_receipt_code,
                'etims_response': etims_data
            }
            
        except Exception as e:
            logger.error(f"Error creating and syncing invoice: {str(e)}")
            return False, {'error': str(e)}
    
    # ==========================================================
    # BULK SYNC HELPER METHODS
    # ==========================================================
    
    def get_pending_etims_sales(self, shop_id: int = None) -> List:
        """
        Get pending eTims sales from the ETimsSale model
        
        Args:
            shop_id: Optional shop ID filter
            
        Returns:
            List of ETimsSale objects
        """
        try:
            from Server.Models.ETimsSales import ETimsSale, ETimsSaleStatus
            
            query = ETimsSale.query.filter_by(sync_status=ETimsSaleStatus.PENDING)
            if shop_id:
                query = query.filter_by(shop_id=shop_id)
            
            return query.order_by(ETimsSale.created_at).all()
            
        except Exception as e:
            logger.error(f"Error getting pending eTims sales: {str(e)}")
            return []
    
    def get_failed_etims_sales(self, shop_id: int = None) -> List:
        """
        Get failed eTims sales from the ETimsSale model
        
        Args:
            shop_id: Optional shop ID filter
            
        Returns:
            List of ETimsSale objects
        """
        try:
            from Server.Models.ETimsSales import ETimsSale, ETimsSaleStatus
            
            query = ETimsSale.query.filter_by(sync_status=ETimsSaleStatus.FAILED)
            if shop_id:
                query = query.filter_by(shop_id=shop_id)
            
            return query.order_by(ETimsSale.created_at).all()
            
        except Exception as e:
            logger.error(f"Error getting failed eTims sales: {str(e)}")
            return []
    
    def get_etims_sale_stats(self, shop_id: int = None) -> Dict:
        """
        Get statistics for eTims sales
        
        Args:
            shop_id: Optional shop ID filter
            
        Returns:
            Dict with statistics
        """
        try:
            from Server.Models.ETimsSales import ETimsSale, ETimsSaleStatus
            from sqlalchemy import func
            
            query = ETimsSale.query
            if shop_id:
                query = query.filter_by(shop_id=shop_id)
            
            total = query.count()
            pending = query.filter_by(sync_status=ETimsSaleStatus.PENDING).count()
            published = query.filter_by(sync_status=ETimsSaleStatus.PUBLISHED).count()
            failed = query.filter_by(sync_status=ETimsSaleStatus.FAILED).count()
            
            pending_total = query.filter_by(
                sync_status=ETimsSaleStatus.PENDING
            ).with_entities(func.sum(ETimsSale.total_amount)).scalar() or 0
            
            return {
                'total': total,
                'pending': pending,
                'pending_total_amount': float(pending_total),
                'published': published,
                'failed': failed
            }
            
        except Exception as e:
            logger.error(f"Error getting eTims sale stats: {str(e)}")
            return {
                'total': 0,
                'pending': 0,
                'pending_total_amount': 0,
                'published': 0,
                'failed': 0,
                'error': str(e)
            }


# Create a global instance
etims_service = ETimsService()