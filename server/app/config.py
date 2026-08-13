from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# app/config.py -> app -> server -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"


class Settings(BaseSettings):
    """Application configuration.

    Resolved from the repo-root ``.env`` via an absolute path, so the app behaves
    identically whether it is launched from ``server/``, the repo root, or a
    process manager with an unrelated working directory.
    """

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- Core ----------
    app_name: str = "Trueplate"
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"

    # ---------- Datastores ----------
    database_url: str = "postgresql+psycopg://trueplate:trueplate@localhost:5432/trueplate"
    redis_url: str = "redis://localhost:6379/0"
    db_echo: bool = False

    # Fail fast when a datastore is unreachable. The defaults for both clients
    # are long enough that a down dependency looks like a hang rather than an
    # outage, which is far harder to diagnose.
    db_connect_timeout_seconds: int = 3
    redis_timeout_seconds: int = 2
    health_check_timeout_seconds: float = 3.0

    # ---------- Auth ----------
    jwt_secret_key: str = "dev-only-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30

    # Replaying a just-rotated refresh token within this window is treated as a
    # client retry (a flaky network, two tabs racing) rather than theft.
    # Without it, one genuine concurrent refresh revokes the whole session.
    # Costs an attacker nothing they could not already do inside the same few
    # seconds; the next mismatched rotation still catches them.
    refresh_reuse_grace_seconds: int = 15

    access_cookie_name: str = "tp_access"
    refresh_cookie_name: str = "tp_refresh"
    cookie_secure: bool = True
    cookie_samesite: str = "lax"
    # Scoping the refresh cookie to the auth router keeps it off every other
    # request, so a token with 30-day life is not sprayed across the whole API.
    refresh_cookie_path: str = "/api/v1/auth"

    # Nice-to-have instant revocation. Off by default: the hot path verifies the
    # access token by signature alone and never touches Redis.
    access_denylist_enabled: bool = False

    google_client_id: str = ""

    # ---------- CORS ----------
    # Only consulted cross-origin. The Vite dev proxy makes the browser treat the
    # API as same-origin, so this is unused in local development.
    #
    # NoDecode suppresses pydantic-settings' automatic JSON decode of complex
    # types, which otherwise runs before the validator below and rejects a plain
    # comma-separated string.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    # ---------- Rate limits ----------
    ai_detect_rate_limit: int = 20
    ai_detect_rate_window_seconds: int = 3600

    # ---------- External services (not wired yet) ----------
    anthropic_api_key: str = ""
    usda_fdc_api_key: str = ""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        # Accept both a JSON list and a plain comma-separated string, so the
        # .env stays readable.
        if isinstance(v, str):
            stripped = v.strip()
            if stripped.startswith("["):
                return v
            return [o.strip() for o in stripped.split(",") if o.strip()]
        return v

    @property
    def access_token_ttl_seconds(self) -> int:
        return self.access_token_ttl_minutes * 60

    @property
    def refresh_token_ttl_seconds(self) -> int:
        return self.refresh_token_ttl_days * 24 * 60 * 60


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
