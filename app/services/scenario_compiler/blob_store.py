from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
from uuid import uuid4

from fastapi import HTTPException, UploadFile


MEDIA_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".csv": "text/csv",
}
ACCEPTED_UPLOAD_TYPES = {
    "application/pdf",
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/octet-stream",
}


def upload_root() -> Path:
    return Path(os.getenv("WORLDPULSE_UPLOAD_ROOT", "data/uploads")).resolve()


def max_upload_bytes() -> int:
    configured = int(os.getenv("WORLDPULSE_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
    return max(1024, min(configured, 50 * 1024 * 1024))


async def store_upload(upload: UploadFile) -> tuple[str, int, str, str, bool]:
    filename = _safe_filename(upload.filename or "")
    suffix = Path(filename).suffix.lower()
    expected_media = MEDIA_BY_SUFFIX.get(suffix)
    if not expected_media:
        raise HTTPException(status_code=415, detail="Only PDF, TXT, Markdown and CSV documents are supported")
    supplied = str(upload.content_type or "application/octet-stream").split(";", 1)[0].strip().lower()
    if supplied not in ACCEPTED_UPLOAD_TYPES:
        raise HTTPException(status_code=415, detail="Uploaded media type is not supported")
    if supplied != "application/octet-stream" and not _media_compatible(supplied, expected_media):
        raise HTTPException(status_code=415, detail="Filename extension and media type do not match")

    root = upload_root()
    temporary = root / "tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    temp_path = (temporary / f"upload-{uuid4().hex}.part").resolve()
    if root not in temp_path.parents:
        raise HTTPException(status_code=422, detail="Unsafe upload path")
    digest = hashlib.sha256()
    size = 0
    prefix = b""
    try:
        with temp_path.open("xb") as handle:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                if not prefix:
                    prefix = chunk[:16]
                size += len(chunk)
                if size > max_upload_bytes():
                    raise HTTPException(status_code=413, detail=f"Document exceeds the {max_upload_bytes()} byte upload limit")
                digest.update(chunk)
                handle.write(chunk)
        if size == 0:
            raise HTTPException(status_code=422, detail="Empty documents are not accepted")
        _verify_signature(expected_media, prefix)
        content_hash = digest.hexdigest()
        blob_key = f"sha256/{content_hash[:2]}/{content_hash}"
        destination = (root / blob_key).resolve()
        if root not in destination.parents:
            raise HTTPException(status_code=422, detail="Unsafe content-addressed blob path")
        destination.parent.mkdir(parents=True, exist_ok=True)
        created = not destination.exists()
        if created:
            temp_path.replace(destination)
        else:
            temp_path.unlink(missing_ok=True)
        return content_hash, size, blob_key, expected_media, created
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


def resolve_blob(blob_key: str) -> Path:
    root = upload_root()
    path = (root / blob_key).resolve()
    if root not in path.parents or not re.fullmatch(r"sha256/[0-9a-f]{2}/[0-9a-f]{64}", blob_key):
        raise HTTPException(status_code=409, detail="Stored document blob key is invalid")
    return path


def verify_blob(blob_key: str, expected_hash: str, expected_size: int) -> dict:
    path = resolve_blob(blob_key)
    if not path.is_file():
        return {"status": "missing", "blob_key": blob_key, "expected_hash": expected_hash}
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    actual = digest.hexdigest()
    status = "verified" if actual == expected_hash and size == expected_size else "failed"
    return {"status": status, "blob_key": blob_key, "expected_hash": expected_hash, "actual_hash": actual, "expected_size": expected_size, "actual_size": size}


def _safe_filename(filename: str) -> str:
    if not filename or filename in {".", ".."}:
        raise HTTPException(status_code=422, detail="Document filename is required")
    if Path(filename).name != filename or "/" in filename or "\\" in filename or "\x00" in filename:
        raise HTTPException(status_code=422, detail="Document filename contains an unsafe path")
    if len(filename) > 240:
        raise HTTPException(status_code=422, detail="Document filename is too long")
    return filename


def _media_compatible(supplied: str, expected: str) -> bool:
    if supplied == expected:
        return True
    return expected in {"text/plain", "text/markdown", "text/csv"} and supplied == "text/plain"


def _verify_signature(media_type: str, prefix: bytes) -> None:
    if media_type == "application/pdf" and not prefix.startswith(b"%PDF-"):
        raise HTTPException(status_code=415, detail="PDF signature is missing or invalid")
    if media_type != "application/pdf" and b"\x00" in prefix:
        raise HTTPException(status_code=415, detail="Text document contains a binary signature")
