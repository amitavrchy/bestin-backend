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
    url = os.getenv("TEST_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DB_FALLBACK_SQLITE", "false")
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "storage"))
    get_settings.cache_clear()
    engine = create_engine(url)
    Base.metadata.drop_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
    engine.dispose()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def auth(client, email="admin@bestin.local", password="admin12345"):
    response = client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def ai(method, path, **kwargs):
    if path.endswith("/ingest"):
        return {"status": "queued"}
    if path.endswith("/status"):
        return {
            "status": "ready",
            "progress": 1,
            "chunks": 3,
            "pages": 1,
            "error": None,
            "suggested_questions": ["Why?"],
        }
    if path == "/v1/ask":
        return {
            "answer": "An answer [1]",
            "citations": [
                {
                    "chunk_id": "1",
                    "text": "text",
                    "page": 1,
                    "chapter": None,
                    "score": 0.9,
                }
            ],
            "provider": "extractive",
            "speech": None,
        }
    if path == "/v1/voices":
        return []
    return None


def test_auth_and_guards(client):
    response = client.post(
        "/api/auth/register",
        json={
            "email": "reader@example.com",
            "password": "password123",
            "name": "Reader",
        },
    )
    assert response.status_code == 200
    headers = {"Authorization": "Bearer " + response.json()["access_token"]}
    assert client.get("/api/auth/me", headers=headers).json()["role"] == "user"
    assert client.get("/api/admin/users", headers=headers).status_code == 403
    assert client.get("/api/books").status_code == 401
    assert (
        client.post(
            "/api/auth/register",
            json={
                "email": "reader@example.com",
                "password": "password123",
                "name": "Reader",
            },
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/auth/login", json={"email": "reader@example.com", "password": "wrong"}
        ).status_code
        == 401
    )


def test_book_chat_reporting_and_deletion(client):
    admin = auth(client)
    registration = client.post(
        "/api/auth/register",
        json={
            "email": "reader@example.com",
            "password": "password123",
            "name": "Reader",
        },
    ).json()
    reader = {"Authorization": "Bearer " + registration["access_token"]}
    with patch("app.services.ai_client.request", side_effect=ai):
        response = client.post(
            "/api/admin/books",
            headers=admin,
            data={"title": "A Book"},
            files={"file": ("book.txt", b"book contents", "text/plain")},
        )
        assert response.status_code == 201, response.text
        book_id = response.json()["id"]
        book = client.get(f"/api/books/{book_id}", headers=reader).json()
        assert book["status"] == "ready" and book["suggested_questions"] == ["Why?"]
        assert client.patch(
            f"/api/admin/books/{book_id}",
            headers=admin,
            json={"suggested_questions": ["Custom?"]},
        ).json()["suggested_questions"] == ["Custom?"]
        conversation = client.post(
            "/api/conversations", headers=reader, json={"book_id": book_id}
        ).json()
        cid = conversation["id"]
        answer = client.post(
            f"/api/conversations/{cid}/ask",
            headers=reader,
            json={"question": "What happened?", "speak": False},
        )
        assert answer.status_code == 200, answer.text
        assert answer.json()["assistant_message"]["provider"] == "extractive"
        assert client.get(f"/api/conversations/{cid}", headers=admin).status_code == 404
        assert (
            len(
                client.get(f"/api/conversations/{cid}", headers=reader).json()[
                    "messages"
                ]
            )
            == 2
        )
        assert client.get("/api/admin/stats", headers=admin).json()["questions"] == 1
        assert (
            client.get("/api/admin/qa", headers=admin).json()["items"][0]["answer"]
            == "An answer [1]"
        )
        assert (
            client.delete(f"/api/admin/books/{book_id}", headers=admin).status_code
            == 204
        )
        assert (
            client.get(f"/api/conversations/{cid}", headers=reader).status_code == 404
        )


def test_sqlite_fallback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://bestin:bestin@127.0.0.1:1/bestin"
    )
    monkeypatch.setenv("DB_FALLBACK_SQLITE", "true")
    get_settings.cache_clear()
    with TestClient(app) as client:
        assert client.get("/health").json()["db"] == "sqlite"
        assert Path("data/bestin.db").exists()
    get_settings.cache_clear()


