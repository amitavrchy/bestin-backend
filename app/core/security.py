from datetime import datetime, timedelta, timezone
import bcrypt
import jwt
from app.core.config import get_settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def create_token(user_id: int) -> str:
    settings = get_settings()
    return jwt.encode({'sub': str(user_id), 'exp': datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)}, settings.jwt_secret, algorithm='HS256')
