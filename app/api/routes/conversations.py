from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import current_user
from app.db.session import get_db
from app.models import Conversation, Message, User, now
from app.schemas import Ask, ConversationCreate, ConversationDetail, ConversationOut, MessageOut
from app.services import ai_client
from app.services.books import visible_book
from app.services.conversations import owned_conversation

router = APIRouter(prefix='/api/conversations', tags=['conversations'])


@router.post('', response_model=ConversationOut)
def create(body: ConversationCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    visible_book(db, body.book_id, user)
    conversation = Conversation(user_id=user.id, book_id=body.book_id)
    db.add(conversation)
    db.commit()
    return conversation


@router.get('', response_model=list[ConversationOut])
def listing(book_id: int | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = select(Conversation).where(Conversation.user_id == user.id)
    if book_id is not None:
        query = query.where(Conversation.book_id == book_id)
    return db.scalars(query.order_by(Conversation.updated_at.desc(), Conversation.id.desc())).all()


@router.get('/{conversation_id}', response_model=ConversationDetail)
def detail(conversation_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return owned_conversation(db, conversation_id, user.id)


@router.delete('/{conversation_id}', status_code=204)
def delete(conversation_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(owned_conversation(db, conversation_id, user.id))
    db.commit()


@router.post('/{conversation_id}/ask')
def ask(conversation_id: int, body: Ask, user: User = Depends(current_user), db: Session = Depends(get_db)):
    conversation = owned_conversation(db, conversation_id, user.id)
    visible_book(db, conversation.book_id, user)
    history = [{'role': m.role, 'content': m.content} for m in conversation.messages[-6:]]
    result = ai_client.request('POST', '/v1/ask', json={'book_id': conversation.book_id, 'question': body.question, 'history': history, 'speak': body.speak, 'voice': body.voice, 'style': body.style})
    question = Message(conversation_id=conversation.id, role='user', content=body.question, citations=[])
    answer = Message(conversation_id=conversation.id, role='assistant', content=result['answer'], citations=result.get('citations', []), provider=result.get('provider'))
    if not conversation.messages:
        conversation.title = body.question[:100]
    conversation.updated_at = now()
    db.add_all([question, answer])
    db.commit()
    return {'user_message': MessageOut.model_validate(question), 'assistant_message': MessageOut.model_validate(answer), 'speech': result.get('speech')}
