
import os
import re
import uuid
import logging
import requests

from datetime import datetime, timedelta

from flask import request
from flask_restful import Resource

from app import db

from Server.Models.Users import Users
from Server.Models.WhatsAppChat import WhatsAppWebhookEvent

from Server.Models.DirajaAIConversation import (
    DirajaAIConversation,
    DirajaAIMessage
)

from Server.AI.whatsapp_dira_service import ask_dira_question


logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 20

SESSION_TIMEOUT_MINUTES = int(
    os.getenv("DIRA_SESSION_TIMEOUT_MINUTES", "5")
)

WELCOME_MESSAGE = (
    "Hello! Welcome to Dira AI.\n\n"
    "I'm your business assistant. You can ask me questions about "
    "your sales, expenses, products, shops, employees and business "
    "performance.\n\n"
    "You can ask follow-up questions naturally, and I'll use our "
    "conversation history to understand the context.\n\n"
    "When you're finished, send *end chat* to close this session."
)

SESSION_ENDED_MESSAGE = (
    "Your Dira AI session has been closed successfully.\n\n"
    "Your conversation has been saved. "
    "Send *Hello Dira* whenever you want to start a new conversation."
)

SESSION_NOT_STARTED_MESSAGE = (
    "Hello! I'm Dira AI.\n\n"
    "To start a conversation, send *Hello Dira*."
)

SESSION_EXPIRED_MESSAGE = (
    "Your previous Dira AI session has expired due to inactivity.\n\n"
    "Your conversation has been saved. "
    "Send *Hello Dira* to start a new session."
)


# ---------------------------------------------------------
# TIME HELPERS
# ---------------------------------------------------------

def now_eat():
    """
    Use naive East African Time (UTC+3), consistent with
    the existing Diraja models.
    """
    return datetime.utcnow() + timedelta(hours=3)


# ---------------------------------------------------------
# MESSAGE NORMALIZATION
# ---------------------------------------------------------

def normalize_command(message):
    """
    Normalize command text so these are recognized equally:

    Hello Dira
    hello dira
    HELLO DIRA!
    end chat
    End Chat.
    """

    message = str(message or "").strip().lower()

    message = re.sub(r"[^\w\s]", "", message)

    message = re.sub(r"\s+", " ", message)

    return message.strip()


def is_start_command(message):
    return normalize_command(message) == "hello dira"


def is_end_command(message):
    return normalize_command(message) == "end chat"


# ---------------------------------------------------------
# PHONE NUMBER HELPERS
# ---------------------------------------------------------

def normalize_phone(phone):
    """
    Normalize Kenyan numbers to 2547XXXXXXXX / 2541XXXXXXXX.
    """

    phone = re.sub(r"\D", "", str(phone or ""))

    if phone.startswith("0"):
        phone = "254" + phone[1:]

    if phone.startswith("7") or phone.startswith("1"):
        phone = "254" + phone

    return phone


def _phone_variants(phone):

    if not phone:
        return []

    variants = {phone, f"+{phone}"}

    if phone.startswith("254"):
        variants.add("0" + phone[3:])

    return list(variants)


# ---------------------------------------------------------
# WAPENDA MESSAGE HELPERS
# ---------------------------------------------------------

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
        logger.exception(
            "Failed to send WApenda message to %s",
            phone
        )

        return None


# ---------------------------------------------------------
# MANAGER LOOKUP
# ---------------------------------------------------------

def get_manager_by_phone(phone):

    variants = _phone_variants(phone)

    if not variants:
        return None

    return Users.query.filter(
        Users.phone_number.in_(variants),
        Users.role == "manager",
        Users.status == "active",
    ).first()


# ---------------------------------------------------------
# OPTIONAL SHOP METADATA
# ---------------------------------------------------------

def get_optional_shop_id(data):

    shop_id = data.get("shop_id")

    if shop_id in (None, ""):
        return None

    try:
        return int(shop_id)

    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------
# CONVERSATION MANAGEMENT
# ---------------------------------------------------------

def get_active_conversation(user):

    """
    Find the manager's active WhatsApp conversation.

    IMPORTANT:
    Ownership is based only on user_id.
    shop_id is never used to filter conversations.
    """

    return (
        DirajaAIConversation.query
        .filter_by(
            user_id=user.users_id,
            channel="whatsapp",
            status="active"
        )
        .order_by(
            DirajaAIConversation.updated_at.desc()
        )
        .first()
    )


def create_conversation(user, shop_id=None):

    conversation = DirajaAIConversation(
        user_id=user.users_id,
        shop_id=shop_id,
        title="WhatsApp Dira Conversation",
        channel="whatsapp",
        status="active",
        last_message_at=now_eat()
    )

    db.session.add(conversation)

    db.session.flush()

    return conversation


def archive_conversation(conversation):

    conversation.status = "archived"
    conversation.last_message_at = now_eat()

    db.session.commit()


def is_session_expired(conversation):

    if not conversation.last_message_at:
        return False

    elapsed = now_eat() - conversation.last_message_at

    return elapsed > timedelta(
        minutes=SESSION_TIMEOUT_MINUTES
    )


