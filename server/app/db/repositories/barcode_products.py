"""Exact barcode and name lookups over products previously scanned."""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.barcode import BarcodeProduct


async def get(db: AsyncSession, upc: str) -> BarcodeProduct | None:
    return await db.get(BarcodeProduct, upc)


async def by_name(db: AsyncSession, name: str) -> BarcodeProduct | None:
    return await db.scalar(select(BarcodeProduct).where(func.lower(BarcodeProduct.name) == name))


async def add_if_absent(db: AsyncSession, row: BarcodeProduct) -> None:
    try:
        # A SAVEPOINT rather than the request's whole transaction — the
        # route commits this same session afterwards, and a bare rollback
        # would leave it committing a dead session.
        async with db.begin_nested():
            db.add(row)
    except IntegrityError:
        # Another request cached the same UPC first; theirs is the same
        # product, so there is nothing to reconcile.
        pass
