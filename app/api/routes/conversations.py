from typing import Literal
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session
from app.api.deps import current_user
from app.db.session import get_db
from app.models import User
from app.services import conversations as service, ai_client

from app.schemas import (
    Ask,
    ConversationCreate,
    ConversationDetail,
    ConversationOut,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.post("", response_model=ConversationOut)
def create(
    body: ConversationCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return service.create(body, user, db)


@router.get("", response_model=list[ConversationOut])
def listing(
    book_id: int | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return service.listing(book_id, user, db)


@router.get("/{conversation_id}", response_model=ConversationDetail)
def detail(
    conversation_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return service.detail(conversation_id, user, db)


@router.delete("/{conversation_id}", status_code=204)
def delete(
    conversation_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return service.delete(conversation_id, user, db)


@router.post("/{conversation_id}/ask")
def ask(
    conversation_id: int,
    body: Ask,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return service.ask(conversation_id, body, user, db)


@router.post("/{conversation_id}/ask-voice")
def ask_voice(
    conversation_id: int,
    file: UploadFile = File(...),
    speak: bool = Form(True),
    voice: str | None = Form(None),
    style: Literal["concise", "detailed"] = Form("concise"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    service.owned_conversation(db, conversation_id, user.id)
    data = file.file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "file_too_large")
    transcript = ai_client.request("POST", "/v1/stt", files={
        "file": (file.filename or "recording.webm", data, file.content_type or "application/octet-stream")
    }).get("text", "").strip()
    if not transcript:
        raise HTTPException(422, "no_speech")
    result = service.ask(conversation_id, Ask(question=transcript, speak=speak, voice=voice, style=style), user, db)
    return {**result, "transcript": transcript, "input": "voice"}
