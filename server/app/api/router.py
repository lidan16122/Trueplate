from fastapi import APIRouter

from app.api.routes import health

# Versioned application routes. Mounted under settings.api_v1_prefix.
# Feature routers (auth, onboarding, logs, ai) are added as they land.
api_router = APIRouter()

# Health lives at the root, not under /api/v1 — probes should not have to track
# an API version.
health_router = health.router
