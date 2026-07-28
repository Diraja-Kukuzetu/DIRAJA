from app import db
from datetime import datetime


class ShopReport(db.Model):
    __tablename__ = "clerk_reports"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.users_id", ondelete="SET NULL"),
        nullable=True
    )

    username = db.Column(db.String(100), nullable=False)

    shop_id = db.Column(
        db.Integer,
        db.ForeignKey("shops.shops_id", ondelete="CASCADE"),
        nullable=False
    )

    reported_at = db.Column(
        db.DateTime,
        server_default=db.func.now(),
        nullable=False
    )

    location = db.Column(db.String(255))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)

    note = db.Column(db.Text)
    
    timestamp = db.Column(
        db.DateTime,
        server_default=db.func.now(),
        nullable=False
    )
