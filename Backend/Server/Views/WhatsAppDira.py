import os
import re
import requests
import logging

from flask import request
from flask_restful import Resource

from app import db
from Server.Models.Users import Users
from Server.Models.WhatsAppChat import WhatsAppWebhookEvent
from Server.AI.whatsapp_dira_service import ask_dira_question


logger = logging.getLogger(__name__)


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


def _phone_variants(phone):
    """
    Return the likely ways a normalized phone may be stored in
    Users.phone_number, so we can match regardless of format:
      - 254712345678
      - +254712345678
      - 0712345678
    """
    if not phone:
        return []

    variants = {phone, f"+{phone}"}

    if phone.startswith("254"):
        variants.add("0" + phone[3:])

    return list(variants)


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


def send_message_safely(phone, message):
    try:
        return send_wapenda_message(phone, message)
    except Exception:
        logger.exception("Failed to send WApenda message to %s", phone)
        return None


def get_manager_by_phone(phone):
    """
    Return the Users record whose phone_number matches the
    given normalized phone, restricted to active managers.
    """
    variants = _phone_variants(phone)

    if not variants:
        return None

    user = Users.query.filter(
        Users.phone_number.in_(variants),
        Users.role == "manager",
        Users.status == "active",
    ).first()

    return user


class WhatsAppDiraWebhook(Resource):

    def post(self):
        # Webhook signature verification is disabled.
        data = request.get_json(silent=True) or {}

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

            user = get_manager_by_phone(phone)

            # ── Unauthorized ──
            if not user:
                db.session.commit()

                send_message_safely(
                    phone,
                    "Your WhatsApp number is not linked to an active "
                    "manager account. Please contact your administrator."
                )

                return {
                    "success": True,
                    "authorized": False
                }, 200

            # ── Authorized ──
            user_context = {
                "user_id": user.users_id,
                "username": user.username,
                "role": user.role,
            }

            answer = ask_dira_question(
                question=message,
                conversation_history=[],
                user_context=user_context,
            )

            db.session.commit()

            send_message_safely(phone, answer)

            return {
                "success": True,
                "authorized": True,
                "message_processed": True
            }, 200

        except Exception:
            db.session.rollback()
            logger.exception("WhatsApp Dira webhook processing failed")
            return {
                "success": False,
                "message": "Webhook processing failed"
            }, 500