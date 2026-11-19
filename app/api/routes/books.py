from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from app.api.deps import current_user
from app.db.session import get_db
from app.models import Book, User
from app.schemas import BookOut
from app.services.books import sync_book, visible_book

router = APIRouter(prefix='/api/books', tags=['books'])


@router.get('', response_model=list[BookOut])
def list_books(q: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = select(Book).order_by(Book.created_at.desc())
    if q:
        query = query.where(or_(Book.title.ilike(f'%{q}%'), Book.author.ilike(f'%{q}%')))
    books = db.scalars(query).all()
    for book in books:
        sync_book(db, book)
    return [b for b in books if user.role == 'admin' or (b.status == 'ready' and b.is_published)]


@router.get('/{book_id}', response_model=BookOut)
def get_book(book_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return visible_book(db, book_id, user)


@router.get('/{book_id}/cover')
def cover(book_id: int, db: Session = Depends(get_db)):
    from pathlib import Path
    book = db.get(Book, book_id)
    if not book or not book.cover_path or not Path(book.cover_path).is_file():
        raise HTTPException(404, 'cover_not_found')
    return FileResponse(book.cover_path, media_type='image/webp')
