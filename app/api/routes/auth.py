from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.api.deps import current_user
from app.core.security import create_token, hash_password, verify_password
from app.db.session import get_db
from app.models import User
from app.schemas import Login, Register, Token, UserOut

router = APIRouter(prefix='/api/auth', tags=['auth'])


def token(user):
    return Token(access_token=create_token(user.id), user=UserOut.model_validate(user))


@router.post('/register', response_model=Token)
def register(body: Register, db: Session = Depends(get_db)):
    if len(body.password.encode()) > 72 or not body.name.strip():
        raise HTTPException(422, 'invalid_input')
    user = User(email=body.email.lower(), name=body.name.strip(), password_hash=hash_password(body.password), role='user')
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'email_already_registered')
    return token(user)


@router.post('/login', response_model=Token)
def login(body: Login, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, 'invalid_credentials')
    return token(user)


@router.get('/me', response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user
