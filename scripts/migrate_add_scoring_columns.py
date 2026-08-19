"""One-off, idempotent column migration for the new task-scoring feature.

SQLModel's create_all creates brand-new tables (task, score_event,
proof_submission, point_award) but never ALTERs existing ones, so the columns
added to chat_session / app_user must be added explicitly. Uses
ADD COLUMN IF NOT EXISTS so it's safe to re-run and non-destructive.
"""

import asyncio

from sqlalchemy import text

from app.db import engine, init_db

ALTERS = [
    "ALTER TABLE chat_session ADD COLUMN IF NOT EXISTS task_id UUID",
    "ALTER TABLE chat_session ADD COLUMN IF NOT EXISTS context_summary TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE chat_session ADD COLUMN IF NOT EXISTS live_score DOUBLE PRECISION NOT NULL DEFAULT 0",
    "ALTER TABLE chat_session ADD COLUMN IF NOT EXISTS score_components JSONB NOT NULL DEFAULT '{}'",
    "ALTER TABLE app_user ADD COLUMN IF NOT EXISTS display_name TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE app_user ADD COLUMN IF NOT EXISTS disqualified BOOLEAN NOT NULL DEFAULT false",
]


async def main() -> None:
    # create_all first: makes the four brand-new tables.
    await init_db()
    async with engine.begin() as conn:
        for stmt in ALTERS:
            await conn.execute(text(stmt))
    print("migration OK")


if __name__ == "__main__":
    asyncio.run(main())
