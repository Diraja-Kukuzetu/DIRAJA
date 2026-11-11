import logging

from datetime import timedelta
from sqlalchemy import text

from app import db
from Server.Models.WhatsAppChat import (
    WhatsAppChatSession,
    now_eat,
)
from Server.Views.WhatsAppDira import send_wapenda_message


logger = logging.getLogger(__name__)

TIMEOUT_MINUTES = 5


def run_whatsapp_timeout_sweep():
    """
    Expire inactive sessions and send one timeout message per session.

    MySQL GET_LOCK ensures only one worker runs this sweep at a time.
    """

    lock_name = "diraja_whatsapp_timeout_sweep"

    try:
        lock_result = db.session.execute(
            text("SELECT GET_LOCK(:name, 0)"),
            {"name": lock_name}
        ).scalar()

        if lock_result != 1:
            return

        now = now_eat()
        cutoff = now - timedelta(minutes=TIMEOUT_MINUTES)

        sessions = WhatsAppChatSession.query.filter(
            WhatsAppChatSession.status == "active",
            WhatsAppChatSession.last_activity_at <= cutoff
        ).all()

        for session in sessions:
            try:
                session.status = "expired"
                session.ended_at = now
                session.conversation_history = []

                # Commit expiry before sending so another sweep cannot
                # pick the same active session again.
                phone = session.phone
                session_id = session.id
                db.session.commit()

                send_wapenda_message(
                    phone,
                    "Your Dira session expired because of 5 minutes "
                    "of inactivity.\n\n"
                    "Send *Hello Dira* to start a new conversation."
                )

                logger.info(
                    "Dira WhatsApp session %s expired and notified",
                    session_id
                )

            except Exception:
                db.session.rollback()
                logger.exception(
                    "Failed to expire WhatsApp session %s",
                    session.id
                )

    except Exception:
        db.session.rollback()
        logger.exception("WhatsApp timeout sweep failed")

    finally:
        try:
            db.session.execute(
                text("SELECT RELEASE_LOCK(:name)"),
                {"name": lock_name}
            )
            db.session.commit()
        except Exception:
            db.session.rollback()