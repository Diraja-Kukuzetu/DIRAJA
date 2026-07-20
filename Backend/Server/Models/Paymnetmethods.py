from flask_sqlalchemy import SQLAlchemy
from app import db
from sqlalchemy.orm import validates
from datetime import datetime

class SalesPaymentMethods(db.Model):
    __tablename__ = "sales_payment_methods"
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.sales_id'), nullable=False)
    payment_method = db.Column(db.String(50), nullable=False)
    amount_paid = db.Column(db.Float, nullable=False)
    discount = db.Column(db.Float, nullable=False, default=0.0)
    balance = db.Column(db.Float, nullable=True)
    transaction_code = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # SasaPay specific fields
    checkout_request_id = db.Column(db.String(100), nullable=True)
    merchant_code = db.Column(db.String(20), nullable=True)
    sasapay_transaction_id = db.Column(db.String(100), nullable=True)
    payment_status = db.Column(db.String(20), nullable=True, default='pending')  # pending, success, failed
    result_code = db.Column(db.String(10), nullable=True)
    result_desc = db.Column(db.String(500), nullable=True)
    failure_reason = db.Column(db.String(500), nullable=True)
    callback_received_at = db.Column(db.DateTime, nullable=True)
    callback_data = db.Column(db.Text, nullable=True)  # Store full callback JSON
    

    # Validation for payment method
    @validates('payment_method')
    def validate_payment_method(self, key, payment_method):
        valid_methods = ['bank', 'cash', 'mpesa', 'sasapay', 'sasapay deliveries', 'not payed']
        assert payment_method in valid_methods, f"Invalid payment method. Must be one of: {', '.join(valid_methods)}"
        return payment_method
    
    # Validation for payment status
    @validates('payment_status')
    def validate_payment_status(self, key, payment_status):
        if payment_status:
            valid_statuses = ['pending', 'success', 'failed']
            assert payment_status in valid_statuses, f"Invalid payment status. Must be one of: {', '.join(valid_statuses)}"
        return payment_status

    def __repr__(self):
        return (
            f"SalesPaymentMethods(id={self.id}, sale_id={self.sale_id}, "
            f"payment_method='{self.payment_method}', amount_paid={self.amount_paid}, "
            f"balance={self.balance}, transaction_code='{self.transaction_code}', "
            f"payment_status='{self.payment_status}', checkout_request_id='{self.checkout_request_id}', "
            f"created_at='{self.created_at}')"
        )