def test_ai_error_mapping_and_voice(client):
    import httpx
    import respx

    headers = auth(client)
    with respx.mock:
        respx.get("http://localhost:8001/v1/voices").mock(
            side_effect=httpx.ConnectError("offline")
        )
        response = client.get("/api/voices", headers=headers)
        assert response.status_code == 502
        assert response.json() == {"detail": "ai_unavailable"}
        respx.post("http://localhost:8001/v1/stt").respond(
            503, json={"detail": "stt_unavailable"}
        )
        response = client.post(
            "/api/stt",
            headers=headers,
            files={"file": ("audio.wav", b"audio", "audio/wav")},
        )
        assert response.status_code == 503
        assert response.json()["detail"] == "stt_unavailable"


def test_upload_validation_and_cover(client):
    from io import BytesIO
    from PIL import Image

    admin = auth(client)
    with patch("app.services.ai_client.request", side_effect=ai):
        response = client.post(
            "/api/admin/books",
            headers=admin,
            data={"title": "Bad"},
            files={"file": ("bad.exe", b"x")},
        )
        assert response.status_code == 415
        response = client.post(
            "/api/admin/books",
            headers=admin,
            data={"title": "Good"},
            files={"file": ("book.md", b"# Book")},
        )
        book_id = response.json()["id"]
        image = BytesIO()
        Image.new("RGB", (1000, 500), "red").save(image, "PNG")
        response = client.put(
            f"/api/admin/books/{book_id}/cover",
            headers=admin,
            files={"cover": ("cover.png", image.getvalue(), "image/png")},
        )
        assert response.status_code == 200 and response.json()["has_cover"]
        response = client.get(f"/api/books/{book_id}/cover")
        assert (
            response.status_code == 200
            and response.headers["content-type"] == "image/webp"
        )
        with Image.open(BytesIO(response.content)) as resized:
            assert resized.size == (600, 300)


@pytest.fixture
def reader(client):
    response = client.post(
        "/api/auth/register",
        json={
            "email": "reader@example.com",
            "password": "password123",
            "name": "Reader",
        },
    )
    return {"Authorization": "Bearer " + response.json()["access_token"]}


@pytest.fixture
def book(client):
    with patch("app.services.ai_client.request", side_effect=ai):
        response = client.post(
            "/api/admin/books",
            headers=auth(client),
            data={"title": "The Sea", "author": "Sailor"},
            files={"file": ("sea.txt", b"The sea is blue.")},
        )
        assert response.status_code == 201
        return response.json()["id"]


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "invalid", "password": "password123", "name": "Name"},
        {"email": "a@example.com", "password": "short", "name": "Name"},
        {"email": "a@example.com", "password": "password123", "name": "   "},
        {"email": "a@example.com", "password": "é" * 40, "name": "Name"},
    ],
)
def test_register_rejects_invalid_input(client, payload):
    assert client.post("/api/auth/register", json=payload).status_code == 422


@pytest.mark.parametrize(
    "path,method",
    [
        ("/api/admin/users", "get"),
        ("/api/admin/stats", "get"),
        ("/api/admin/qa", "get"),
        ("/api/admin/books/1", "delete"),
        ("/api/admin/users/1", "patch"),
    ],
)
def test_admin_routes_reject_readers(client, reader, path, method):
    assert getattr(client, method)(path, headers=reader).status_code == 403


