"""Translate application failures once, preserving the existing public responses."""

from fastapi import HTTPException, status

from app.services.errors import InvalidOperationError, NotFoundError


def translate_service_error(exc: InvalidOperationError | NotFoundError) -> HTTPException:
    code = (
        status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
    )
    return HTTPException(status_code=code, detail=str(exc))
