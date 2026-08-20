"""Repository/service functions (task 1.5).

Thin async wrappers around the DB session so route handlers (Phase 2-4)
don't touch SQLAlchemy directly.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ChatSession,
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


async def user_total_score(db: AsyncSession, user_id: uuid.UUID) -> float:
    """Sum of the cumulative live_score across all of the user's chats -- the
    total shown on screen while they chat."""
    result = await db.execute(
        select(func.coalesce(func.sum(ChatSession.live_score), 0.0)).where(
            ChatSession.user_id == user_id
        )
    )
    return float(result.scalar_one())


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


# --- Points / leaderboard ---
async def award_points(
    db: AsyncSession,
    user_id: uuid.UUID,
    task_id: uuid.UUID,
    proof_id: uuid.UUID,
    points: int,
) -> PointAward:
    award = PointAward(
        user_id=user_id, task_id=task_id, proof_id=proof_id, points=points
    )
    db.add(award)
    await db.commit()
    await db.refresh(award)
    return award


async def leaderboard(db: AsyncSession, limit: int = 50) -> list[dict]:
    """Rank users by total score = summed chat live_score across their chats
    PLUS bonus points awarded for verified task proofs. Everyone with any chat
    activity appears (not just award-holders); completing + getting a task
    verified adds bonus points that push them higher."""
    # Chat score per user: sum of the cumulative live_score across their chats.
    chat_stmt = (
        select(
            ChatSession.user_id.label("user_id"),
            func.coalesce(func.sum(ChatSession.live_score), 0.0).label("chat_score"),
        )
        .group_by(ChatSession.user_id)
    )
    chat_map = {r.user_id: float(r.chat_score) for r in (await db.execute(chat_stmt)).all()}

    # Bonus points + tasks completed per user from verified proofs (PointAward).
    points_stmt = (
        select(
            PointAward.user_id.label("user_id"),
            func.coalesce(func.sum(PointAward.points), 0).label("bonus_points"),
            func.count(PointAward.task_id).label("tasks_completed"),
        )
        .group_by(PointAward.user_id)
    )
    points_map = {
        r.user_id: (int(r.bonus_points), int(r.tasks_completed))
        for r in (await db.execute(points_stmt)).all()
    }

    # Display names.
    users = (await db.execute(select(User))).scalars().all()
    name_map = {u.id: (u.display_name or u.name or u.email) for u in users}

    # Everyone with chat activity or awarded points is on the board.
    user_ids = set(chat_map) | set(points_map)
    entries = []
    for uid in user_ids:
        chat_score = chat_map.get(uid, 0.0)
        bonus_points, tasks_completed = points_map.get(uid, (0, 0))
        entries.append(
            {
                "user_id": uid,
                "display_name": name_map.get(uid, ""),
                # Total is the ranking key: rounded chat score + bonus points.
                "total_points": round(chat_score) + bonus_points,
                "chat_score": round(chat_score, 1),
                "bonus_points": bonus_points,
                "tasks_completed": tasks_completed,
            }
        )
    # Rank by total, then bonus (verified tasks break ties upward).
    entries.sort(key=lambda e: (e["total_points"], e["bonus_points"]), reverse=True)
    return entries[:limit]
