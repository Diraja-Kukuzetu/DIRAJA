from flask_sqlalchemy import SQLAlchemy
from app import db
import datetime

class CashDeposits(db.Model):
    __tablename__ = "cash_deposits"

    deposit_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.users_id'), nullable=False)
    shop_id = db.Column(db.Integer, db.ForeignKey('shops.shops_id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    deductions = db.Column(db.Float, nullable=True)
    reason = db.Column(db.String(255), nullable=True)
    transaction_code = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)

    # Relationships
    users = db.relationship('Users', backref='cash_deposits', lazy=True)
    shops  = db.relationship('Shops', backref='cash_deposits', lazy=True)

    def __repr__(self):
        return (f"CashDeposit(deposit_id={self.deposit_id}, user_id={self.user_id}, "
                f"shop_id={self.shop_id}, amount={self.amount}, deductions={self.deductions}, "
                f"reason='{self.reason}', transaction_code='{self.transaction_code}', created_at='{self.created_at}')")
