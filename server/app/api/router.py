from fastapi import APIRouter

from app.api.routes import ai, auth, logs, onboarding

# Versioned application routes. Mounted under settings.api_v1_prefix.
api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(onboarding.router)
api_router.include_router(logs.router)
api_router.include_router(ai.router)

# Health deliberately does not live here: probes should not have to track an API
# version, so `app.main` mounts `routes.health.router` at the root directly.
