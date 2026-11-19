from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from app.models import User
import logging
from fastapi import HTTPException
from app.models import Book
from app.services import ai_client

logger = logging.getLogger(__name__)


def sync_book(db: Session, book: Book) -> Book:
    """Refresh pending ingestion without hiding the last known state on an outage."""
    if book.status not in ("queued", "processing"):
        return book
    try:
        data = ai_client.request("GET", f"/v1/books/{book.id}/status")
        status = data.get("status")
        if status == "not_found":
            status = "failed"
            data["error"] = "Book not found in AI service"
        if status in ("queued", "processing", "ready", "failed"):
            book.status = status
        for field in ("progress", "chunks", "pages", "error"):
            if field in data:
                setattr(book, field, data[field])
        if not book.questions_overridden and isinstance(
            data.get("suggested_questions"), list
        ):
            book.suggested_questions = data["suggested_questions"]
        db.commit()
    except HTTPException as exc:
        logger.warning("Could not sync book %s: %s", book.id, exc.detail)
    return book


def visible_book(db: Session, book_id: int, user: User) -> Book:
    book = db.get(Book, book_id)
    if book:
        sync_book(db, book)
    if not book or (
        user.role != "admin" and (book.status != "ready" or not book.is_published)
    ):
        raise HTTPException(404, "book_not_found")
    return book


def list_books(q: str | None, user: User, db: Session) -> list[Book]:
    query = select(Book).order_by(Book.created_at.desc())
    if q:
        query = query.where(
            or_(Book.title.ilike(f"%{q}%"), Book.author.ilike(f"%{q}%"))
        )
    books = db.scalars(query).all()
    for book in books:
        sync_book(db, book)
    return [
        b
        for b in books
        if user.role == "admin" or (b.status == "ready" and b.is_published)
    ]
