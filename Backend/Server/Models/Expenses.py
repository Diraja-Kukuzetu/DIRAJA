from flask_sqlalchemy import SQLAlchemy
from app import db
import datetime

class Expenses(db.Model):
    __tablename__ = "expenses"

    # Table columns
    expense_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.users_id'))
    shop_id = db.Column(db.Integer, db.ForeignKey('shops.shops_id'))
    creditor_id = db.Column(db.Integer, db.ForeignKey('expense_creditors.creditor_id'), nullable=True)  # ✅ FIXED
    item = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(50), nullable=False) 
    category = db.Column(db.String(50), nullable=False) 
    quantity = db.Column(db.Float, nullable=True)
    paidTo = db.Column(db.String(50), nullable=True)
    totalPrice = db.Column(db.Float, nullable=False)
    amountPaid = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    source = db.Column(db.String(100), nullable=False)
    comments = db.Column(db.String(100), nullable=True)
    paymentRef = db.Column(db.String(100), nullable=False)
    payment_status = db.Column(db.String(10), nullable=False, default='pending')
    
    # Relationships
    users = db.relationship('Users', backref='expenses', lazy=True)
    shops = db.relationship('Shops', backref='expenses', lazy=True)
    creditor = db.relationship('Creditor', backref='expenses', lazy=True)  # ✅ now valid
    credit_payments = db.relationship('CreditPayments', backref='expense', lazy=True, cascade="all, delete-orphan")
    
    @property
    def outstanding_balance(self):
        return self.totalPrice - self.amountPaid
    
    @property
    def is_credit(self):
        return self.outstanding_balance > 0
    
    def update_payment_status(self):
        if self.amountPaid == 0:
            self.payment_status = 'pending'
        elif self.amountPaid >= self.totalPrice:
            self.payment_status = 'paid'
        else:
            self.payment_status = 'partial'
    
    def __repr__(self):
        return (f"Expense (expense_id={self.expense_id}, user_id='{self.user_id}', "
                f"shop_id='{self.shop_id}', category='{self.category}', item='{self.item}', "
                f"description='{self.description}', quantity='{self.quantity}', "
                f"paidTo='{self.paidTo}', totalPrice='{self.totalPrice}', "
                f"amountPaid='{self.amountPaid}', payment_status='{self.payment_status}', "
                f"source='{self.source}', comments='{self.comments}')")


class CreditPayments(db.Model):
    __tablename__ = "credit_payments"
    
    payment_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    expense_id = db.Column(db.Integer, db.ForeignKey('expenses.expense_id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    payment_date = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    payment_ref = db.Column(db.String(100), nullable=False)
    payment_method = db.Column(db.String(50), nullable=True)
    source = db.Column(db.String(100), nullable=False)
    notes = db.Column(db.String(200), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.users_id'), nullable=True)
    
    def __repr__(self):
        return (f"CreditPayment(payment_id={self.payment_id}, expense_id={self.expense_id}, "
                f"amount={self.amount}, payment_ref='{self.payment_ref}', source='{self.source}')")
    

class Creditor(db.Model):
    __tablename__ = "expense_creditors"
    
    creditor_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(100), nullable=True)
    address = db.Column(db.String(200), nullable=True)
    total_amount_owed = db.Column(db.Float, default=0.0)
    total_amount_paid = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    notes = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    
    # Relationships
    user_id = db.Column(db.Integer, db.ForeignKey('users.users_id'), nullable=True)
    user = db.relationship('Users', backref='creditors', lazy=True)
    
    @property
    def outstanding_balance(self):
        return self.total_amount_owed - self.total_amount_paid
    
    @property
    def payment_status(self):
        if self.outstanding_balance <= 0:
            return 'fully_paid'
        elif self.total_amount_paid == 0:
            return 'unpaid'
        else:
            return 'partial'
    
    def update_totals(self):
        from sqlalchemy import func
        
        total_owed = db.session.query(func.sum(Expenses.totalPrice)).filter(
            Expenses.creditor_id == self.creditor_id
        ).scalar() or 0.0
        
        total_paid = db.session.query(func.sum(Expenses.amountPaid)).filter(
            Expenses.creditor_id == self.creditor_id
        ).scalar() or 0.0
        
        self.total_amount_owed = total_owed
        self.total_amount_paid = total_paid
        self.updated_at = datetime.datetime.utcnow()
        db.session.commit()
    
    def __repr__(self):
        return (f"Creditor(creditor_id={self.creditor_id}, name='{self.name}', "
                f"phone='{self.phone_number}', owed={self.total_amount_owed}, "
                f"paid={self.total_amount_paid}, outstanding={self.outstanding_balance})")