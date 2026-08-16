"""Model package.

Every model is re-exported here so a single ``import app.db.models`` populates
``Base.metadata`` — which is what Alembic autogenerate reads. A model that is
not reachable from this module is silently invisible to migrations.
"""

from app.db.base import Base
from app.db.models.barcode import BarcodeProduct
from app.db.models.food import Food
from app.db.models.goal import Goal
from app.db.models.log import DailyLog, FoodEntry
from app.db.models.profile import UserProfile, WeightEntry
from app.db.models.user import AuthIdentity, User

__all__ = [
    "AuthIdentity",
    "BarcodeProduct",
    "Base",
    "DailyLog",
    "Food",
    "FoodEntry",
    "Goal",
    "User",
    "UserProfile",
    "WeightEntry",
]
