from fastapi import APIRouter

# Versioned application routes. Mounted under settings.api_v1_prefix.
# Feature routers (auth, onboarding, logs, ai) are added as they land.
api_router = APIRouter()

# Health deliberately does not live here: probes should not have to track an API
# version, so `app.main` mounts `routes.health.router` at the root directly.
