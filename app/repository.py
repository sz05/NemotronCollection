"""Repository/service functions (task 1.5).

Thin async wrappers around the DB session so route handlers (Phase 2-4)
don't touch SQLAlchemy directly.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ChatSession,
    ChatSubmission,
    FeedbackEntry,
    PointAward,
    ProofSubmission,
    ScoreEvent,
    Task,
    User,
)
from app.models import _utcnow


async def get_or_create_google_user(
    db: AsyncSession, google_sub: str, email: str, name: str, picture: str
) -> User:
    result = await db.execute(select(User).where(User.google_sub == google_sub))
    user = result.scalar_one_or_none()
    if user is None:
        # Same email may exist from a dev-login session; claim it.
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(google_sub=google_sub, email=email, name=name, picture=picture)
        else:
            user.google_sub = google_sub
    user.name = name or user.name
    user.picture = picture or user.picture
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def get_or_create_dev_user(db: AsyncSession, email: str) -> User:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(email=email, name=email.split("@")[0])
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


async def set_user_nemotron_key(db: AsyncSession, user: User, encrypted: str | None) -> User:
    user.nemotron_key_encrypted = encrypted
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def create_session(
    db: AsyncSession, user_id: uuid.UUID, task_id: uuid.UUID | None = None
) -> ChatSession:
    session = ChatSession(user_id=user_id, messages=[], task_id=task_id)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def list_sessions(db: AsyncSession, user_id: uuid.UUID) -> list[ChatSession]:
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == user_id)
        .order_by(ChatSession.created_at.desc())
    )
    return list(result.scalars().all())


async def user_has_session_for_task(
    db: AsyncSession, user_id: uuid.UUID, task_id: uuid.UUID
) -> bool:
    """A task/theme can be locked to at most one of a user's chats: True if
    this user already started a chat for this task."""
    result = await db.execute(
        select(ChatSession.id).where(
            ChatSession.user_id == user_id, ChatSession.task_id == task_id
        )
    )
    return result.first() is not None


async def user_total_score(db: AsyncSession, user_id: uuid.UUID) -> int:
    """The user's total = sum over their chats of that chat's BEST submission
    points (keep-highest per chat). Automatic live_score no longer contributes
    -- points come solely from pressing 'Submit chat'."""
    per_chat_best = (
        select(func.max(ChatSubmission.points).label("best"))
        .where(ChatSubmission.user_id == user_id)
        .group_by(ChatSubmission.session_id)
        .subquery()
    )
    total = (
        await db.execute(select(func.coalesce(func.sum(per_chat_best.c.best), 0)))
    ).scalar_one()
    return int(total)


async def create_chat_submission(
    db: AsyncSession,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    task_id: uuid.UUID | None,
    score: int,
    points: int,
    user_msg_count: int,
) -> ChatSubmission:
    sub = ChatSubmission(
        session_id=session_id,
        user_id=user_id,
        task_id=task_id,
        score=score,
        points=points,
        user_msg_count=user_msg_count,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return sub


async def count_session_submissions(db: AsyncSession, session_id: uuid.UUID) -> int:
    """How many times this chat has been submitted -- drives the next unlock
    threshold (each submit pushes the bar 5-8 user-messages further)."""
    return int(
        (
            await db.execute(
                select(func.count(ChatSubmission.id)).where(
                    ChatSubmission.session_id == session_id
                )
            )
        ).scalar_one()
    )


async def session_best_score(db: AsyncSession, session_id: uuid.UUID) -> int | None:
    """The highest 0-100 score submitted for this chat, or None if never submitted."""
    val = (
        await db.execute(
            select(func.max(ChatSubmission.score)).where(
                ChatSubmission.session_id == session_id
            )
        )
    ).scalar_one()
    return int(val) if val is not None else None


async def session_has_pending_proof(db: AsyncSession, session_id: uuid.UUID) -> bool:
    """True if this chat already has a proof awaiting review -- used to block a
    second submission until the first is graded or rejected."""
    result = await db.execute(
        select(ProofSubmission.id).where(
            ProofSubmission.session_id == session_id,
            ProofSubmission.status == "pending",
        )
    )
    return result.first() is not None


async def append_message(db: AsyncSession, session_id: uuid.UUID, role: str, content: str) -> ChatSession:
    session = await db.get(ChatSession, session_id)
    if session is None:
        raise ValueError(f"ChatSession {session_id} not found")

    # Reassign (rather than .append) so SQLAlchemy's change tracking on the
    # JSONB column reliably detects the mutation and includes it in the UPDATE.
    session.messages = [*session.messages, {"role": role, "content": content}]

    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def get_chat_session(db: AsyncSession, session_id: uuid.UUID) -> ChatSession | None:
    return await db.get(ChatSession, session_id)


async def append_turn(
    db: AsyncSession, session_id: uuid.UUID, user_content: str, assistant_content: str
) -> ChatSession:
    """Persist a completed user+assistant round trip atomically. Used instead
    of two append_message calls so a failed Nemotron call (see the /chat
    handler) never leaves a dangling, unanswered user turn in history --
    that malformed shape (consecutive user turns) got resent to the model on
    every retry and appeared to make it far slower/less reliable."""
    session = await db.get(ChatSession, session_id)
    if session is None:
        raise ValueError(f"ChatSession {session_id} not found")

    if not session.messages:
        # First turn names the chat for the sidebar.
        session.title = user_content[:60]

    session.messages = [
        *session.messages,
        {"role": "user", "content": user_content},
        {"role": "assistant", "content": assistant_content},
    ]

    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def save_feedback(
    db: AsyncSession,
    session_id: uuid.UUID,
    question: str,
    answer: str,
    chat_context: list[dict] | None = None,
) -> FeedbackEntry:
    entry = FeedbackEntry(
        session_id=session_id,
        question=question,
        answer=answer,
        chat_context=chat_context or [],
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


# --- Tasks ---
async def create_task(
    db: AsyncSession,
    title: str,
    description: str,
    difficulty: str,
    base_points: int,
    proof_types: list[str],
    instructions: str,
    created_by: uuid.UUID | None,
) -> Task:
    task = Task(
        title=title,
        description=description,
        difficulty=difficulty,
        base_points=base_points,
        proof_types=proof_types,
        instructions=instructions,
        created_by=created_by,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


async def list_tasks(db: AsyncSession, active_only: bool = True) -> list[Task]:
    stmt = select(Task)
    if active_only:
        stmt = stmt.where(Task.active == True)  # noqa: E712
    stmt = stmt.order_by(Task.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_task(db: AsyncSession, task_id: uuid.UUID) -> Task | None:
    return await db.get(Task, task_id)


# --- Live scoring ---
async def add_score_event(
    db: AsyncSession,
    session_id: uuid.UUID,
    turn_index: int,
    scores: dict,
    live_score: float,
) -> ScoreEvent:
    event = ScoreEvent(
        session_id=session_id,
        turn_index=turn_index,
        responsiveness=float(scores.get("responsiveness", 0.0)),
        elaboration=float(scores.get("elaboration", 0.0)),
        development=float(scores.get("development", 0.0)),
        progress=float(scores.get("progress", 0.0)),
        live_score=live_score,
        context_snapshot=scores.get("context_snapshot", []),
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


async def update_session_score(
    db: AsyncSession,
    session_id: uuid.UUID,
    summary: str,
    components: dict,
    live_score: float,
) -> ChatSession:
    session = await db.get(ChatSession, session_id)
    if session is None:
        raise ValueError(f"ChatSession {session_id} not found")
    session.context_summary = summary
    session.score_components = components
    session.live_score = live_score
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


# --- Proof submissions ---
async def create_proof(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    task_id: uuid.UUID,
    user_id: uuid.UUID,
    proof_type: str,
    storage_ref: str | None,
    url: str | None,
    sha256: str | None,
    phash: str | None,
    meta: dict,
    warning_ack_at,
) -> ProofSubmission:
    proof = ProofSubmission(
        session_id=session_id,
        task_id=task_id,
        user_id=user_id,
        proof_type=proof_type,
        storage_ref=storage_ref,
        url=url,
        sha256=sha256,
        phash=phash,
        meta=meta or {},
        warning_ack_at=warning_ack_at,
    )
    db.add(proof)
    await db.commit()
    await db.refresh(proof)
    return proof


async def get_proof(db: AsyncSession, proof_id: uuid.UUID) -> ProofSubmission | None:
    return await db.get(ProofSubmission, proof_id)


async def find_proof_by_sha(
    db: AsyncSession, task_id: uuid.UUID, sha256: str
) -> ProofSubmission | None:
    result = await db.execute(
        select(ProofSubmission).where(
            ProofSubmission.task_id == task_id, ProofSubmission.sha256 == sha256
        )
    )
    return result.scalars().first()


async def list_pending_proofs(db: AsyncSession) -> list[ProofSubmission]:
    result = await db.execute(
        select(ProofSubmission)
        .where(ProofSubmission.status == "pending")
        .order_by(ProofSubmission.created_at.asc())
    )
    return list(result.scalars().all())


async def review_proof(
    db: AsyncSession,
    proof_id: uuid.UUID,
    decision: str,
    quality_factor: float | None,
    notes: str | None,
    reviewer_id: uuid.UUID,
) -> ProofSubmission:
    proof = await db.get(ProofSubmission, proof_id)
    if proof is None:
        raise ValueError(f"ProofSubmission {proof_id} not found")
    proof.status = "verified" if decision == "verified" else "rejected"
    proof.quality_factor = quality_factor
    proof.review_notes = notes
    proof.reviewer_id = reviewer_id
    proof.reviewed_at = _utcnow()
    db.add(proof)
    await db.commit()
    await db.refresh(proof)
    return proof


# --- Proof listing (admin) ---
async def list_all_proofs(db: AsyncSession) -> list[ProofSubmission]:
    result = await db.execute(
        select(ProofSubmission).order_by(ProofSubmission.created_at.desc())
    )
    return list(result.scalars().all())


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)


# --- Points / leaderboard ---
async def get_award(
    db: AsyncSession, user_id: uuid.UUID, task_id: uuid.UUID
) -> PointAward | None:
    result = await db.execute(
        select(PointAward).where(
            PointAward.user_id == user_id, PointAward.task_id == task_id
        )
    )
    return result.scalars().first()


async def upsert_award(
    db: AsyncSession,
    user_id: uuid.UUID,
    task_id: uuid.UUID,
    proof_id: uuid.UUID,
    points: int,
) -> PointAward:
    """Award (or re-award) points for a (user, task). If the user already has
    an award for this task -- i.e. they resubmitted a better proof and it was
    re-graded -- update it in place to the latest grade instead of failing the
    UNIQUE(user, task) constraint. This is what lets a stronger PoC raise a
    participant's points."""
    award = await get_award(db, user_id, task_id)
    if award is None:
        award = PointAward(
            user_id=user_id, task_id=task_id, proof_id=proof_id, points=points
        )
    else:
        award.points = points
        award.proof_id = proof_id
    db.add(award)
    await db.commit()
    await db.refresh(award)
    return award


