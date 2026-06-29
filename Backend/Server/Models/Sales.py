from flask_sqlalchemy import SQLAlchemy
from app import db
from sqlalchemy.orm import validates


class Sales(db.Model):
    __tablename__ = "sales"

    sales_id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.users_id'),
        nullable=False
    )

    shop_id = db.Column(
        db.Integer,
        db.ForeignKey('shops.shops_id'),
        nullable=False
    )

    customer_name = db.Column(db.String(50), nullable=True)
    customer_number = db.Column(db.String(15), nullable=True)

    status = db.Column(
        db.String(50),
        default="unpaid",
        nullable=False
    )

    created_at = db.Column(db.DateTime, nullable=False)

    balance = db.Column(db.Float)
    note = db.Column(db.String(50))
    promocode = db.Column(db.String(70), nullable=True)

    delivery = db.Column(
        db.Boolean,
        default=True,
        nullable=False
    )

    timestamp = db.Column(
        db.DateTime,
        server_default=db.func.now(),
        nullable=False
    )

    # ===============================
    # RELATIONSHIPS
    # ===============================

    users = db.relationship(
        'Users',
        backref='sales',
        lazy=True
    )

    shops = db.relationship(
        'Shops',
        backref='sales_for_shop',
        lazy=True
    )

    items = db.relationship(
        'SoldItem',
        backref='sale',
        lazy=True,
        cascade="all, delete-orphan"
    )

    payment = db.relationship(
        'SalesPaymentMethods',
        backref='related_sale',
        lazy=True,
        cascade="all, delete-orphan"
    )

    # ✅ VERY IMPORTANT: CASCADE LEDGER
    ledger_entries = db.relationship(
        "SalesLedger",
        backref="sale",
        cascade="all, delete-orphan",
        passive_deletes=True
    )

    # ===============================
    # VALIDATIONS
    # ===============================

    @validates('status')
    def validate_status(self, key, status):
        valid_status = ['paid', 'unpaid', 'partially_paid' , 'pending']
        if status is not None:
            assert status in valid_status, (
                f"Invalid status. Must be one of: {', '.join(valid_status)}"
            )
        return status

    @validates('customer_number')
    def validate_customer_number(self, key, customer_number):
        if customer_number == '':
            return None
        return customer_number

    def __repr__(self):
        return (
            f"<Sale id={self.sales_id} "
            f"user_id={self.user_id} "
            f"shop_id={self.shop_id} "
            f"status={self.status}>"
        )
