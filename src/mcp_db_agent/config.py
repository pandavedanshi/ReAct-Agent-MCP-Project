"""Runtime configuration, read once from the environment / .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # --- Database ---
    database_path: Path = Path(os.getenv("DATABASE_PATH", ROOT / "data" / "university.db"))
    max_rows: int = _int_env("MAX_ROWS", 200)           # cap on rows returned to the model
    query_timeout_ms: int = _int_env("QUERY_TIMEOUT_MS", 5_000)

    # --- Gemini ---
    # Deliberately read from the environment only; the key is never passed
    # through the MCP layer, and the MCP server never reads it.
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
    max_agent_steps: int = _int_env("MAX_AGENT_STEPS", 10)
    # The free tier allows only a few requests per minute and one ReAct loop
    # spends several, so retrying a 429 is normal operation, not an edge case.
    max_retries: int = _int_env("MAX_RETRIES", 4)
    # Client-side pacing, in requests per minute. 0 means "derive from the
    # model family" (Flash 5, Flash-Lite 15). Set a number to override, e.g.
    # on a paid key with a higher allowance.
    gemini_rpm: int = _int_env("GEMINI_RPM", 0)
    # Tried in order when the current model's per-day allowance runs out. Each
    # model has a separate daily quota, so this keeps a demo alive rather than
    # failing at the worst moment. Set to an empty string to disable.
    gemini_fallback_models: tuple = tuple(
        m.strip() for m in os.getenv(
            "GEMINI_FALLBACK_MODELS",
            "gemini-3.7-flash,gemini-3.5-flash,"
            "gemini-3.1-flash-lite,gemini-3.5-flash-lite",
        ).split(",") if m.strip()
    )

    # --- MCP transport ---
    # "stdio" launches server.py as a subprocess and speaks real MCP over pipes.
    # "memory" wires the client straight to the server object - same protocol
    # objects, no process boundary, which makes tests fast.
    mcp_transport: str = os.getenv("MCP_TRANSPORT", "stdio")

    # --- API ---
    api_host: str = os.getenv("API_HOST", "127.0.0.1")
    api_port: int = _int_env("API_PORT", 8000)
    cors_origins: tuple = tuple(
        o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()
    )

    @property
    def has_gemini_key(self) -> bool:
        return bool(self.gemini_api_key)


settings = Settings()
