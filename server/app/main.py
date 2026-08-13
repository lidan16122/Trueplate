import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router, health_router
from app.config import settings
from app.db.session import engine
from app.stores.client import close_redis_pool

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    logger.info("%s API starting", settings.app_name)
    yield
    # Connections are pooled for the process lifetime; tear both down on the way
    # out so reloads and container stops do not leak sockets.
    await engine.dispose()
    await close_redis_pool()
    logger.info("%s API stopped", settings.app_name)


def create_app() -> FastAPI:
    app = FastAPI(
        title=f"{settings.app_name} API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Credentials must be allowed for the httpOnly cookie auth to work
    # cross-origin, and that forbids a wildcard origin — hence the explicit list.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
