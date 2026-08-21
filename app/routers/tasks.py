"""Task routes: challenge definitions users complete for points. Any
authenticated user may create a task (created_by tracks authorship) and list
active tasks; individual fetch is public to logged-in users."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import get_current_user, require_admin
from app.models import User
from app.repository import create_task, get_task, list_tasks
from app.schemas import TaskCreate, TaskOut

router = APIRouter()


def _to_out(task) -> TaskOut:
    return TaskOut(
        id=task.id,
        title=task.title,
        description=task.description,
        difficulty=task.difficulty,
        base_points=task.base_points,
        proof_types=task.proof_types,
        instructions=task.instructions,
        active=task.active,
    )


@router.post("/tasks", response_model=TaskOut)
async def create_task_route(
    body: TaskCreate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> TaskOut:
    task = await create_task(
        db,
        title=body.title,
        description=body.description,
        difficulty=body.difficulty,
        base_points=body.base_points,
        proof_types=body.proof_types,
        instructions=body.instructions,
        created_by=user.id,
    )
    return _to_out(task)


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks_route(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[TaskOut]:
    tasks = await list_tasks(db, active_only=True)
    return [_to_out(t) for t in tasks]


@router.get("/tasks/{task_id}", response_model=TaskOut)
async def get_task_route(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> TaskOut:
    task = await get_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return _to_out(task)
