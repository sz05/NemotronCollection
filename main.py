"""FastAPI app entrypoint (task 0.2). CORS wiring is task 0.6."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import init_db
from app.routers.auth import router as auth_router
from app.routers.chat import router as chat_router
from app.routers.feedback import router as feedback_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Synthetic Data Collection Harness", lifespan=lifespan)

# Task 0.6: allow the Vite dev origin to call this API directly (SPA, no templates).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(feedback_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
