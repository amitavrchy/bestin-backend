import logging
from fastapi import HTTPException
from sqlalchemy import select
from app.models import Book
from app.services import ai_client

logger = logging.getLogger(__name__)


def sync_book(db, book):
    if book.status not in ('queued', 'processing'):
        return book
    try:
        data = ai_client.request('GET', f'/v1/books/{book.id}/status')
        status = data.get('status')
        if status == 'not_found':
            status = 'failed'
            data['error'] = 'Book not found in AI service'
        if status in ('queued', 'processing', 'ready', 'failed'):
            book.status = status
        for field in ('progress', 'chunks', 'pages', 'error'):
            if field in data:
                setattr(book, field, data[field])
        if not book.questions_overridden and isinstance(data.get('suggested_questions'), list):
            book.suggested_questions = data['suggested_questions']
        db.commit()
    except HTTPException as exc:
        logger.warning('Could not sync book %s: %s', book.id, exc.detail)
    return book


def visible_book(db, book_id, user):
    book = db.get(Book, book_id)
    if book:
        sync_book(db, book)
    if not book or (user.role != 'admin' and (book.status != 'ready' or not book.is_published)):
        raise HTTPException(404, 'book_not_found')
    return book