# ---------------------------------------------------------
# MESSAGE STORAGE
# ---------------------------------------------------------

def save_message(
    conversation,
    message_type,
    content,
    turn_id=None,
    sql_query=None,
    result_data=None,
    model_name=None,
    execution_status=None,
    execution_time_ms=None,
    error_message=None
):

    message = DirajaAIMessage(
        conversation_id=conversation.conversation_id,
        turn_id=turn_id or str(uuid.uuid4()),
        message_type=message_type,
        content=str(content),
        sql_query=sql_query,
        result_data=result_data,
        model_name=model_name,
        execution_status=execution_status,
        execution_time_ms=execution_time_ms,
        error_message=error_message
    )

    db.session.add(message)

    conversation.last_message_at = now_eat()

    if (
        message_type == "user"
        and conversation.title == "WhatsApp Dira Conversation"
    ):
        conversation.title = str(content)[:250]

    db.session.commit()

    return message


# ---------------------------------------------------------
# CONVERSATION HISTORY
# ---------------------------------------------------------

def get_conversation_history(conversation):

    messages = (
        DirajaAIMessage.query
        .filter_by(
            conversation_id=conversation.conversation_id
        )
        .order_by(
            DirajaAIMessage.created_at.desc(),
            DirajaAIMessage.message_id.desc()
        )
        .limit(MAX_HISTORY_MESSAGES)
        .all()
    )

    messages.reverse()

    history = []

    for message in messages:

        if message.message_type not in ("user", "assistant"):
            continue

        history.append({
            "role": message.message_type,
            "content": message.content
        })

    return history


# ---------------------------------------------------------
# AI RESPONSE NORMALIZATION
# ---------------------------------------------------------

def normalize_ai_answer(answer):

    if answer is None:
        return "I could not generate an answer. Please try again."

    if isinstance(answer, str):
        return answer

    if isinstance(answer, dict):

        return (
            answer.get("answer")
            or answer.get("response")
            or str(answer)
        )

    return str(answer)


# ---------------------------------------------------------
# START SESSION
# ---------------------------------------------------------

def start_dira_session(user, phone, shop_id=None):

    conversation = get_active_conversation(user)

    # If an active session exists, reuse it.
    if conversation:

        if shop_id is not None:
            conversation.shop_id = shop_id

        turn_id = str(uuid.uuid4())

        save_message(
            conversation=conversation,
            message_type="user",
            content="Hello Dira",
            turn_id=turn_id
        )

        save_message(
            conversation=conversation,
            message_type="assistant",
            content=(
                "You're already connected to Dira AI.\n\n"
                "You can continue asking your questions or send "
                "*end chat* to close this conversation."
            ),
            turn_id=turn_id,
            execution_status="completed"
        )

        return conversation, False

    # No active conversation: create a new one.
    conversation = create_conversation(
        user=user,
        shop_id=shop_id
    )

    turn_id = str(uuid.uuid4())

    save_message(
        conversation=conversation,
        message_type="user",
        content="Hello Dira",
        turn_id=turn_id
    )

    save_message(
        conversation=conversation,
        message_type="assistant",
        content=WELCOME_MESSAGE,
        turn_id=turn_id,
        execution_status="completed"
    )

    logger.info(
        "Started Dira session for user_id=%s conversation_id=%s",
        user.users_id,
        conversation.conversation_id
    )

    return conversation, True


# ---------------------------------------------------------
# END SESSION
# ---------------------------------------------------------

def end_dira_session(user, phone):

    conversation = get_active_conversation(user)

    if not conversation:

        send_message_safely(
            phone,
            "You do not have an active Dira AI session.\n\n"
            "Send *Hello Dira* to start a new conversation."
        )

        return None

    turn_id = str(uuid.uuid4())

    # Save the manager's closing command.
    save_message(
        conversation=conversation,
        message_type="user",
        content="end chat",
        turn_id=turn_id
    )

    # Save Dira's closing response.
    save_message(
        conversation=conversation,
        message_type="assistant",
        content=SESSION_ENDED_MESSAGE,
        turn_id=turn_id,
        execution_status="completed"
    )

    # Archive the conversation.
    archive_conversation(conversation)

    logger.info(
        "Ended Dira session for user_id=%s conversation_id=%s",
        user.users_id,
        conversation.conversation_id
    )

    send_message_safely(
        phone,
        SESSION_ENDED_MESSAGE
    )

    return conversation


# ---------------------------------------------------------
# WHATSAPP DIRA WEBHOOK
# ---------------------------------------------------------

