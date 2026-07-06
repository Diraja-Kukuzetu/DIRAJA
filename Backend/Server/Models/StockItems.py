from flask_sqlalchemy import SQLAlchemy
from app import db
from sqlalchemy import func
from datetime import datetime

class StockItems(db.Model):
    """Your existing StockItems model - extended for eTims"""
    __tablename__ = "stock_item"

    id = db.Column(db.Integer, primary_key=True)
    item_name = db.Column(db.String(150), nullable=False)
    item_code = db.Column(db.String(150), nullable=True)  # Your internal code
    unit_price = db.Column(db.Float, nullable=True)
    pack_price = db.Column(db.Float, nullable=True)
    pack_quantity = db.Column(db.Integer, nullable=True)

    # ✅ Category column
    category = db.Column(
        db.Enum("eggs", "chicken", "farmers choice", "others", name="stock_category"),
        nullable=True
    )

    # ============ NEW eTims Fields ============
    # eTims specific fields
    etims_item_code = db.Column(db.String(50), nullable=True, unique=True)  # KRA code
    etims_synced = db.Column(db.Boolean, default=False)
    etims_sync_date = db.Column(db.DateTime, nullable=True)
    
    # eTims required fields (with defaults)
    org_country_code = db.Column(db.String(10), default='KE')
    item_type_code = db.Column(db.String(10), default='1')  # 1=Goods, 2=Service
    tax_code = db.Column(db.String(10), default='A')  # A=Standard, B=Zero-rated, C=Exempt
    qty_unit_code = db.Column(db.String(10), default='U')  # U=Unit
    pkg_unit_code = db.Column(db.String(10), default='CT')  # CT=Carton
    item_class_code = db.Column(db.String(20), default='99000000')  # HS Code
    initial_stock = db.Column(db.Float, default=0)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __str__(self):
        return f"{self.item_name} - {self.category or 'Uncategorized'}"

    def to_etims_payload(self):
        """Convert StockItems model to eTims API payload"""
        return {
            "name": self.item_name,
            "orgCountryCode": self.org_country_code or "KE",
            "unitPrice": float(self.unit_price or 0),
            "itemTypeCode": self.item_type_code or "1",
            "taxCode": self.tax_code or "A",
            "qtyUnitCode": self.qty_unit_code or "U",
            "pkgUnitCode": self.pkg_unit_code or "CT",
            "itemClassCode": self.item_class_code or "99000000",
            "initialStock": self.initial_stock or 0
        }


class EtimsItem(db.Model):
    """eTims Item model - stores items synced from eTims"""
    __tablename__ = 'etims_items'
    
    id = db.Column(db.Integer, primary_key=True)
    item_code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    org_country_code = db.Column(db.String(10))
    unit_price = db.Column(db.Float)
    item_type_code = db.Column(db.String(10))
    tax_code = db.Column(db.String(10))
    qty_unit_code = db.Column(db.String(10))
    pkg_unit_code = db.Column(db.String(10))
    item_class_code = db.Column(db.String(20))
    stock = db.Column(db.Float, default=0)
    
    # Reference to local stock item
    local_item_id = db.Column(db.Integer, db.ForeignKey('stock_item.id'), nullable=True)
    local_item = db.relationship('StockItems', backref='etims_record')
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<EtimsItem {self.item_code}: {self.name}>'