import uuid
from datetime import date

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession
from app.api.errors import translate_service_error
from app.schemas.log import (
    CreateEntriesRequest,
    DayLogOut,
    DaySummary,
    FoodEntryOut,
    UpdateEntryRequest,
)
from app.services import logs as log_service
from app.services.errors import InvalidOperationError, NotFoundError

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("/{log_date}", response_model=DayLogOut)
async def read_day(log_date: date, user: CurrentUser, db: DbSession) -> DayLogOut:
    """One day, grouped into meals in the design's fixed order."""
    try:
        return await log_service.read_day(log_date, user, db)
    except (InvalidOperationError, NotFoundError) as exc:
        raise translate_service_error(exc) from exc


@router.get("", response_model=list[DaySummary])
async def read_day_range(
    user: CurrentUser,
    db: DbSession,
    days: int = Query(default=14, ge=1, le=90),
    end: date | None = None,
) -> list[DaySummary]:
    """Totals per day, for the date strip's has-entries dots."""
    try:
        return await log_service.read_day_range(user, db, days, end)
    except (InvalidOperationError, NotFoundError) as exc:
        raise translate_service_error(exc) from exc


@router.post("/{log_date}/entries", response_model=DayLogOut, status_code=status.HTTP_201_CREATED)
async def add_entries(
    log_date: date, payload: CreateEntriesRequest, user: CurrentUser, db: DbSession
) -> DayLogOut:
    """Save a confirmed proposal into the day.

    The whole basket lands in one request because that is how the confirm screen
    works — the user reviews every item, then commits once.
    """
    try:
        return await log_service.add_entries(log_date, payload, user, db)
    except (InvalidOperationError, NotFoundError) as exc:
        raise translate_service_error(exc) from exc


@router.patch("/entries/{entry_id}", response_model=FoodEntryOut)
async def update_entry(
    entry_id: uuid.UUID, payload: UpdateEntryRequest, user: CurrentUser, db: DbSession
) -> FoodEntryOut:
    try:
        return await log_service.update_entry(entry_id, payload, user, db)
    except (InvalidOperationError, NotFoundError) as exc:
        raise translate_service_error(exc) from exc


@router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(entry_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    try:
        return await log_service.delete_entry(entry_id, user, db)
    except (InvalidOperationError, NotFoundError) as exc:
        raise translate_service_error(exc) from exc
