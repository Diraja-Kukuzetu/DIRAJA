from flask_sqlalchemy import SQLAlchemy
from app import db
from datetime import datetime
from sqlalchemy import Enum, func

class ETimsSaleStatus:
    """Status constants for eTims sales"""
    PENDING = 'pending'      # Created, waiting to be published
    PUBLISHED = 'published'  # Successfully published to eTims
    FAILED = 'failed'        # Failed to publish
    RETRY = 'retry'          # Will retry

class ETimsSale(db.Model):
    """
    eTims Sales model - stores sales that need to be published to KRA
    """
    __tablename__ = 'etims_sales'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Reference to your local sale
    local_sale_id = db.Column(db.Integer, nullable=False, index=True)
    shop_id = db.Column(db.Integer, nullable=False, index=True)
    
    # Invoice details (mapped to eTims format)
    trader_invoice_no = db.Column(db.String(50), unique=True, nullable=False)
    total_amount = db.Column(db.Float, nullable=False)
    payment_type = db.Column(db.String(10), default='01')  # 01=Cash, 02=Card, 03=Mobile
    sales_type_code = db.Column(db.String(10), default='N')  # N=Normal
    receipt_type_code = db.Column(db.String(10), default='S')  # S=Sales
    sales_status_code = db.Column(db.String(10), default='01')  # 01=Final
    sales_date = db.Column(db.String(20), nullable=False)  # Format: YYYYMMDDHHMMSS
    currency = db.Column(db.String(10), default='KES')
    exchange_rate = db.Column(db.Float, default=1.0)
    
    # Customer details
    customer_pin = db.Column(db.String(50), nullable=True)  # Optional for B2C
    customer_name = db.Column(db.String(200))
    customer_phone = db.Column(db.String(20))
    
    # eTims response (after publishing)
    etims_receipt_code = db.Column(db.String(50), nullable=True)
    etims_invoice_no = db.Column(db.String(50), nullable=True)
    etims_response = db.Column(db.Text, nullable=True)  # Full JSON response
    
    # Sync status
    sync_status = db.Column(
        db.String(20), 
        default=ETimsSaleStatus.PENDING,
        index=True
    )
    sync_attempts = db.Column(db.Integer, default=0)
    last_sync_attempt = db.Column(db.DateTime, nullable=True)
    sync_error = db.Column(db.Text, nullable=True)
    published_at = db.Column(db.DateTime, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship with items
    items = db.relationship('ETimsSaleItem', backref='etims_sale', lazy='dynamic', cascade='all, delete-orphan')
    
    def to_etims_payload(self):
        """Convert to eTims API payload"""
        return {
            "traderInvoiceNo": self.trader_invoice_no,
            "totalAmount": self.total_amount,
            "paymentType": self.payment_type,
            "salesTypeCode": self.sales_type_code,
            "receiptTypeCode": self.receipt_type_code,
            "salesStatusCode": self.sales_status_code,
            "salesDate": self.sales_date,
            "currency": self.currency,
            "exchangeRate": self.exchange_rate,
            "customerPin": self.customer_pin or "",
            "salesItems": [
                item.to_etims_payload() for item in self.items
            ]
        }
    
    def __repr__(self):
        return f'<ETimsSale {self.trader_invoice_no} - {self.sync_status}>'


class ETimsSaleItem(db.Model):
    """eTims Sale Items - line items for eTims sales"""
    __tablename__ = 'etims_sale_items'
    
    id = db.Column(db.Integer, primary_key=True)
    etims_sale_id = db.Column(db.Integer, db.ForeignKey('etims_sales.id'), nullable=False)
    
    # Item details (must use eTims item codes)
    item_code = db.Column(db.String(50), nullable=False)  # eTims item code
    item_name = db.Column(db.String(200))
    qty = db.Column(db.Float, nullable=False)
    pkg = db.Column(db.Float, default=0)
    unit_price = db.Column(db.Float, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    discount_amount = db.Column(db.Float, default=0)
    
    # Tax details
    tax_amount = db.Column(db.Float, default=0)
    taxable_amount = db.Column(db.Float, default=0)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_etims_payload(self):
        """Convert to eTims API payload"""
        return {
            "itemCode": self.item_code,
            "qty": self.qty,
            "pkg": self.pkg or 0,
            "unitPrice": self.unit_price,
            "amount": self.amount,
            "discountAmount": self.discount_amount or 0
        }