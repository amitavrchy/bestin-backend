import logging
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.core.config import get_settings

logger = logging.getLogger(__name__)
engine = None
SessionLocal = sessionmaker(expire_on_commit=False)


def configure_database():
    global engine
    settings = get_settings()
    url = settings.database_url
    try:
        candidate = create_engine(url, connect_args={'connect_timeout': 3} if url.startswith('postgresql') else {})
        with candidate.connect() as connection:
            connection.execute(text('SELECT 1'))
    except Exception:
        if not settings.db_fallback_sqlite or not url.startswith('postgresql'):
            raise
        logger.warning('PostgreSQL unavailable; falling back to SQLite', exc_info=True)
        Path('data').mkdir(exist_ok=True)
        candidate = create_engine('sqlite:///data/bestin.db', connect_args={'check_same_thread': False})
    engine = candidate
    SessionLocal.configure(bind=engine)
    return engine


def get_db():
    with SessionLocal() as db:
        yield db