class WhatsAppDiraWebhook(Resource):

    def post(self):

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
            message = (
                message.get("body")
                or message.get("text")
            )

        if not sender or not message:

            return {
                "success": False,
                "message": "Missing sender or message"
            }, 400

        phone = normalize_phone(sender)
        message = str(message).strip()

        if not phone or not message:

            return {
                "success": False,
                "message": "Invalid message"
            }, 400

        try:

            # -------------------------------------------------
            # 1. DUPLICATE EVENT PROTECTION
            # -------------------------------------------------

            if event_id:

                existing_event = WhatsAppWebhookEvent.query.filter_by(
                    event_id=str(event_id)
                ).first()

                if existing_event:

                    return {
                        "success": True,
                        "duplicate": True
                    }, 200

                db.session.add(
                    WhatsAppWebhookEvent(
                        event_id=str(event_id)
                    )
                )

                db.session.flush()

            # -------------------------------------------------
            # 2. MANAGER AUTHORIZATION
            # -------------------------------------------------

            user = get_manager_by_phone(phone)

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

            shop_id = get_optional_shop_id(data)

            # -------------------------------------------------
            # 3. START COMMAND
            # -------------------------------------------------

            if is_start_command(message):

                conversation, created = start_dira_session(
                    user=user,
                    phone=phone,
                    shop_id=shop_id
                )

                db.session.commit()

                # Send welcome or already-active response.
                latest_response = (
                    DirajaAIMessage.query
                    .filter_by(
                        conversation_id=conversation.conversation_id,
                        message_type="assistant"
                    )
                    .order_by(
                        DirajaAIMessage.message_id.desc()
                    )
                    .first()
                )

                if latest_response:

                    send_message_safely(
                        phone,
                        latest_response.content
                    )

                return {
                    "success": True,
                    "authorized": True,
                    "session_started": created,
                    "conversation_id": conversation.conversation_id
                }, 200

            # -------------------------------------------------
            # 4. END COMMAND
            # -------------------------------------------------

            if is_end_command(message):

                conversation = end_dira_session(
                    user=user,
                    phone=phone
                )

                return {
                    "success": True,
                    "authorized": True,
                    "session_ended": conversation is not None,
                    "conversation_id": (
                        conversation.conversation_id
                        if conversation else None
                    )
                }, 200

            # -------------------------------------------------
            # 5. REQUIRE AN ACTIVE SESSION
            # -------------------------------------------------

            conversation = get_active_conversation(user)

            if not conversation:

                db.session.commit()

                send_message_safely(
                    phone,
                    SESSION_NOT_STARTED_MESSAGE
                )

                return {
                    "success": True,
                    "authorized": True,
                    "session_active": False,
                    "message": "Send Hello Dira to start."
                }, 200

            # -------------------------------------------------
            # 6. CHECK SESSION INACTIVITY
            # -------------------------------------------------

            if is_session_expired(conversation):

                archive_conversation(conversation)

                send_message_safely(
                    phone,
                    SESSION_EXPIRED_MESSAGE
                )

                return {
                    "success": True,
                    "authorized": True,
                    "session_expired": True,
                    "conversation_id": conversation.conversation_id
                }, 200

            # -------------------------------------------------
            # 7. LOAD CONVERSATION HISTORY
            # -------------------------------------------------

            conversation_history = get_conversation_history(
                conversation
            )

            conversation_id = conversation.conversation_id

            # -------------------------------------------------
            # 8. SAVE MANAGER QUESTION
            # -------------------------------------------------

            turn_id = str(uuid.uuid4())

            save_message(
                conversation=conversation,
                message_type="user",
                content=message,
                turn_id=turn_id
            )

            # -------------------------------------------------
            # 9. MANAGER CONTEXT
            # -------------------------------------------------

            user_context = {
                "user_id": user.users_id,
                "username": user.username,
                "role": user.role,
                "conversation_id": conversation_id,
                "shop_id": shop_id
            }

            # -------------------------------------------------
            # 10. ASK DIRaja AI
            # -------------------------------------------------

            try:

                answer = ask_dira_question(
                    question=message,
                    conversation_history=conversation_history,
                    user_context=user_context
                )

                answer_text = normalize_ai_answer(answer)

                save_message(
                    conversation=conversation,
                    message_type="assistant",
                    content=answer_text,
                    turn_id=turn_id,
                    execution_status="completed"
                )

            except Exception as ai_error:

                logger.exception(
                    "Dira AI failed for conversation_id=%s",
                    conversation_id
                )

                db.session.rollback()

                conversation = db.session.get(
                    DirajaAIConversation,
                    conversation_id
                )

                answer_text = (
                    "I encountered an error while processing your "
                    "question. Please try again."
                )

                if conversation:

                    save_message(
                        conversation=conversation,
                        message_type="assistant",
                        content=answer_text,
                        turn_id=turn_id,
                        execution_status="failed",
                        error_message=str(ai_error)
                    )

            # -------------------------------------------------
            # 11. SEND AI RESPONSE
            # -------------------------------------------------

            send_message_safely(
                phone,
                answer_text
            )

            return {
                "success": True,
                "authorized": True,
                "message_processed": True,
                "conversation_id": conversation_id,
                "turn_id": turn_id
            }, 200

        except Exception:

            db.session.rollback()

            logger.exception(
                "WhatsApp Dira webhook processing failed"
            )

            return {
                "success": False,
                "message": "Webhook processing failed"
            }, 500
