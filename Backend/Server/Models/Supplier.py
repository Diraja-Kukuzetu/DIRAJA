from flask_sqlalchemy import SQLAlchemy
from app import db
import datetime


class Suppliers(db.Model):
    __tablename__ = "suppliers"

    supplier_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    supplier_name = db.Column(db.String(255), nullable=False)
    supplier_location = db.Column(db.String(255), nullable=False)
    total_amount_received = db.Column(db.Float, default=0.0)
    credit_amount = db.Column(db.Float, default=0.0)  # New field for supplier credit

    # Optional contact details
    email = db.Column(db.String(255), nullable=True)
    phone_number = db.Column(db.String(50), nullable=False)

    # New column: list of items the supplier sells
    items_sold = db.Column(db.JSON, nullable=True, default=list)

    # Relationship to supplier history
    histories = db.relationship('SupplierHistory', backref='supplier', lazy=True)

    def __repr__(self):
        return (f"Supplier(supplier_id={self.supplier_id}, name='{self.supplier_name}', "
                f"location='{self.supplier_location}', total_amount_received={self.total_amount_received}, "
                f"credit_amount={self.credit_amount}, "  # Added to repr
                f"email='{self.email}', phone_number='{self.phone_number}', "
                f"items_sold={self.items_sold})")


class SupplierHistory(db.Model):
    __tablename__ = "supplier_history"
    
    history_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.supplier_id'), nullable=False)
    amount_received = db.Column(db.Float, nullable=False)
    transaction_date = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    item_bought = db.Column(db.String(255), nullable=False)
    payment_status = db.Column(db.String(20), default="paid")
    credit_amount = db.Column(db.Float, default=0.0)
    inventory_id = db.Column(db.Integer, db.ForeignKey('inventoryV2.inventoryV2_id'), nullable=True)
    
    def __repr__(self):
        return (f"SupplierHistory(history_id={self.history_id}, supplier_id={self.supplier_id}, "
                f"amount_received={self.amount_received}, payment_status='{self.payment_status}')")