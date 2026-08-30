from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
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
    # Bounds a statement that hangs *after* connecting, which the connect
    # timeout cannot see. Generous enough for a cold managed instance.
    db_statement_timeout_seconds: int = 10
    redis_timeout_seconds: int = 2
    health_check_timeout_seconds: float = 3.0

    # ---------- Auth ----------
    # Deliberately has no default, and a length floor rather than a bare `str`.
    # The signature is the access token's entire security, so a deploy that
    # forgets this var must fail to boot rather than sign real tokens with a
    # value published in this repo. `str` alone is not enough: an empty
    # `JWT_SECRET_KEY=` in a compose file or CI secret satisfies it.
    jwt_secret_key: str = Field(min_length=32)
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
    # Carries the CSRF state and the PKCE verifier for one in-flight sign-in.
    # Named here beside the other two so the whole cookie vocabulary reads from
    # one place, which is what lets the tests assert on names rather than
    # literals.
    oauth_state_cookie_name: str = "tp_oauth"
    cookie_secure: bool = True
    cookie_samesite: str = "lax"
    # Scoping the refresh cookie to the auth router keeps it off every other
    # request, so a token with 30-day life is not sprayed across the whole API.
    refresh_cookie_path: str = "/api/v1/auth"

    # Nice-to-have instant revocation. Off by default: the hot path verifies the
    # access token by signature alone and never touches Redis.
    access_denylist_enabled: bool = False

    google_client_id: str = ""

    # Empty default, deliberately unlike `jwt_secret_key` above. The reasoning
    # that makes a missing signing key fatal does not transfer: a missing secret
    # here cannot make us issue a weak credential, it can only fail an exchange
    # Google would have refused anyway. A deploy that has not set this yet must
    # still boot and keep serving everyone holding a live session — only signing
    # in is broken, and it breaks with a message on the sign-in screen rather
    # than a process that will not start.
    google_client_secret: str = ""

    # The *app's* origin, never the API's, and never derived from the incoming
    # request. Two independent reasons it cannot be derived: Google matches this
    # string against the Console entry exactly, and neither proxy in front of
    # this app preserves the browser's Host — `changeOrigin: true` in
    # vite.config.ts rewrites it to localhost:8000, and `new Request(target,
    # request)` in client/worker/index.ts rewrites it to the API's. A
    # request-derived value would name the API's origin and strand the
    # SameSite=Lax auth cookies on a host the browser is not on.
    google_redirect_uri: str = ""

    # Google's token endpoint sits on the sign-in path, and httpx defaults to no
    # timeout at all — a slow Google would pin a worker open and present as this
    # app being down.
    google_timeout_seconds: float = 10.0

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

    # ---------- AI food detection ----------
    # No default, and absent from .env.example as a real value: a missing key
    # surfaces as a clean 503 from the detect routes rather than an opaque 401
    # from the SDK.
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5"

    # Caps thinking *and* response text together on Opus 5, where thinking is on
    # by default. Sized with headroom: too tight and a reply truncates mid-tool-call.
    anthropic_max_tokens: int = 8000
    # The main cost lever per photo. `low` and `medium` are unusually strong on
    # this model, so `low` is worth trying before any prompt work — raising
    # effort is cheaper to try than re-engineering the prompt, and cheaper to
    # undo. `medium` is the starting point because it is the setting the
    # pipeline was actually measured at, not because low was ruled out.
    anthropic_effort: str = "medium"
    # Vision plus a tool loop is slow; the SDK's 10-minute default is far longer
    # than we ever want to hold a request open.
    anthropic_timeout_seconds: float = 120.0

    detect_image_max_bytes: int = 8 * 1024 * 1024
    # Opus 5 accepts up to 2576 px on the long edge, but a full-resolution image
    # costs roughly 3x the tokens of one this size. Downsampling is the single
    # biggest lever on per-photo cost, so it starts conservative — raise it only
    # against a measured portion-accuracy gain, not on principle.
    detect_image_max_edge_px: int = 1568

    # Web search identifies *what a food is*; it never sources a number. Scoped
    # to known-provenance references so an SEO recipe blog can never influence a
    # match. See services/nutrition/resolver.py for why the numbers still come
    # from the database either way.
    web_search_max_uses: int = 3
    web_search_allowed_domains: Annotated[list[str], NoDecode] = [
        "fdc.nal.usda.gov",
        "world.openfoodfacts.org",
        "en.wikipedia.org",
    ]

    # ---------- Nutrition sources ----------
    usda_fdc_api_key: str = ""
    usda_fdc_base_url: str = "https://api.nal.usda.gov/fdc/v1"
    open_food_facts_base_url: str = "https://world.openfoodfacts.org"
    # Open Food Facts publishes no hard rate limit but asks clients to identify
    # themselves. An anonymous scraper is what gets blocked.
    open_food_facts_user_agent: str = "Trueplate/0.1 (https://github.com/lidan16122/Trueplate)"
    nutrition_timeout_seconds: float = 10.0

    # A wrong row written back is served to every future lookup, so a rough
    # third-rung match is left to re-resolve next time rather than frozen.
    #
    # Deliberately equal to SURE_THRESHOLD rather than derived from it: the two
    # answer different questions — that one is "warn this user", this one is
    # "serve every future user" — and they should be free to move apart. Lower
    # it to cache more aggressively, raise it if a bad row ever reaches `foods`.
    foods_writeback_min_confidence: float = 0.75
    # Upstream revises figures. Past this age a row is re-fetched on read
    # instead of being trusted indefinitely.
    foods_ttl_days: int = 30

    # Cached detections expire too. Without this a photo answered once is
    # answered the same way forever, so an improvement to the prompt or a model
    # upgrade would never reach anyone who had already logged that meal.
    detections_ttl_days: int = 30

    @field_validator("web_search_allowed_domains", mode="before")
    @classmethod
    def _split_domains(cls, v: object) -> object:
        if isinstance(v, str):
            stripped = v.strip()
            if stripped.startswith("["):
                return v
            return [d.strip() for d in stripped.split(",") if d.strip()]
        return v

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


# Resolved once, at import. This is deliberately a plain module-level singleton
# and not a cached accessor: the engine and the Redis pool are both built from it
# at import time too, so a "swap the settings" seam would be a lie — nothing
# downstream could observe the swap without reloading the modules.
settings = Settings()