def test_profile_change_and_password(client, reader):
    result = client.patch(
        "/api/auth/me",
        headers=reader,
        json={"name": "New Name", "password": "newpassword"},
    )
    assert result.json()["name"] == "New Name"
    assert (
        client.post(
            "/api/auth/login",
            json={"email": "reader@example.com", "password": "password123"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/auth/login",
            json={"email": "reader@example.com", "password": "newpassword"},
        ).status_code
        == 200
    )


def test_admin_deactivate_and_role(client, reader):
    admin = auth(client)
    uid = client.get("/api/auth/me", headers=reader).json()["id"]
    assert (
        client.patch(
            f"/api/admin/users/{uid}", headers=admin, json={"role": "admin"}
        ).json()["role"]
        == "admin"
    )
    assert client.get("/api/admin/users", headers=reader).status_code == 200
    assert (
        client.patch(
            f"/api/admin/users/{uid}", headers=admin, json={"is_active": False}
        ).status_code
        == 200
    )
    assert client.get("/api/auth/me", headers=reader).status_code == 401
    assert (
        client.patch(
            "/api/admin/users/99999", headers=admin, json={"role": "user"}
        ).status_code
        == 404
    )


@pytest.mark.parametrize("value", [" ", ""])
def test_profile_rejects_blank_name(client, reader, value):
    assert (
        client.patch("/api/auth/me", headers=reader, json={"name": value}).status_code
        == 422
    )


@pytest.mark.parametrize("filename", ["file.exe", "../evil.exe", "file.pdf.exe"])
def test_upload_rejects_file_type_and_cleans_up(client, tmp_path, filename):
    response = client.post(
        "/api/admin/books",
        headers=auth(client),
        data={"title": "Bad"},
        files={"file": (filename, b"data")},
    )
    assert response.status_code == 415
    assert not list((tmp_path / "storage").rglob("*"))


def test_upload_size_limit(client, monkeypatch, tmp_path):
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    response = client.post(
        "/api/admin/books",
        headers=auth(client),
        data={"title": "Big"},
        files={"file": ("big.txt", b"x" * (1024 * 1024 + 1))},
    )
    assert response.status_code == 413
    assert not list((tmp_path / "storage" / "books").glob("*"))


def test_upload_path_is_contained(client, tmp_path):
    with patch("app.services.ai_client.request", side_effect=ai):
        response = client.post(
            "/api/admin/books",
            headers=auth(client),
            data={"title": "Book"},
            files={"file": ("../../escape.txt", b"hello")},
        )
    assert response.status_code == 201
    assert response.json()["file_name"] == "escape.txt"
    assert not (tmp_path / "escape.txt").exists()


def test_visibility_search_and_status(client, reader, book):
    admin = auth(client)
    with patch("app.services.ai_client.request", side_effect=ai):
        assert len(client.get("/api/books?q=sail", headers=reader).json()) == 1
        assert client.get("/api/books?q=missing", headers=reader).json() == []
        client.patch(
            f"/api/admin/books/{book}", headers=admin, json={"is_published": False}
        )
        assert client.get("/api/books", headers=reader).json() == []
        assert client.get(f"/api/books/{book}", headers=reader).status_code == 404
        assert len(client.get("/api/books", headers=admin).json()) == 1


@pytest.mark.parametrize(
    "status", ["queued", "processing", "ready", "failed", "not_found"]
)
def test_status_transitions(client, book, status):
    payload = {
        "status": status,
        "progress": 0.5,
        "chunks": 1,
        "pages": None,
        "error": None,
    }
    with patch("app.services.ai_client.request", return_value=payload):
        result = client.get(f"/api/books/{book}", headers=auth(client))
    assert result.json()["status"] == ("failed" if status == "not_found" else status)


def test_override_questions_survive_sync(client, book):
    admin = auth(client)
    client.patch(
        f"/api/admin/books/{book}",
        headers=admin,
        json={"suggested_questions": ["Mine"]},
    )
    with patch("app.services.ai_client.request", side_effect=ai):
        assert client.get(f"/api/books/{book}", headers=admin).json()[
            "suggested_questions"
        ] == ["Mine"]


def test_reingest_and_delete_files(client, book, tmp_path):
    admin = auth(client)
    folder = tmp_path / "storage" / "books" / str(book)
    assert folder.exists()
    with patch("app.services.ai_client.request", side_effect=ai) as mock:
        assert (
            client.post(f"/api/admin/books/{book}/reingest", headers=admin).json()[
                "status"
            ]
            == "queued"
        )
        assert (
            client.delete(f"/api/admin/books/{book}", headers=admin).status_code == 204
        )
        assert any(
            call.args[:2] == ("DELETE", f"/v1/books/{book}")
            for call in mock.call_args_list
        )
    assert not folder.exists()


def test_cover_invalid_preserves_existing(client, book):
    from io import BytesIO
    from PIL import Image

    out = BytesIO()
    Image.new("RGB", (20, 20), "blue").save(out, "PNG")
    admin = auth(client)
    assert (
        client.put(
            f"/api/admin/books/{book}/cover",
            headers=admin,
            files={"cover": ("cover.png", out.getvalue())},
        ).status_code
        == 200
    )
    before = client.get(f"/api/books/{book}/cover").content
    assert (
        client.put(
            f"/api/admin/books/{book}/cover",
            headers=admin,
            files={"cover": ("bad.png", b"invalid")},
        ).status_code
        == 415
    )
    assert client.get(f"/api/books/{book}/cover").content == before


def test_history_ownership_and_reporting(client, reader, book):
    with patch("app.services.ai_client.request", side_effect=ai) as mock:
        cid = client.post(
            "/api/conversations", headers=reader, json={"book_id": book}
        ).json()["id"]
        for number in range(4):
            assert (
                client.post(
                    f"/api/conversations/{cid}/ask",
                    headers=reader,
                    json={"question": f"Question {number}", "speak": False},
                ).status_code
                == 200
            )
        asks = [c.kwargs["json"] for c in mock.call_args_list if c.args[1] == "/v1/ask"]
        assert len(asks[-1]["history"]) == 6
        assert asks[-1]["history"][0]["content"] == "Question 0"
        assert (
            client.get(f"/api/conversations/{cid}", headers=auth(client)).status_code
            == 404
        )
        listing = client.get(
            f"/api/conversations?book_id={book}", headers=reader
        ).json()
        assert listing[0]["message_count"] == 8 and listing[0]["title"] == "Question 0"
        admin = auth(client)
        stats = client.get("/api/admin/stats", headers=admin).json()
        assert stats["questions"] == 4 and len(stats["questions_last_7d"]) == 7
        qa = client.get(
            f"/api/admin/qa?book_id={book}&limit=2&offset=1", headers=admin
        ).json()
        assert (
            qa["total"] == 4
            and len(qa["items"]) == 2
            and qa["items"][0]["provider"] == "extractive"
        )
        assert (
            client.delete(f"/api/conversations/{cid}", headers=reader).status_code
            == 204
        )
        assert (
            client.get(f"/api/conversations/{cid}", headers=reader).status_code == 404
        )


@pytest.mark.parametrize("query", ["limit=0", "limit=201", "offset=-1"])
def test_qa_pagination_validation(client, query):
    assert client.get("/api/admin/qa?" + query, headers=auth(client)).status_code == 422


@pytest.mark.parametrize(
    "status,detail,expected",
    [
        (409, "anything", "book_not_ready"),
        (500, "error", "ai_unavailable"),
        (503, "other", "ai_unavailable"),
    ],
)
def test_ai_error_mapping(client, status, detail, expected):
    import respx

    with respx.mock:
        respx.get("http://localhost:8001/v1/voices").respond(
            status, json={"detail": detail}
        )
        response = client.get("/api/voices", headers=auth(client))
    assert response.status_code == (409 if status == 409 else 502)
    assert response.json()["detail"] == expected


def test_ask_failure_does_not_store_messages(client, reader, book):
    from fastapi import HTTPException

    with patch("app.services.ai_client.request", side_effect=ai):
        cid = client.post(
            "/api/conversations", headers=reader, json={"book_id": book}
        ).json()["id"]
    with patch(
        "app.services.ai_client.request",
        side_effect=HTTPException(409, "book_not_ready"),
    ):
        response = client.post(
            f"/api/conversations/{cid}/ask", headers=reader, json={"question": "Why?"}
        )
    assert response.status_code == 409
    assert (
        client.get(f"/api/conversations/{cid}", headers=reader).json()["messages"] == []
    )


def test_request_id_and_missing_cover(client):
    response = client.get("/api/books/999/cover")
    assert response.status_code == 404 and len(response.headers["x-request-id"]) == 32


def test_failed_ingest_cleans_upload(client, tmp_path):
    from fastapi import HTTPException

    admin = auth(client)
    with patch(
        "app.services.ai_client.request",
        side_effect=HTTPException(502, "ai_unavailable"),
    ):
        response = client.post(
            "/api/admin/books",
            headers=admin,
            data={"title": "Failed"},
            files={"file": ("book.txt", b"content")},
        )
    assert response.status_code == 502
    assert client.get("/api/books", headers=admin).json() == []
    assert not list((tmp_path / "storage" / "books").glob("*"))
