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
    frontend_origin: str = "http://localhost:5173"

    # Nemotron is an OpenAI-compatible chat completions endpoint (NVIDIA NIM /
    # build.nvidia.com). No secret here -- the key travels per-request only.
    nemotron_base_url: str = "https://integrate.api.nvidia.com/v1"
    # The nano-8B model consistently 502s (gateway timeout) -- its backend
    # appears unhealthy/deprecated. The 49B super model is confirmed working
    # end-to-end with the same key. Override via NEMOTRON_MODEL in .env.
    nemotron_model: str = "nvidia/llama-3.3-nemotron-super-49b-v1"
    # Caps generation length/latency -- see send_chat_message for why.
    nemotron_max_tokens: int = 512

    gemini_model: str = "gemini-3.5-flash-lite"


settings = Settings()
