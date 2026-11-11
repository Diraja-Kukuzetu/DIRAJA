from datetime import datetime, timedelta

from app import db


def now_eat():
    # Your existing Diraja convention: naive East Africa Time (UTC+3)
    return datetime.utcnow() + timedelta(hours=3)


class WhatsAppUserLink(db.Model):
    __tablename__ = "whatsapp_user_links"

    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(25), unique=True, nullable=False, index=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.users_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=now_eat, nullable=False)


class WhatsAppChatSession(db.Model):
    __tablename__ = "whatsapp_chat_sessions"

    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(25), nullable=False, index=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.users_id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    status = db.Column(
        db.String(20),
        nullable=False,
        default="active",
        index=True
    )
    conversation_history = db.Column(db.JSON, nullable=False, default=list)

    started_at = db.Column(db.DateTime, default=now_eat, nullable=False)
    last_activity_at = db.Column(db.DateTime, default=now_eat, nullable=False)
    ended_at = db.Column(db.DateTime, nullable=True)
    timeout_notified_at = db.Column(db.DateTime, nullable=True)


class WhatsAppWebhookEvent(db.Model):
    __tablename__ = "whatsapp_webhook_events"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.String(150), unique=True, nullable=False)
    received_at = db.Column(db.DateTime, default=now_eat, nullable=False)