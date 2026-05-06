from flask_sqlalchemy import SQLAlchemy
from app import db
from sqlalchemy import func

class ExpenseCategory(db.Model):
    __tablename__ = "expense_category"

    id = db.Column(db.Integer, primary_key=True)
    category_name = db.Column(db.String(150), nullable=False)
    type = db.Column(db.String(150), nullable=True)
    
    # Relationship to items
    items = db.relationship('ExpenseItem', backref='category', lazy=True, cascade="all, delete-orphan")

    def __str__(self):
        return f"{self.type} - {self.category_name}"


class ExpenseItem(db.Model):
    __tablename__ = "expense_items"
    
    id = db.Column(db.Integer, primary_key=True)
    item_name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey('expense_category.id'), nullable=False)
    created_at = db.Column(db.DateTime, server_default=func.now(), nullable=False)
    
    def __str__(self):
        return self.item_name