async def leaderboard(db: AsyncSession, limit: int = 50) -> list[dict]:
    """Rank users by total score = sum over their chats of each chat's BEST
    submission points (keep-highest per chat). `tasks_completed` here counts the
    number of chats they've scored on."""
    # Best points per (user, chat)...
    per_chat_best = (
        select(
            ChatSubmission.user_id.label("user_id"),
            ChatSubmission.session_id.label("session_id"),
            func.max(ChatSubmission.points).label("best"),
        )
        .group_by(ChatSubmission.user_id, ChatSubmission.session_id)
        .subquery()
    )
    # ...summed per user, with a count of scored chats.
    agg_stmt = (
        select(
            per_chat_best.c.user_id.label("user_id"),
            func.coalesce(func.sum(per_chat_best.c.best), 0).label("total_points"),
            func.count().label("chats_scored"),
        )
        .group_by(per_chat_best.c.user_id)
    )
    rows = (await db.execute(agg_stmt)).all()

    users = (await db.execute(select(User))).scalars().all()
    name_map = {u.id: (u.display_name or u.name or u.email) for u in users}

    entries = []
    for r in rows:
        total = int(r.total_points or 0)
        entries.append(
            {
                "user_id": r.user_id,
                "display_name": name_map.get(r.user_id, ""),
                "total_points": total,
                # Legacy schema fields kept for the response model; bonus mirrors
                # total now that submissions are the only points source.
                "chat_score": 0.0,
                "bonus_points": total,
                "tasks_completed": int(r.chats_scored or 0),
            }
        )
    entries.sort(key=lambda e: e["total_points"], reverse=True)
    return entries[:limit]
