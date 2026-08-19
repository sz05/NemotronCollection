"""Seed a demo Task so the guardrail can be exercised end-to-end.

Idempotent: if a task with the same title already exists it is left as-is.
Run: PYTHONPATH=. python scripts/seed_task.py
"""

import asyncio

from sqlalchemy import select

from app.db import async_session_factory, init_db
from app.models import Task

TITLE = "Build a FastAPI to-do API"
DESCRIPTION = (
    "Build a REST API in Python with FastAPI that lets users register, log in, "
    "and manage a personal to-do list stored in a Postgres database. Cover "
    "authentication, the data model, CRUD endpoints, and validation."
)


async def main() -> None:
    await init_db()
    async with async_session_factory() as db:
        existing = (
            await db.execute(select(Task).where(Task.title == TITLE))
        ).scalars().first()
        if existing is not None:
            print(f"task already exists: {existing.id}")
            return
        task = Task(
            title=TITLE,
            description=DESCRIPTION,
            difficulty="medium",
            base_points=100,
            proof_types=["image", "url", "file"],
            instructions="Submit a screenshot or a link to the running API / repo.",
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        print(f"seeded task: {task.id}")


if __name__ == "__main__":
    asyncio.run(main())
