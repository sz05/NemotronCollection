"""Admin routes (allowlist-gated via require_admin): review the full proof
queue, award/adjust points with a quality_factor (0..1 = % of the task's
points), reject submissions, and serve uploaded proof files for review.

Point award on verify:
    points = round(task.base_points * difficulty_weight * quality_factor)
Re-verifying a resubmitted proof updates the existing (user, task) award to the
new grade -- a stronger PoC raises the participant's points.
"""

import os
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import require_admin
from app.models import User
from app.repository import (
    get_proof,
    get_task,
    get_user,
    list_all_proofs,
    review_proof,
    upsert_award,
    user_total_score,
)
from app.schemas import AdminProofOut, ReviewRequest
from app.state import feedback_connection_manager

router = APIRouter()


def _grade(task, quality_factor: float | None) -> tuple[int | None, int | None]:
    """(-> percent, points) for a graded proof; (None, None) if ungraded.
    points is a direct % of the task's base_points -- no difficulty multiplier,
    so 50% of a 250-pt task is 125."""
    if quality_factor is None or task is None:
        return None, None
    return round(quality_factor * 100), round(task.base_points * quality_factor)


def _to_admin_out(proof, user, task) -> AdminProofOut:
    # A grade only counts for a verified proof (rejected earns nothing).
    percent, points = (
        _grade(task, proof.quality_factor) if proof.status == "verified" else (None, None)
    )
    return AdminProofOut(
        id=proof.id,
        session_id=proof.session_id,
        task_id=proof.task_id,
        user_id=proof.user_id,
        user_email=(user.email if user else ""),
        user_name=(user.display_name or user.name if user else "") or "",
        task_title=(task.title if task else ""),
        base_points=(task.base_points if task else 0),
        proof_type=proof.proof_type,
        storage_ref=proof.storage_ref,
        has_file=bool(proof.storage_ref),
        url=proof.url,
        status=proof.status,
        sha256=proof.sha256,
        phash=proof.phash,
        quality_factor=proof.quality_factor,
        percent=percent,
        points=points,
        review_notes=proof.review_notes,
        meta=proof.meta,
        created_at=proof.created_at,
        reviewed_at=proof.reviewed_at,
    )


@router.get("/admin/proofs", response_model=list[AdminProofOut])
async def list_proofs(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> list[AdminProofOut]:
    """Every submission (newest first) with participant + task + grade, so the
    admin sees each participant's PoCs and their current status/percentage."""
    proofs = await list_all_proofs(db)
    users: dict[uuid.UUID, User] = {}
    tasks: dict[uuid.UUID, object] = {}
    out: list[AdminProofOut] = []
    for p in proofs:
        if p.user_id not in users:
            users[p.user_id] = await get_user(db, p.user_id)
        if p.task_id not in tasks:
            tasks[p.task_id] = await get_task(db, p.task_id)
        out.append(_to_admin_out(p, users[p.user_id], tasks[p.task_id]))
    return out


@router.get("/admin/proofs/{proof_id}/file")
async def get_proof_file(
    proof_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> FileResponse:
    """Serve an uploaded proof file to a reviewer. Admin-only; streams the file
    from disk by its stored path (never trusting a client-supplied path)."""
    proof = await get_proof(db, proof_id)
    if proof is None or not proof.storage_ref:
        raise HTTPException(status_code=404, detail="No file for this proof")
    if not os.path.isfile(proof.storage_ref):
        # Row exists but the file is gone (e.g. ephemeral disk wiped on redeploy).
        raise HTTPException(status_code=410, detail="Proof file is no longer on disk")
    return FileResponse(proof.storage_ref)


@router.post("/admin/proofs/{proof_id}/review", response_model=AdminProofOut)
async def review(
    proof_id: uuid.UUID,
    body: ReviewRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> AdminProofOut:
    decision = body.decision.lower().strip()
    if decision not in ("verified", "rejected"):
        raise HTTPException(
            status_code=400, detail="decision must be 'verified' or 'rejected'"
        )

    proof = await get_proof(db, proof_id)
    if proof is None:
        raise HTTPException(status_code=404, detail=f"Proof {proof_id} not found")
    # A reviewer must not grade their own submission (security finding C1).
    if proof.user_id == admin.id:
        raise HTTPException(status_code=403, detail="You cannot review your own submission")
    # Can't reject an already-verified proof: the reject path doesn't remove the
    # award, so it would strand the points. A graded proof can only be re-graded
    # (decision="verified"), which updates the award in place.
    if decision == "rejected" and proof.status == "verified":
        raise HTTPException(
            status_code=409,
            detail="This proof is already verified -- re-grade it instead of rejecting.",
        )

    # quality_factor is already clamped to [0, 1] by the schema (finding C2).
    quality_factor = body.quality_factor if body.quality_factor is not None else 1.0

    task = await get_task(db, proof.task_id)

    if decision == "verified":
        if task is None:
            raise HTTPException(status_code=404, detail="Task for this proof not found")
        # Direct % of the task's points (no difficulty multiplier).
        points = round(task.base_points * quality_factor)

        proof = await review_proof(
            db,
            proof_id,
            decision="verified",
            quality_factor=quality_factor,
            notes=body.notes,
            reviewer_id=admin.id,
        )
        # Upsert so a re-graded resubmission updates the award instead of
        # tripping UNIQUE(user, task).
        await upsert_award(db, proof.user_id, proof.task_id, proof.id, points)
    else:
        proof = await review_proof(
            db,
            proof_id,
            decision="rejected",
            quality_factor=quality_factor,
            notes=body.notes,
            reviewer_id=admin.id,
        )

    # Nudge the participant's UI (best-effort) on verify OR reject: if they're
    # watching this chat, ScorePanel refetches its total and ProofModal
    # refreshes its submissions list, so "Awaiting review" flips to the result
    # without a reload.
    total = await user_total_score(db, proof.user_id)
    await feedback_connection_manager.push_score(proof.session_id, total)

    user = await get_user(db, proof.user_id)
    return _to_admin_out(proof, user, task)
