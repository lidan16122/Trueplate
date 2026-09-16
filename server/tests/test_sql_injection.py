"""SQL-looking values stay data through real repository queries and HTTP writes."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import event, func, select

from app.db.models import AuthIdentity, BarcodeProduct, Food, FoodEntry, User
from app.db.repositories import barcode_products, foods, users
from app.models.enums import AuthProvider
from app.schemas.detection import NutritionMatch
from tests.helpers import sign_in

PAYLOADS = [
    "' OR 1=1 --",
    "rice'; DROP TABLE foods; --",
    "' UNION SELECT * FROM users --",
    "%_",
    "o'brien's rice",
]


@pytest.mark.parametrize("value", PAYLOADS)
async def test_food_names_are_bound_values_on_reads_inserts_and_updates(db_session, value):
    match = NutritionMatch(
        name="rice",
        source="manual",
        kcal_per_100g=130,
        protein_g_per_100g=3,
        carbs_g_per_100g=28,
        fat_g_per_100g=1,
    )
    now = datetime.now(UTC)
    original = await foods.upsert(db_session, "rice", match, now)
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append((statement, parameters))

    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        assert await foods.by_name(db_session, value.lower()) == []
        saved = await foods.upsert(db_session, value, match, now)
        changed = match.model_copy(update={"kcal_per_100g": 140})
        assert (await foods.upsert(db_session, value, changed, now)).id == saved.id
        assert [row.id for row in await foods.by_name(db_session, value.lower())] == [saved.id]
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert all(value not in sql for sql, _ in statements)
    assert any(value in parameters for _, parameters in statements)
    assert original.kcal_per_100g == 130
    assert await db_session.scalar(select(func.count()).select_from(Food)) == 2


@pytest.mark.parametrize("value", PAYLOADS)
async def test_sql_text_cannot_match_another_users_identity_or_a_product(db_session, value):
    user = User(email="alice@example.com")
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        AuthIdentity(
            user_id=user.id, provider=AuthProvider.GOOGLE, provider_user_id="alice-google-subject"
        )
    )
    product = BarcodeProduct(
        upc="12345678",
        name="rice",
        kcal_per_100g=130,
        protein_g_per_100g=3,
        carbs_g_per_100g=28,
        fat_g_per_100g=1,
    )
    await barcode_products.add_if_absent(db_session, product)

    assert await users.email_owner(db_session, value) is None
    assert await users.other_email_owner(db_session, value, user.id) is None
    assert await users.google_identity(db_session, value) is None
    assert await barcode_products.by_name(db_session, value) is None
    assert await barcode_products.get(db_session, value) is None
    assert await users.email_owner(db_session, user.email) == user.id
    assert await barcode_products.get(db_session, product.upc) is product


async def test_a_sql_payload_in_a_logged_name_is_stored_literally(client, google_ok, db_session):
    await sign_in(client)
    name = "rice'); DROP TABLE users; --"
    day = datetime.now(UTC).date().isoformat()
    response = await client.post(
        f"/api/v1/logs/{day}/entries",
        json={
            "entries": [
                {
                    "name": name,
                    "meal_type": "dinner",
                    "quantity_g": 100,
                    "kcal_per_100g": 130,
                    "detection_method": "manual",
                    "nutrition_source": "manual",
                }
            ]
        },
    )

    assert response.status_code == 201
    assert (await db_session.scalar(select(FoodEntry))).name == name
    assert await db_session.scalar(select(func.count()).select_from(User)) == 1
