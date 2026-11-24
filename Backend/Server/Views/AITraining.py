from flask import request
from flask_restful import Resource

from app import db
from Server.Models.DirajaAIConversation import (  # adjust import path as needed
    DirajaAIConversation,
    DirajaAIMessage,
)


class DirajaAIMessagesResource(Resource):
    """
    GET /diraja-ai/messages

    Returns ALL messages across ALL conversations, newest first.
    Optional filters via query string:
        ?conversation_id=42
        ?user_id=7
        ?message_type=user|assistant
        ?page=1&per_page=100
    """

    def get(self):
        page = request.args.get("page", 1, type=int)
        per_page = min(request.args.get("per_page", 100, type=int), 500)

        query = DirajaAIMessage.query

        # Optional filters (all ignored if not supplied)
        conversation_id = request.args.get("conversation_id", type=int)
        if conversation_id is not None:
            query = query.filter(DirajaAIMessage.conversation_id == conversation_id)

        message_type = request.args.get("message_type")
        if message_type:
            query = query.filter(DirajaAIMessage.message_type == message_type)

        # Optional: filter by conversation owner
        user_id = request.args.get("user_id", type=int)
        if user_id is not None:
            query = query.join(
                DirajaAIMessage.conversation
            ).filter(
                DirajaAIMessage.conversation.has(user_id=user_id)
            )

        query = query.order_by(
            DirajaAIMessage.created_at.desc(),
            DirajaAIMessage.message_id.desc(),
        )

        messages = query.paginate(page=page, per_page=per_page, error_out=False)

        return {
            "messages": [m.to_dict() for m in messages.items],
            "pagination": {
                "page": messages.page,
                "per_page": messages.per_page,
                "total": messages.total,
                "pages": messages.pages,
                "has_next": messages.has_next,
                "has_prev": messages.has_prev,
            },
        }, 200