"""Settings loader (task 0.4).

Reads configuration from environment variables / .env. Deliberately has no
field for a Nemotron API key -- that value is supplied per-request by the
client and must never live in server-side settings.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/harness"
    gemini_api_key: str = ""
    # Comma-separated list of allowed CORS origins (no trailing slashes).
    frontend_origin: str = "http://localhost:5173,https://nemotron-collection.vercel.app,   "

    @property
    def frontend_origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.frontend_origin.split(",") if o.strip()]

    # Nemotron is an OpenAI-compatible chat completions endpoint (NVIDIA NIM /
    # build.nvidia.com). No secret here -- the key travels per-request only.
    nemotron_base_url: str = "https://integrate.api.nvidia.com/v1"
    # Nemotron 3 Super: 120B MoE (12B active), up to 1M-token context, reasoning
    # on by default -- the model actually in use. If NVIDIA returns a
    # model-not-found error, try the early-access id
    # "private/nvidia/nemotron-3-super-120b-a12b". Override via NEMOTRON_MODEL.
    # (History: nano-8B 502s; llama-4-maverick hit EOL 2026-07-27 -> 410 Gone;
    # llama-3.3-nemotron-super-49b-v1.5 also worked end-to-end.)
    nemotron_model: str = "nvidia/nemotron-3-super-120b-a12b"
    # Caps generation length/latency. This is a *reasoning* model: its output
    # budget must cover the (often long) chain-of-thought AND the final answer.
    # At 512 the thinking alone exhausted the budget (finish_reason=length), so
    # replies were truncated mid-thought and the raw reasoning trace leaked out
    # as the "reply". Full "code the app file by file" turns easily need several
    # thousand tokens on top of the thinking, so 8192. Raised together with the
    # HTTP timeout in nemotron.py -- more tokens means more wall-time. Tune via
    # NEMOTRON_MAX_TOKENS (the provider's own output cap is the hard ceiling).
    nemotron_max_tokens: int = 8192

    gemini_model: str = "gemini-3.5-flash-lite"

    # --- Auth (Google OAuth + JWT cookie) ---
    # OAuth 2.0 Web client ID from Google Cloud Console. Login button is
    # hidden on the frontend until this is set.
    google_client_id: str = ""
    # Signs the session JWT. MUST be a long, random value in .env for anything
    # non-local -- generate with: python -c "import secrets; print(secrets.token_urlsafe(48))"
    jwt_secret: str = "dev-only-secret-change-me-before-deploying"
    jwt_expiry_days: int = 7
    # Separate secret used ONLY to encrypt stored Nemotron API keys (key
    # separation: a leaked signing secret must not also decrypt stored keys).
    # Falls back to jwt_secret when empty so existing local setups keep working;
    # set a distinct random value in .env for anything non-local. Generate with:
    #   python -c "import secrets; print(secrets.token_urlsafe(48))"
    # NOTE: changing this invalidates already-stored keys (users re-enter them).
    api_key_enc_secret: str = ""
    # Dev-only email login (no password) for local testing without a Google
    # client ID. Never enable in production.
    dev_auth: bool = False
    # "lax" works when frontend and backend share a site (localhost dev).
    # Set to "none" when the frontend is on a different domain (e.g. Vercel
    # frontend + Railway backend) — browsers drop Lax cookies on cross-site
    # requests. "none" forces Secure=True, so the backend must be on HTTPS.
    cookie_samesite: str = "lax"
    # Comma-separated emails granted admin rights (proof review + point awards,
    # task creation). Everyone else is a normal participant. Set in .env.
    admin_emails: str = ""

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}

    # --- Semantic relevance + live scoring ---
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    relevance_threshold: float = 0.10
    score_interval_turns: int = 4
    window_user_turns: int = 4
    window_llm_turns: int = 4
    difficulty_weights: dict = {"easy": 1.0, "medium": 1.5, "hard": 2.0}

    # --- Proof submission storage ---
    proof_upload_dir: str = "uploads"
    # 15 MB: comfortably covers screenshots and PDF decks (the file proof kinds
    # for these tasks); larger artifacts (repos, live sites) go via a URL.
    proof_max_bytes: int = 15_000_000


settings = Settings()
