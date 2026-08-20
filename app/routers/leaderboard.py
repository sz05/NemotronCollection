"""Leaderboard route: ranks users by total score (chat live_score + bonus
points from verified task proofs), with the caller's own rank surfaced
separately (.me) so the frontend can highlight it even when the caller is off
the visible page."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import get_current_user
from app.models import User
from app.repository import leaderboard
from app.schemas import LeaderboardEntryOut, LeaderboardOut

router = APIRouter()


@router.get("/leaderboard", response_model=LeaderboardOut)
async def get_leaderboard(
    limit: int = Query(50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> LeaderboardOut:
    rows = await leaderboard(db, limit=limit)

    entries: list[LeaderboardEntryOut] = []
    for rank, row in enumerate(rows, start=1):
        entries.append(
            LeaderboardEntryOut(
                rank=rank,
                user_id=row["user_id"],
                display_name=row["display_name"],
                total_points=row["total_points"],
                chat_score=row["chat_score"],
                bonus_points=row["bonus_points"],
                tasks_completed=row["tasks_completed"],
            )
        )

    me = next((e for e in entries if e.user_id == user.id), None)
    return LeaderboardOut(entries=entries, me=me)
