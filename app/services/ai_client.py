import logging
import httpx
from fastapi import HTTPException
from app.core.config import get_settings

logger = logging.getLogger(__name__)


def request(method, path, **kwargs):
    settings = get_settings()
    try:
        with httpx.Client(
            base_url=settings.ai_url,
            timeout=settings.ai_timeout,
            headers={"X-Internal-Token": settings.ai_internal_token},
        ) as client:
            response = client.request(method, path, **kwargs)
    except httpx.RequestError as exc:
        logger.warning("AI service unavailable: %s", exc)
        raise HTTPException(502, "ai_unavailable") from exc
    if response.is_error:
        if response.status_code >= 500 and response.status_code != 503:
            raise HTTPException(502, "ai_unavailable")
        try:
            detail = response.json().get("detail", "ai_error")
        except ValueError:
            detail = "ai_error"
        raise HTTPException(response.status_code, detail)
    return None if response.status_code == 204 else response.json()


def ingest(book):
    with open(book.file_path, "rb") as file:
        return request(
            "POST",
            f"/v1/books/{book.id}/ingest",
            files={"file": (book.file_name, file)},
            data={"title": book.title},
        )
