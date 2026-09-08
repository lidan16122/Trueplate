import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import transaction
from app.db.models import FoodEntry, User
from app.db.repositories import logs as repository
from app.db.repositories.goals import active_goal
from app.models.enums import meal_sort_key
from app.schemas.log import (
    CreateEntriesRequest,
    DayLogOut,
    DaySummary,
    FoodEntryOut,
    MealGroupOut,
    NutritionFacts,
    UpdateEntryRequest,
    confidence_view,
)
from app.services.errors import InvalidOperationError, NotFoundError


def _entry_out(entry: FoodEntry) -> FoodEntryOut:
    confidence = confidence_view(entry.detection_confidence)
    return FoodEntryOut(
        id=entry.id,
        name=entry.name,
        brand=entry.brand,
        meal_type=entry.meal_type,
        quantity_g=entry.quantity_g,
        serving_description=entry.serving_description,
        calories=entry.calories,
        protein_g=entry.protein_g,
        carbs_g=entry.carbs_g,
        fat_g=entry.fat_g,
        detection_method=entry.detection_method,
        nutrition_source=entry.nutrition_source,
        detection_confidence=entry.detection_confidence,
        confidence_label=confidence.label,
        is_rough=confidence.is_rough,
    )


def _totals(entries: list[FoodEntry]) -> NutritionFacts:
    return NutritionFacts(
        calories=sum(e.calories for e in entries),
        protein_g=sum(e.protein_g for e in entries),
        carbs_g=sum(e.carbs_g for e in entries),
        fat_g=sum(e.fat_g for e in entries),
    )


async def _assemble_day(db, user_id: uuid.UUID, log_date: date) -> DayLogOut:
    """Build the day view.

    A plain function rather than the route handler, because two routes need it
    — reading a day, and returning the day after adding to it. Calling one
    handler from another ties them together through FastAPI's signature, so the
    dependencies of one become the caller's problem.
    """
    log = await repository.read_log(db, user_id, log_date)
    entries = list(log.entries) if log else []

    buckets: dict[str, list[FoodEntry]] = {}
    for entry in entries:
        buckets.setdefault(entry.meal_type, []).append(entry)

    groups = [
        MealGroupOut(
            meal_type=meal,
            calories=sum(e.calories for e in items),
            entries=[_entry_out(e) for e in items],
        )
        for meal, items in sorted(buckets.items(), key=lambda kv: meal_sort_key(kv[0]))
    ]

    goal = await active_goal(db, user_id)

    return DayLogOut(
        log_date=log_date,
        groups=groups,
        totals=_totals(entries),
        target_calories=goal.target_calories if goal else None,
        target_protein_g=goal.target_protein_g if goal else None,
        target_carbs_g=goal.target_carbs_g if goal else None,
        target_fat_g=goal.target_fat_g if goal else None,
    )


async def read_day(log_date: date, user: User, db: AsyncSession) -> DayLogOut:
    """One day, grouped into meals in the design's fixed order."""
    return await _assemble_day(db, user.id, log_date)


async def read_day_range(
    user: User,
    db: AsyncSession,
    days: int = 14,
    end: date | None = None,
) -> list[DaySummary]:
    """Totals per day, for the date strip's has-entries dots."""
    end_date = end or datetime.now(UTC).date()
    start_date = end_date - timedelta(days=days - 1)

    logs = await repository.read_range(db, user.id, start_date, end_date)
    by_date = {log.log_date: log for log in logs}

    summaries = []
    for offset in range(days):
        day = start_date + timedelta(days=offset)
        log = by_date.get(day)
        entries = list(log.entries) if log else []
        summaries.append(
            DaySummary(
                log_date=day,
                calories=sum(e.calories for e in entries),
                has_entries=bool(entries),
            )
        )
    return summaries


async def add_entries(
    log_date: date, payload: CreateEntriesRequest, user: User, db: AsyncSession
) -> DayLogOut:
    """Save a confirmed proposal into the day.

    The whole basket lands in one request because that is how the confirm screen
    works — the user reviews every item, then commits once.
    """
    if log_date > datetime.now(UTC).date():
        raise InvalidOperationError("Cannot log food in the future")

    log = await repository.get_or_create_log(db, user.id, log_date)
    now = datetime.now(UTC)

    await repository.add_entries(db, log.id, payload.entries, now)

    await transaction.commit(db)
    return await _assemble_day(db, user.id, log_date)


async def update_entry(
    entry_id: uuid.UUID, payload: UpdateEntryRequest, user: User, db: AsyncSession
) -> FoodEntryOut:
    entry = await _owned_entry(db, entry_id, user.id)

    entry.quantity_g = payload.quantity_g
    if payload.meal_type is not None:
        entry.meal_type = payload.meal_type

    # A user correcting the portion is the strongest confirmation available,
    # so the estimate stops being flagged as a guess.
    if entry.detection_confidence is not None:
        entry.detection_confidence = 1.0

    await transaction.commit(db)
    await transaction.refresh(db, entry)
    return _entry_out(entry)


async def delete_entry(entry_id: uuid.UUID, user: User, db: AsyncSession) -> None:
    entry = await _owned_entry(db, entry_id, user.id)
    await repository.delete_entry(db, entry)
    await transaction.commit(db)


async def _owned_entry(db, entry_id: uuid.UUID, user_id: uuid.UUID) -> FoodEntry:
    """Fetch an entry, refusing to reveal whether someone else's exists.

    The join through daily_logs is the authorisation check: without it, any
    entry id would be editable by any signed-in user.
    """
    entry = await repository.owned_entry(db, entry_id, user_id)
    if entry is None:
        raise NotFoundError("Entry not found")
    return entry
