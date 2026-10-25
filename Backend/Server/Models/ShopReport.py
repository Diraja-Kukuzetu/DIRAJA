from app import db
from datetime import datetime, timedelta


def now_eat():
    """Current time in East Africa Time (UTC+3), naive."""
    return datetime.utcnow() + timedelta(hours=3)


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

    # Stored in EAT, set by the app (not the DB clock)
    reported_at = db.Column(db.DateTime, default=now_eat, nullable=False)

    # NULL until the shop is closed. No default.
    closed_at = db.Column(db.DateTime, nullable=True)

    # ── Opening location ─────────────────────────────────────────
    location = db.Column(db.String(255))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)

    # ── Closing location ─────────────────────────────────────────
    closing_location = db.Column(db.String(255))
    closing_latitude = db.Column(db.Float)
    closing_longitude = db.Column(db.Float)

    # ── Closing image ────────────────────────────────────────────
    closing_image_url = db.Column(db.String(500))

    note = db.Column(db.Text)