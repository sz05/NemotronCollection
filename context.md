# Project: Synthetic Data Collection Harness (V1)

## System Context & V1 Scope Boundaries

You are building V1 of a data collection harness designed to capture high-quality human-LLM interactions to challenge synthetic benchmarks.

**IMPORTANT: Do NOT implement features outside of the V1 scope (e.g., OAuth, leaderboards, word-count limiters, or scoring heuristics) unless explicitly instructed.**

V1 is strictly limited to the following five components:

1. **API Key Ingestion**: A UI prompt/modal that accepts and holds the user's Nvidia Nemotron API key in the active session.
2. **Chat Harness**: The main chat interface where user messages are routed to the Nemotron API using the user's provided key.
3. **Chat Persistence**: Save all chat sessions, user prompts, and Nemotron responses to the database.
4. **Gemini Side-Panel**: A distinct UI panel that passes the ongoing chat context to a Gemini model to generate dynamic, context-aware feedback questions.
5. **Feedback Persistence**: Capture and save the user's answers to these Gemini-generated questions into the database linked to the specific session.

## Architecture & Tech Stack

- **Backend**: FastAPI (Python 3.10+).
- **Database**: PostgreSQL (using Asyncpg / SQLAlchemy or SQLModel).
- **LLM Integrations**:
  - _Nemotron_: Called via the user-provided API key from the frontend/session.
  - _Gemini_: Called via a server-side API key (managed via environment variables / `.env`).

## Development Rules & Conventions

- **Database Storage**: Use PostgreSQL `JSONB` columns to store the conversational message arrays (`[{"role": "user", "content": "..."}, ...]`) to keep chat logs simple and efficient.
- **Asynchronous Operations**: Use `async`/`await` for all DB operations and external API requests (e.g., `httpx` for async HTTP calls) to ensure high concurrency and prevent blocking the main event loop.
- **Security**: NEVER log or permanently store the user's Nemotron API key. Pass it securely per active session request.
- **Performance**: Decouple the Gemini feedback call from the Nemotron response flow. Feedback generation must run asynchronously without delaying the active chat stream.

## Commands

- **Environment Setup**: `python -m venv venv && source venv/bin/activate && pip install -r requirements.txt`
- **Run Server**: `uvicorn main:app --reload`
- **Testing**: `pytest`
