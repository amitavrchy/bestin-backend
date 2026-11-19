from sqlalchemy.orm import Session
from app.models import Message, User, now
from app.schemas import Ask, ConversationCreate, MessageOut
from app.services import ai_client
from app.services.books import visible_book
from fastapi import HTTPException
from sqlalchemy import select
from app.models import Conversation


def owned_conversation(db, conversation_id, user_id):
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id
        )
    )
    if not conversation:
        raise HTTPException(404, "conversation_not_found")
    return conversation


def create(body: ConversationCreate, user: User, db: Session):
    visible_book(db, body.book_id, user)
    conversation = Conversation(user_id=user.id, book_id=body.book_id)
    db.add(conversation)
    db.commit()
    return conversation


def listing(book_id: int | None, user: User, db: Session):
    query = select(Conversation).where(Conversation.user_id == user.id)
    if book_id is not None:
        query = query.where(Conversation.book_id == book_id)
    return db.scalars(
        query.order_by(Conversation.updated_at.desc(), Conversation.id.desc())
    ).all()


def detail(conversation_id: int, user: User, db: Session):
    return owned_conversation(db, conversation_id, user.id)


def delete(conversation_id: int, user: User, db: Session):
    db.delete(owned_conversation(db, conversation_id, user.id))
    db.commit()


def ask(conversation_id: int, body: Ask, user: User, db: Session):
    conversation = owned_conversation(db, conversation_id, user.id)
    visible_book(db, conversation.book_id, user)
    history = [
        {"role": m.role, "content": m.content} for m in conversation.messages[-6:]
    ]
    result = ai_client.request(
        "POST",
        "/v1/ask",
        json={
            "book_id": conversation.book_id,
            "question": body.question,
            "history": history,
            "speak": body.speak,
            "voice": body.voice,
            "style": body.style,
        },
    )
    question = Message(
        conversation_id=conversation.id,
        role="user",
        content=body.question,
        citations=[],
    )
    answer = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=result["answer"],
        citations=result.get("citations", []),
        provider=result.get("provider"),
    )
    if not conversation.messages:
        conversation.title = body.question[:100]
    conversation.updated_at = now()
    db.add_all([question, answer])
    db.commit()
    return {
        "user_message": MessageOut.model_validate(question),
        "assistant_message": MessageOut.model_validate(answer),
        "speech": result.get("speech"),
    }
