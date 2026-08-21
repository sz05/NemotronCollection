"""Proof submission routes: a user uploads evidence (file and/or URL) that
they completed a task for a given chat session. Submissions land in a pending
queue for admin review (see admin.py).

Anti-cheat + integrity handling here:
- warning_ack must be True (the client shows a "submitting false proof can get
  you disqualified" notice; we refuse to store a proof without the ack).
- sha256 of the raw file bytes gives an exact-duplicate check: if the same
  bytes were already submitted for this task, reject 409.
- perceptual hash (phash) for images is best-effort metadata for reviewers to
  spot near-duplicates; PIL/imagehash are lazy-imported and failures degrade
  to None rather than blocking the upload.
"""

import hashlib
import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.deps import get_current_user
from app.models import User
from app.repository import (
    create_proof,
    find_proof_by_sha,
    get_chat_session,
    get_proof,
    get_task,
    session_has_pending_proof,
)
from app.schemas import ProofOut

router = APIRouter()

# Allowed upload content types (client-declared) -> canonical extension.
# Screenshots + PDF decks cover the file proof kinds for these tasks; other
# artifacts (repos, live sites) go via a URL. The extension is derived from
# this map so a client-supplied filename is never trusted.
_ALLOWED_UPLOAD_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}

_URL_SCHEMES = ("http://", "https://")
_MAX_URL_LEN = 2048


def _compute_phash(data: bytes) -> str | None:
    """Perceptual hash for near-duplicate image detection. Heavy deps are
    imported lazily so a missing PIL/imagehash never breaks proof upload."""
    try:
        import io

        import imagehash
        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            return str(imagehash.phash(img))
    except Exception:
        # Non-image bytes, unsupported format, or deps absent -> no phash.
        return None


async def _get_owned_session(db: AsyncSession, session_id: uuid.UUID, user: User):
    session = await get_chat_session(db, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=404, detail=f"ChatSession {session_id} not found")
    return session


@router.post("/sessions/{session_id}/proof", response_model=ProofOut)
async def submit_proof(
    session_id: uuid.UUID,
    proof_type: str = Form(...),
    warning_ack: bool = Form(False),
    url: str | None = Form(None),
    file: UploadFile | None = File(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> ProofOut:
    session = await _get_owned_session(db, session_id, user)

    if session.task_id is None:
        raise HTTPException(
            status_code=400, detail="This session is not attached to a task"
        )

    # Anti-cheat gate: the client must surface the false-proof warning and pass
    # the acknowledgement back. Without it we refuse to store anything.
    if not warning_ack:
        raise HTTPException(
            status_code=400, detail="warning_ack must be true to submit a proof"
        )

    task = await get_task(db, session.task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task for this session not found")

    # One in-flight submission at a time: block a resubmission until the
    # previous proof has been graded (verified) or rejected.
    if await session_has_pending_proof(db, session.id):
        raise HTTPException(
            status_code=409,
            detail="You already have a submission pending review -- wait for it to be graded.",
        )

    # M1: proof_type must be one the task accepts.
    if task.proof_types and proof_type not in task.proof_types:
        raise HTTPException(
            status_code=400,
            detail=f"proof_type must be one of {task.proof_types}",
        )

    # M1: a submitted URL must be a plain web link -- reject javascript:/data:
    # and other schemes that could XSS a reviewer or drive an SSRF.
    if url is not None:
        url = url.strip() or None
    if url is not None:
        if len(url) > _MAX_URL_LEN or not url.lower().startswith(_URL_SCHEMES):
            raise HTTPException(status_code=400, detail="url must be an http(s) link")

    storage_ref: str | None = None
    sha256: str | None = None
    phash: str | None = None

    if file is not None:
        # M2: reject unsupported types up front (client-declared; combined with
        # the size cap and non-web-served storage this is sufficient here).
        content_type = (file.content_type or "").split(";")[0].strip().lower()
        if content_type not in _ALLOWED_UPLOAD_TYPES:
            raise HTTPException(
                status_code=415,
                detail="Unsupported file type -- upload a PNG/JPG/GIF/WEBP image or a PDF, or use a URL.",
            )

        # M2: read in bounded chunks and abort the moment the cap is exceeded,
        # so an oversized upload can't be fully buffered into memory first.
        max_bytes = settings.proof_max_bytes
        buf = bytearray()
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            buf.extend(chunk)
            if len(buf) > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds max size of {max_bytes} bytes",
                )
        data = bytes(buf)
        if not data:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        sha256 = hashlib.sha256(data).hexdigest()

        # Exact-duplicate reject: identical bytes already submitted for this task.
        existing = await find_proof_by_sha(db, task.id, sha256)
        if existing is not None:
            raise HTTPException(
                status_code=409, detail="This exact file was already submitted for this task"
            )

        phash = _compute_phash(data)

        os.makedirs(settings.proof_upload_dir, exist_ok=True)
        # Extension derived from the validated content type -- never from the
        # client filename. The sha-prefixed name avoids collisions.
        ext = _ALLOWED_UPLOAD_TYPES[content_type]
        stored_name = f"{sha256}{ext}"
        storage_ref = os.path.join(settings.proof_upload_dir, stored_name)
        with open(storage_ref, "wb") as fh:
            fh.write(data)

    if file is None and not url:
        raise HTTPException(
            status_code=400, detail="Provide a file, a url, or both as proof"
        )

    # Naive UTC to match the TIMESTAMP WITHOUT TIME ZONE columns -- asyncpg
    # rejects mixing aware/naive datetimes in one INSERT (same convention as
    # the models' _utcnow()).
    from app.models import _utcnow

    proof = await create_proof(
        db,
        session_id=session.id,
        task_id=task.id,
        user_id=user.id,
        proof_type=proof_type,
        storage_ref=storage_ref,
        url=url,
        sha256=sha256,
        phash=phash,
        meta={},
        warning_ack_at=_utcnow(),
    )

    return ProofOut(
        id=proof.id,
        status=proof.status,
        proof_type=proof.proof_type,
        created_at=proof.created_at,
    )


@router.get("/sessions/{session_id}/proof", response_model=list[ProofOut])
async def get_proof_status(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[ProofOut]:
    session = await _get_owned_session(db, session_id, user)

    from sqlalchemy import select

    from app.models import ProofSubmission

    result = await db.execute(
        select(ProofSubmission)
        .where(ProofSubmission.session_id == session.id)
        .order_by(ProofSubmission.created_at.desc())
    )
    proofs = result.scalars().all()

    # All proofs in a session share the same task; grade each from its
    # quality_factor so the participant sees the % and points they earned.
    # points = quality_factor (0..1) * the task's base_points -- a direct
    # "% of the task's points", no difficulty multiplier.
    task = await get_task(db, session.task_id) if session.task_id else None

    def _out(p) -> ProofOut:
        # Only a *verified* proof carries a grade -- a rejected one earns no
        # points even though a quality_factor may have been recorded.
        percent = points = quality_factor = None
        if p.status == "verified" and p.quality_factor is not None:
            quality_factor = p.quality_factor
            percent = round(p.quality_factor * 100)
            if task is not None:
                points = round(task.base_points * p.quality_factor)
        return ProofOut(
            id=p.id,
            status=p.status,
            proof_type=p.proof_type,
            created_at=p.created_at,
            quality_factor=quality_factor,
            percent=percent,
            points=points,
            review_notes=p.review_notes,
        )

    return [_out(p) for p in proofs]
