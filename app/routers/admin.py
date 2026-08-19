"""Admin proof-review routes: a reviewer sees the pending queue and either
verifies a proof (awarding points in the same commit) or rejects it.

Point award formula (on verify):
    award = round(task.base_points * difficulty_weight * quality_factor)
where difficulty_weight comes from settings.difficulty_weights keyed by the
task's difficulty (fallback 1.0) and quality_factor is the reviewer's 0..1
judgement of proof quality (defaults to 1.0 when omitted).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.deps import get_current_user
from app.models import User
from app.repository import (
    award_points,
    get_proof,
    get_task,
    list_pending_proofs,
    review_proof,
)
from app.schemas import AdminProofOut, ReviewRequest

router = APIRouter()


def _to_admin_out(proof) -> AdminProofOut:
    return AdminProofOut(
        id=proof.id,
        session_id=proof.session_id,
        task_id=proof.task_id,
        user_id=proof.user_id,
        proof_type=proof.proof_type,
        storage_ref=proof.storage_ref,
        url=proof.url,
        status=proof.status,
        sha256=proof.sha256,
        phash=proof.phash,
        meta=proof.meta,
        created_at=proof.created_at,
    )


@router.get("/admin/proofs", response_model=list[AdminProofOut])
async def list_pending(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[AdminProofOut]:
    proofs = await list_pending_proofs(db)
    return [_to_admin_out(p) for p in proofs]


@router.post("/admin/proofs/{proof_id}/review", response_model=AdminProofOut)
async def review(
    proof_id: uuid.UUID,
    body: ReviewRequest,
    user: User = Depends(get_current_user),
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
    if proof.status != "pending":
        raise HTTPException(
            status_code=409, detail=f"Proof already {proof.status}"
        )

    quality_factor = body.quality_factor if body.quality_factor is not None else 1.0

    if decision == "verified":
        task = await get_task(db, proof.task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task for this proof not found")

        weight = settings.difficulty_weights.get(task.difficulty, 1.0)
        points = round(task.base_points * weight * quality_factor)

        proof = await review_proof(
            db,
            proof_id,
            decision="verified",
            quality_factor=quality_factor,
            notes=body.notes,
            reviewer_id=user.id,
        )
        try:
            # Same commit as the review so a verified proof can never exist
            # without its award (and the UNIQUE(user,task) guards double-awards).
            await award_points(db, proof.user_id, proof.task_id, proof.id, points)
        except IntegrityError as exc:
            await db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Points already awarded to this user for this task",
            ) from exc
    else:
        proof = await review_proof(
            db,
            proof_id,
            decision="rejected",
            quality_factor=quality_factor,
            notes=body.notes,
            reviewer_id=user.id,
        )

    return _to_admin_out(proof)
