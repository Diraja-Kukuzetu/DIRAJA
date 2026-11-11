import os
import re
import requests
import logging

from datetime import timedelta

from flask import request, current_app
from flask_restful import Resource

from app import db
from Server.Models.Users import Users
from Server.Models.WhatsAppChat import (
    WhatsAppUserLink,
    WhatsAppChatSession,
    WhatsAppWebhookEvent,
    now_eat,
)
from Server.AI.whatsapp_dira_service import ask_dira_question


logger = logging.getLogger(__name__)

SESSION_TIMEOUT_MINUTES = 5

ACTIVATION_PHRASES = {
    "hello dira",
    "hi dira",
}

END_PHRASES = {
    "end chat",
    "end conversation",
    "stop chat",
}


def normalize_phone(phone):
    """
    Normalize Kenyan numbers to 2547XXXXXXXX / 2541XXXXXXXX.
    Extend this function if you support other countries.
    """
    phone = re.sub(r"\D", "", str(phone or ""))

    if phone.startswith("0"):
        phone = "254" + phone[1:]

    if phone.startswith("7") or phone.startswith("1"):
        phone = "254" + phone

    return phone


def send_wapenda_message(phone, message):
    base_url = os.getenv(
        "WAPENDA_BASE_URL",
        "https://tekservix.com/wapenda/api"
    ).rstrip("/")

    api_key = os.getenv("WAPENDA_API_KEY")

    if not api_key:
        raise RuntimeError("WAPENDA_API_KEY is not configured")

    response = requests.post(
        f"{base_url}/send-message",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "to": phone,
            "text": message,
        },
        timeout=20,
    )

    response.raise_for_status()
    return response.json() if response.content else {}


def get_linked_user(phone):
    link = WhatsAppUserLink.query.filter_by(
        phone=phone,
        is_active=True
    ).first()

    if not link:
        return None

    user = Users.query.filter_by(
        users_id=link.user_id
    ).first()

    if not user or user.status != "active":
        return None

    return user


def get_active_session(phone):
    return WhatsAppChatSession.query.filter_by(
        phone=phone,
        status="active"
    ).order_by(
        WhatsAppChatSession.started_at.desc()
    ).first()


def send_message_safely(phone, message):
    try:
        return send_wapenda_message(phone, message)
    except Exception:
        logger.exception("Failed to send WApenda message to %s", phone)
        return None


class WhatsAppDiraWebhook(Resource):

    def post(self):
        # Webhook signature verification is disabled.
        # Incoming requests are processed without validating a provider signature.
        data = request.get_json(silent=True) or {}

        # Adapt these fields to the exact WApenda webhook event format.
        # Do not assume the provider sends all these fields.
        event_id = (
            data.get("id")
            or data.get("event_id")
            or data.get("message_id")
        )

        sender = (
            data.get("from")
            or data.get("sender")
            or data.get("phone")
        )

        message = (
            data.get("text")
            or data.get("message")
            or data.get("body")
        )

        if isinstance(message, dict):
            message = message.get("body") or message.get("text")

        if not sender or not message:
            return {
                "success": False,
                "message": "Missing sender or message"
            }, 400

        phone = normalize_phone(sender)
        message = str(message).strip()
        command = message.lower()

        if not phone or not message:
            return {"success": False, "message": "Invalid message"}, 400

        try:
            # Prevent WApenda webhook retries from processing the same event.
            if event_id:
                existing_event = WhatsAppWebhookEvent.query.filter_by(
                    event_id=str(event_id)
                ).first()

                if existing_event:
                    return {"success": True, "duplicate": True}, 200

                db.session.add(
                    WhatsAppWebhookEvent(event_id=str(event_id))
                )
                db.session.flush()

            user = get_linked_user(phone)

            if command in ACTIVATION_PHRASES:
                if not user:
                    db.session.commit()
                    send_message_safely(
                        phone,
                        "Your WhatsApp number is not linked to an active "
                        "Diraja account. Please contact your administrator."
                    )
                    return {"success": True}, 200

                if user.role not in ("admin", "super_admin"):
                    db.session.commit()
                    send_message_safely(
                        phone,
                        "Your account is not yet authorized to use Dira AI "
                        "through WhatsApp. Please contact your administrator."
                    )
                    return {"success": True}, 200

                # Close any previous active session.
                old_session = get_active_session(phone)

                if old_session:
                    old_session.status = "ended"
                    old_session.ended_at = now_eat()

                session = WhatsAppChatSession(
                    phone=phone,
                    user_id=user.users_id,
                    status="active",
                    conversation_history=[],
                    started_at=now_eat(),
                    last_activity_at=now_eat(),
                )

                db.session.add(session)
                db.session.commit()

                send_message_safely(
                    phone,
                    "Hello! 👋 I'm Dira, your Diraja AI assistant.\n\n"
                    "You can ask me about your business reports, sales, "
                    "inventory and other available business data.\n\n"
                    "Your chat will automatically end after 5 minutes "
                    "of inactivity.\n\n"
                    "Send *End chat* whenever you want to close the session."
                )

                return {"success": True, "session_started": True}, 200

            session = get_active_session(phone)

            if command in END_PHRASES:
                if session:
                    session.status = "ended"
                    session.ended_at = now_eat()
                    session.conversation_history = []

                db.session.commit()

                send_message_safely(
                    phone,
                    "Your Dira chat has ended. 👋\n"
                    "Send *Hello Dira* whenever you want to start again."
                )

                return {"success": True, "session_ended": True}, 200

            if not session:
                db.session.commit()

                send_message_safely(
                    phone,
                    "Your Dira session is not active.\n\n"
                    "Send *Hello Dira* to start a new conversation."
                )

                return {"success": True, "session_inactive": True}, 200

            now = now_eat()

            if now - session.last_activity_at > timedelta(
                minutes=SESSION_TIMEOUT_MINUTES
            ):
                session.status = "expired"
                session.ended_at = now
                session.conversation_history = []
                db.session.commit()

                send_message_safely(
                    phone,
                    "Your Dira session expired because of 5 minutes "
                    "of inactivity.\n\nSend *Hello Dira* to start again."
                )

                return {"success": True, "session_expired": True}, 200

            # Revalidate the linked user on every message.
            user = get_linked_user(phone)

            if not user or user.users_id != session.user_id:
                session.status = "ended"
                session.ended_at = now
                db.session.commit()

                send_message_safely(
                    phone,
                    "Your Diraja account is no longer authorized. "
                    "Please contact your administrator."
                )

                return {"success": True}, 200

            if user.role not in ("admin", "super_admin"):
                session.status = "ended"
                session.ended_at = now
                db.session.commit()

                send_message_safely(
                    phone,
                    "Your account is not authorized to use Dira AI."
                )

                return {"success": True}, 200

            session.last_activity_at = now

            history = session.conversation_history or []

            user_context = {
                "user_id": user.users_id,
                "username": user.username,
                "role": user.role,
            }

            # Save the user's message before asking the AI.
            history.append({
                "role": "user",
                "content": message
            })

            answer = ask_dira_question(
                question=message,
                conversation_history=history[:-1],
                user_context=user_context,
            )

            history.append({
                "role": "assistant",
                "content": answer
            })

            # Retain only the most recent messages.
            session.conversation_history = history[-12:]

            db.session.commit()

            send_message_safely(phone, answer)

            return {"success": True, "message_processed": True}, 200

        except Exception:
            db.session.rollback()
            logger.exception("WhatsApp Dira webhook processing failed")
            return {"success": False, "message": "Webhook processing failed"}, 500