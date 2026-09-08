"""Exercise the relocated log workflow through HTTP and the real SQLite adapter."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.db.models import DailyLog, FoodEntry
from app.services.auth import google_oauth
from tests.helpers import complete_onboarding, google_payload, sign_in

API = "/api/v1/logs"


def entry(**changes):
    return {
        "name": "Rice",
        "meal_type": "dinner",
        "quantity_g": 100,
        "kcal_per_100g": 130,
        "protein_g_per_100g": 3,
        "carbs_g_per_100g": 28,
        "fat_g_per_100g": 1,
        "detection_method": "photo",
        "nutrition_source": "usda_fdc",
        "source_ref": "rice-source-row",
        "detection_confidence": 0.4,
        "image_hash": "meal-photo",
        **changes,
    }


async def save(client, day, entries):
    response = await client.post(f"{API}/{day}/entries", json={"entries": entries})
    assert response.status_code == 201
    return (await client.get(f"{API}/{day}")).json()


async def test_day_groups_meals_in_order_and_scales_the_saved_nutrition(client, google_ok):
    await sign_in(client)
    onboarding = (await complete_onboarding(client)).json()
    day = datetime.now(UTC).date().isoformat()

    result = await save(
        client, day, [entry(quantity_g=200), entry(name="Breakfast rice", meal_type="breakfast")]
    )

    assert [group["meal_type"] for group in result["groups"]] == ["breakfast", "dinner"]
    assert [group["calories"] for group in result["groups"]] == [130, 260]
    assert result["totals"] == {"calories": 390, "protein_g": 9, "carbs_g": 84, "fat_g": 3}
    assert result["target_calories"] == onboarding["targets"]["target_calories"]


async def test_portion_correction_preserves_the_source_snapshot_and_confirms_the_entry(
    client, google_ok, db_session
):
    await sign_in(client)
    day = datetime.now(UTC).date().isoformat()
    result = await save(client, day, [entry()])
    entry_id = result["groups"][0]["entries"][0]["id"]

    response = await client.patch(
        f"{API}/entries/{entry_id}", json={"quantity_g": 250, "meal_type": "lunch"}
    )

    assert response.status_code == 200
    assert response.json()["calories"] == 325
    assert response.json()["detection_confidence"] == 1
    assert response.json()["is_rough"] is False
    row = await db_session.get(FoodEntry, uuid.UUID(entry_id))
    assert (row.kcal_per_100g, row.protein_g_per_100g, row.source_ref) == (
        130,
        3,
        "rice-source-row",
    )
    assert row.meal_type == "lunch"

    assert (await client.delete(f"{API}/entries/{entry_id}")).status_code == 204
    assert (await client.get(f"{API}/{day}")).json()["groups"] == []


async def test_another_users_entry_is_hidden_from_reads_updates_and_deletes(
    client, google_ok, db_session, monkeypatch
):
    await sign_in(client)
    day = datetime.now(UTC).date().isoformat()
    saved = await save(client, day, [entry()])
    entry_id = saved["groups"][0]["entries"][0]["id"]
    monkeypatch.setattr(
        google_oauth,
        "_verify_sync",
        lambda credential: google_payload(sub="another-subject", email="bob@example.com"),
    )
    await sign_in(client)

    assert (await client.get(f"{API}/{day}")).json()["groups"] == []
    changed = await client.patch(f"{API}/entries/{entry_id}", json={"quantity_g": 1})
    deleted = await client.delete(f"{API}/entries/{entry_id}")
    assert changed.status_code == deleted.status_code == 404
    assert changed.json() == deleted.json() == {"detail": "Entry not found"}
    original = await db_session.get(FoodEntry, uuid.UUID(entry_id))
    assert original.quantity_g == 100


async def test_future_logging_is_refused_and_day_ranges_include_empty_days(
    client, google_ok, db_session
):
    await sign_in(client)
    today = datetime.now(UTC).date()
    tomorrow = today + timedelta(days=1)
    response = await client.post(f"{API}/{tomorrow}/entries", json={"entries": [entry()]})
    assert response.status_code == 400
    assert response.json() == {"detail": "Cannot log food in the future"}
    assert await db_session.scalar(select(func.count()).select_from(DailyLog)) == 0

    yesterday = today - timedelta(days=1)
    await save(client, yesterday.isoformat(), [entry()])
    days = (await client.get(f"{API}?days=3&end={today}")).json()
    assert [day["log_date"] for day in days] == [
        (today - timedelta(days=offset)).isoformat() for offset in [2, 1, 0]
    ]
    assert [day["calories"] for day in days] == [0, 130, 0]
    assert [day["has_entries"] for day in days] == [False, True, False]
