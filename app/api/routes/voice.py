from fastapi import APIRouter, Depends, File, UploadFile
from app.api.deps import current_user
from app.schemas import TTS
from app.services import ai_client

router = APIRouter(prefix="/api", tags=["voice"], dependencies=[Depends(current_user)])


@router.get("/voices")
def voices():
    return ai_client.request("GET", "/v1/voices")


@router.post("/tts")
def tts(body: TTS):
    return ai_client.request("POST", "/v1/tts", json=body.model_dump(exclude_none=True))


@router.post("/stt")
def stt(file: UploadFile = File(...)):
    return ai_client.request(
        "POST",
        "/v1/stt",
        files={
            "file": (
                file.filename,
                file.file,
                file.content_type or "application/octet-stream",
            )
        },
    )
