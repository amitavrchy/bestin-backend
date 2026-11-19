from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.api.deps import require_admin
from app.db.session import get_db
from app.models import Book, Conversation, Message, User
from app.schemas import AdminUserPatch, BookOut, BookPatch, UserOut
from app.services import ai_client, storage

router = APIRouter(
    prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)]
)


def find_book(db, book_id):
    book = db.get(Book, book_id)
    if not book:
        raise HTTPException(404, "book_not_found")
    return book


def start_ingest(db, book):
    try:
        ai_client.ingest(book)
    except HTTPException as exc:
        book.status = "failed"
        book.error = str(exc.detail)
        db.commit()
        raise
    book.status = "queued"
    book.progress = 0
    book.chunks = 0
    book.pages = None
    book.error = None
    db.commit()
    return book


@router.post("/books", status_code=201, response_model=BookOut)
def upload_book(
    file: UploadFile = File(...),
    title: str = Form(..., min_length=1, max_length=300),
    author: str | None = Form(None),
    description: str | None = Form(None),
    cover: UploadFile | None = File(None),
    is_published: bool = Form(True),
    db: Session = Depends(get_db),
):
    book = Book(
        title=title,
        author=author,
        description=description,
        is_published=is_published,
        file_name="",
        file_size=0,
    )
    db.add(book)
    db.flush()
    try:
        book.file_path, book.file_name, book.file_size = storage.save_book(
            book.id, file
        )
        if cover:
            book.cover_path = storage.save_cover(book.id, cover)
        db.commit()
    except Exception:
        storage.delete_book(book.id)
        db.rollback()
        raise
    return start_ingest(db, book)


@router.patch("/books/{book_id}", response_model=BookOut)
def update_book(book_id: int, body: BookPatch, db: Session = Depends(get_db)):
    book = find_book(db, book_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        if key in ("title", "is_published", "suggested_questions") and value is None:
            raise HTTPException(422, "invalid_field")
        setattr(book, key, value)
        if key == "suggested_questions":
            book.questions_overridden = True
    db.commit()
    return book


@router.put("/books/{book_id}/cover", response_model=BookOut)
def update_cover(
    book_id: int, cover: UploadFile = File(...), db: Session = Depends(get_db)
):
    book = find_book(db, book_id)
    book.cover_path = storage.save_cover(book.id, cover)
    db.commit()
    return book


@router.post("/books/{book_id}/reingest", response_model=BookOut)
def reingest(book_id: int, db: Session = Depends(get_db)):
    return start_ingest(db, find_book(db, book_id))


@router.delete("/books/{book_id}", status_code=204)
def delete_book(book_id: int, db: Session = Depends(get_db)):
    book = find_book(db, book_id)
    try:
        ai_client.request("DELETE", f"/v1/books/{book_id}")
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
    conversations = db.scalars(
        select(Conversation).where(Conversation.book_id == book_id)
    ).all()
    for conversation in conversations:
        db.delete(conversation)
    db.delete(book)
    db.commit()
    storage.delete_book(book_id)


@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    def count(model):
        return db.scalar(select(func.count()).select_from(model))

    today = datetime.now(timezone.utc).date()
    messages = db.scalars(
        select(Message).where(
            Message.role == "user",
            Message.created_at
            >= datetime.combine(
                today - timedelta(days=6), datetime.min.time(), tzinfo=timezone.utc
            ),
        )
    ).all()
    days = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    return {
        "books": count(Book),
        "ready_books": db.scalar(
            select(func.count()).select_from(Book).where(Book.status == "ready")
        ),
        "users": count(User),
        "conversations": count(Conversation),
        "questions": db.scalar(
            select(func.count()).select_from(Message).where(Message.role == "user")
        ),
        "questions_last_7d": [
            {
                "date": day,
                "count": sum(m.created_at.date().isoformat() == day for m in messages),
            }
            for day in days
        ],
    }


@router.get("/qa")
def qa(
    book_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    if not 1 <= limit <= 200 or offset < 0:
        raise HTTPException(422, "invalid_pagination")
    query = select(Message).join(Conversation).where(Message.role == "user")
    if book_id is not None:
        query = query.where(Conversation.book_id == book_id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    messages = db.scalars(
        query.order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    items = []
    for message in messages:
        conversation = message.conversation
        answer = db.scalar(
            select(Message)
            .where(
                Message.conversation_id == conversation.id,
                Message.id > message.id,
                Message.role == "assistant",
            )
            .order_by(Message.id)
            .limit(1)
        )
        user = db.get(User, conversation.user_id)
        items.append(
            {
                "id": message.id,
                "question": message.content,
                "answer": answer.content if answer else "",
                "book_id": conversation.book_id,
                "book_title": conversation.book.title,
                "user_email": user.email,
                "created_at": message.created_at,
                "provider": answer.provider if answer else None,
            }
        )
    return {"items": items, "total": total}


@router.get("/users", response_model=list[UserOut])
def users(db: Session = Depends(get_db)):
    return db.scalars(select(User).order_by(User.created_at.desc())).all()


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: AdminUserPatch, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "user_not_found")
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is None:
            raise HTTPException(422, "invalid_field")
        setattr(user, field, value)
    db.commit()
    return user
