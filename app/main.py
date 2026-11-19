import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path
import httpx
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from app.api.routes import admin, auth, books, conversations, voice
from app.core import logging as logging_setup  # noqa: F401
from app.core.config import get_settings
from app.core.security import hash_password
from app.db import session
from app.models import Book, User
from app.services.books import sync_book

logger = logging.getLogger(__name__)


def poll_once():
    with session.SessionLocal() as db:
        for book in db.scalars(select(Book).where(Book.status.in_(['queued', 'processing']))).all():
            sync_book(db, book)


async def poll():
    while True:
        await asyncio.sleep(get_settings().status_poll_seconds)
        try:
            await asyncio.to_thread(poll_once)
        except Exception:
            logger.exception('Book status poll failed')


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = session.configure_database()
    config = Config(str(Path(__file__).resolve().parent.parent / 'alembic.ini'))
    config.set_main_option('script_location', str(Path(__file__).resolve().parent.parent / 'alembic'))
    with engine.begin() as connection:
        config.attributes['connection'] = connection
        command.upgrade(config, 'head')
    settings = get_settings()
    with session.SessionLocal() as db:
        if not db.scalar(select(User).where(User.email == settings.admin_email.lower())):
            db.add(User(email=settings.admin_email.lower(), name='Admin', password_hash=hash_password(settings.admin_password), role='admin'))
            db.commit()
    task = asyncio.create_task(poll())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    engine.dispose()


settings = get_settings()
app = FastAPI(title='Bestin Backend', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[origin.strip() for origin in settings.cors_origins.split(',') if origin.strip()], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
for router in (auth.router, books.router, admin.router, conversations.router, voice.router):
    app.include_router(router)


@app.get('/health')
def health():
    try:
        response = httpx.get(f'{get_settings().ai_url}/health', timeout=2)
        ai = 'ok' if response.is_success else 'unreachable'
    except httpx.RequestError:
        ai = 'unreachable'
    return {'status': 'ok', 'service': 'bestin-backend', 'db': session.engine.dialect.name, 'ai': ai}
