import logging
from typing import Any

import httpx
from fastapi import HTTPException
from app.core.config import get_settings
from app.models import Book

logger = logging.getLogger(__name__)


def request(method: str, path: str, **kwargs: Any) -> Any:
    """Call the internal service, retrying a failed connection once."""
    settings = get_settings()
    try:
        with httpx.Client(
            base_url=settings.ai_url,
            timeout=settings.ai_timeout,
            headers={"X-Internal-Token": settings.ai_internal_token},
            transport=httpx.HTTPTransport(retries=1),
        ) as client:
            response = client.request(method, path, **kwargs)
    except httpx.RequestError as exc:
        logger.warning("AI service unavailable: %s", exc)
        raise HTTPException(502, "ai_unavailable") from exc
    if response.is_error:
        if response.status_code == 409:
            raise HTTPException(409, "book_not_ready")
        if response.status_code >= 500:
            if response.status_code == 503 and path == "/v1/stt":
                try:
                    detail = response.json().get("detail")
                except ValueError:
                    detail = None
                if detail == "stt_unavailable":
                    raise HTTPException(503, detail)
            raise HTTPException(502, "ai_unavailable")
        try:
            detail = response.json().get("detail", "ai_error")
        except ValueError:
            detail = "ai_error"
        raise HTTPException(response.status_code, detail)
    if response.status_code == 204:
        return None
    try:
        return response.json()
    except ValueError as exc:
        logger.warning("AI service returned invalid JSON for %s", path)
        raise HTTPException(502, "ai_unavailable") from exc


def ingest(book: Book) -> Any:
    with open(book.file_path, "rb") as file:
        return request(
            "POST",
            f"/v1/books/{book.id}/ingest",
            files={"file": (book.file_name, file)},
            data={"title": book.title},
        )
