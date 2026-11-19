import os
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from app.core.config import get_settings
from app.db.base import Base
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    url = os.getenv('TEST_DATABASE_URL', f'sqlite:///{tmp_path}/test.db')
    monkeypatch.setenv('DATABASE_URL', url)
    monkeypatch.setenv('DB_FALLBACK_SQLITE', 'false')
    monkeypatch.setenv('STORAGE_DIR', str(tmp_path / 'storage'))
    get_settings.cache_clear()
    engine = create_engine(url)
    Base.metadata.drop_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql('DROP TABLE IF EXISTS alembic_version')
    engine.dispose()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def auth(client, email='admin@bestin.local', password='admin12345'):
    response = client.post('/api/auth/login', json={'email': email, 'password': password})
    assert response.status_code == 200, response.text
    return {'Authorization': 'Bearer ' + response.json()['access_token']}


def ai(method, path, **kwargs):
    if path.endswith('/ingest'):
        return {'status': 'queued'}
    if path.endswith('/status'):
        return {'status': 'ready', 'progress': 1, 'chunks': 3, 'pages': 1, 'error': None, 'suggested_questions': ['Why?']}
    if path == '/v1/ask':
        return {'answer': 'An answer [1]', 'citations': [{'chunk_id': '1', 'text': 'text', 'page': 1, 'chapter': None, 'score': 0.9}], 'provider': 'extractive', 'speech': None}
    if path == '/v1/voices':
        return []
    return None


def test_auth_and_guards(client):
    response = client.post('/api/auth/register', json={'email': 'reader@example.com', 'password': 'password123', 'name': 'Reader'})
    assert response.status_code == 200
    headers = {'Authorization': 'Bearer ' + response.json()['access_token']}
    assert client.get('/api/auth/me', headers=headers).json()['role'] == 'user'
    assert client.get('/api/admin/users', headers=headers).status_code == 403
    assert client.get('/api/books').status_code == 401
    assert client.post('/api/auth/register', json={'email': 'reader@example.com', 'password': 'password123', 'name': 'Reader'}).status_code == 409
    assert client.post('/api/auth/login', json={'email': 'reader@example.com', 'password': 'wrong'}).status_code == 401


def test_book_chat_reporting_and_deletion(client):
    admin = auth(client)
    registration = client.post('/api/auth/register', json={'email': 'reader@example.com', 'password': 'password123', 'name': 'Reader'}).json()
    reader = {'Authorization': 'Bearer ' + registration['access_token']}
    with patch('app.services.ai_client.request', side_effect=ai):
        response = client.post('/api/admin/books', headers=admin, data={'title': 'A Book'}, files={'file': ('book.txt', b'book contents', 'text/plain')})
        assert response.status_code == 201, response.text
        book_id = response.json()['id']
        book = client.get(f'/api/books/{book_id}', headers=reader).json()
        assert book['status'] == 'ready' and book['suggested_questions'] == ['Why?']
        assert client.patch(f'/api/admin/books/{book_id}', headers=admin, json={'suggested_questions': ['Custom?']}).json()['suggested_questions'] == ['Custom?']
        conversation = client.post('/api/conversations', headers=reader, json={'book_id': book_id}).json()
        cid = conversation['id']
        answer = client.post(f'/api/conversations/{cid}/ask', headers=reader, json={'question': 'What happened?', 'speak': False})
        assert answer.status_code == 200, answer.text
        assert answer.json()['assistant_message']['provider'] == 'extractive'
        assert client.get(f'/api/conversations/{cid}', headers=admin).status_code == 404
        assert len(client.get(f'/api/conversations/{cid}', headers=reader).json()['messages']) == 2
        assert client.get('/api/admin/stats', headers=admin).json()['questions'] == 1
        assert client.get('/api/admin/qa', headers=admin).json()['items'][0]['answer'] == 'An answer [1]'
        assert client.delete(f'/api/admin/books/{book_id}', headers=admin).status_code == 204
        assert client.get(f'/api/conversations/{cid}', headers=reader).status_code == 404


def test_sqlite_fallback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('DATABASE_URL', 'postgresql+psycopg://bestin:bestin@127.0.0.1:1/bestin')
    monkeypatch.setenv('DB_FALLBACK_SQLITE', 'true')
    get_settings.cache_clear()
    with TestClient(app) as client:
        assert client.get('/health').json()['db'] == 'sqlite'
        assert Path('data/bestin.db').exists()
    get_settings.cache_clear()
