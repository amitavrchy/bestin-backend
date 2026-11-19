from pathlib import Path
import shutil
from PIL import Image, UnidentifiedImageError
from fastapi import HTTPException, UploadFile
from app.core.config import get_settings


def directory(book_id):
    return Path(get_settings().storage_dir) / "books" / str(book_id)


def save_book(book_id: int, upload: UploadFile):
    name = Path((upload.filename or "").replace("\\", "/")).name
    if Path(name).suffix.lower() not in {".pdf", ".epub", ".txt", ".md"}:
        raise HTTPException(415, "unsupported_file_type")
    folder = directory(book_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    limit = get_settings().max_upload_mb * 1024 * 1024
    size = 0
    try:
        with path.open("wb") as out:
            while chunk := upload.file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, "file_too_large")
                out.write(chunk)
        if not size:
            raise HTTPException(400, "empty_file")
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return str(path), name, size


def save_cover(book_id: int, upload: UploadFile):
    folder = directory(book_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "cover.webp"
    temporary = folder / "cover.tmp"
    try:
        with Image.open(upload.file) as image:
            image.thumbnail((600, 600))
            image.convert("RGB").save(temporary, "WEBP", quality=85)
        temporary.replace(path)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        temporary.unlink(missing_ok=True)
        raise HTTPException(415, "invalid_cover") from exc
    return str(path)


def delete_book(book_id):
    shutil.rmtree(directory(book_id), ignore_errors=True)
