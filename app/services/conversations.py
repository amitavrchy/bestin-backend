from fastapi import HTTPException
from sqlalchemy import select
from app.models import Conversation


def owned_conversation(db, conversation_id, user_id):
    conversation = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id))
    if not conversation:
        raise HTTPException(404, 'conversation_not_found')
    return conversation
