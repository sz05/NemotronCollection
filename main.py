"""FastAPI app entrypoint (task 0.2). CORS wiring is task 0.6."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import init_db
from app.services.embeddings import warmup as warmup_embeddings
from app.routers.admin import router as admin_router
from app.routers.auth import router as auth_router
from app.routers.chat import router as chat_router
from app.routers.feedback import router as feedback_router
from app.routers.leaderboard import router as leaderboard_router
from app.routers.proof import router as proof_router
from app.routers.tasks import router as tasks_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Warm the embedding model off the request path so the first /chat doesn't
    # pay the multi-second cold start. Fire-and-forget in a thread so startup
    # (and health checks) return immediately; a request arriving mid-warmup
    # still works -- it just falls back to the lazy load once.
    warm_task = asyncio.create_task(asyncio.to_thread(warmup_embeddings))
    try:
        yield
    finally:
        warm_task.cancel()


app = FastAPI(title="Synthetic Data Collection Harness", lifespan=lifespan)

# Task 0.6: allow the frontend origins (Vite dev + deployed) to call this API
# directly (SPA, no templates).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.frontend_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(feedback_router)
app.include_router(tasks_router)
app.include_router(proof_router)
app.include_router(leaderboard_router)
app.include_router(admin_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
