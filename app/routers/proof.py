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
)
from app.schemas import ProofOut

router = APIRouter()


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

    storage_ref: str | None = None
    sha256: str | None = None
    phash: str | None = None

    if file is not None:
        data = await file.read()
        if len(data) > settings.proof_max_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"File exceeds max size of {settings.proof_max_bytes} bytes",
            )
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
        # Keep the original extension for reviewer convenience; the sha-prefixed
        # name avoids collisions without trusting the client filename.
        _, ext = os.path.splitext(file.filename or "")
        stored_name = f"{sha256}{ext}"
        storage_ref = os.path.join(settings.proof_upload_dir, stored_name)
        with open(storage_ref, "wb") as fh:
            fh.write(data)

    if file is None and not url:
        raise HTTPException(
            status_code=400, detail="Provide a file, a url, or both as proof"
        )

    from datetime import datetime, timezone

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
        warning_ack_at=datetime.now(timezone.utc),
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
    return [
        ProofOut(
            id=p.id,
            status=p.status,
            proof_type=p.proof_type,
            created_at=p.created_at,
        )
        for p in proofs
    ]
