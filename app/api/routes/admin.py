from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session
from app.api.deps import require_admin
from app.db.session import get_db
from app.schemas import AdminUserPatch, BookOut, BookPatch, UserOut
from app.services import admin as service


router = APIRouter(
    prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)]
)


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
    return service.upload_book(
        file, title, author, description, cover, is_published, db
    )


@router.patch("/books/{book_id}", response_model=BookOut)
def update_book(book_id: int, body: BookPatch, db: Session = Depends(get_db)):
    return service.update_book(book_id, body, db)


@router.put("/books/{book_id}/cover", response_model=BookOut)
def update_cover(
    book_id: int, cover: UploadFile = File(...), db: Session = Depends(get_db)
):
    return service.update_cover(book_id, cover, db)


@router.post("/books/{book_id}/reingest", response_model=BookOut)
def reingest(book_id: int, db: Session = Depends(get_db)):
    return service.reingest(book_id, db)


@router.delete("/books/{book_id}", status_code=204)
def delete_book(book_id: int, db: Session = Depends(get_db)):
    return service.delete_book(book_id, db)


@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    return service.stats(db)


@router.get("/qa")
def qa(
    book_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    return service.qa(book_id, limit, offset, db)


@router.get("/users", response_model=list[UserOut])
def users(db: Session = Depends(get_db)):
    return service.users(db)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: AdminUserPatch, db: Session = Depends(get_db)):
    return service.update_user(user_id, body, db)
