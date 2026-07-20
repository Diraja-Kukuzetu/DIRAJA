from flask_sqlalchemy import SQLAlchemy
from app import db
from sqlalchemy.orm import validates
import datetime

class ServiceSales(db.Model):
    """Model for service sales (no stock deduction)"""
    __tablename__ = 'service_sales'
    
    sales_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.users_id'))
    shop_id = db.Column(db.Integer, db.ForeignKey('shops.shops_id'))
    customer_name = db.Column(db.String(255))
    customer_number = db.Column(db.String(50))
    status = db.Column(db.String(50))  # paid, unpaid, partially_paid
    service_type = db.Column(db.String(100))  # consultation, repair, labor, etc.
    service_notes = db.Column(db.Text)
    total_price = db.Column(db.Float, default=0.0)
    total_services = db.Column(db.Integer, default=0)
    total_quantity = db.Column(db.Float, default=0.0)
    balance = db.Column(db.Float, default=0.0)
    promocode = db.Column(db.String(100))
    delivery = db.Column(db.Boolean, default=False)
    completed = db.Column(db.Boolean, default=False)
    completed_at = db.Column(db.DateTime)
    payment_status = db.Column(db.String(50))  # track payment status separately
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    services = db.relationship('ServiceItem', backref='sale', lazy=True)
    payments = db.relationship('ServicePaymentMethod', backref='sale', lazy=True)


class ServiceItem(db.Model):
    """Individual service items in a service sale"""
    __tablename__ = 'service_items'
    
    id = db.Column(db.Integer, primary_key=True)
    service_sale_id = db.Column(db.Integer, db.ForeignKey('service_sales.sales_id'))
    service_name = db.Column(db.String(255))
    quantity = db.Column(db.Float, default=1.0)
    unit_price = db.Column(db.Float)
    total_price = db.Column(db.Float)
    duration = db.Column(db.String(100))  # e.g., "2 hours", "30 minutes"
    service_notes = db.Column(db.Text)
    service_date = db.Column(db.DateTime)
    assigned_to = db.Column(db.String(255))  # staff member assigned
    service_type = db.Column(db.String(100))
    completed = db.Column(db.Boolean, default=False)
    completed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ServicePaymentMethod(db.Model):
    """Payment methods for service sales"""
    __tablename__ = 'service_payment_methods'
    
    id = db.Column(db.Integer, primary_key=True)
    service_sale_id = db.Column(db.Integer, db.ForeignKey('service_sales.sales_id'))
    payment_method = db.Column(db.String(50))  # cash, sasapay, mpesa, etc.
    amount_paid = db.Column(db.Float)
    transaction_code = db.Column(db.String(100))
    discount = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)