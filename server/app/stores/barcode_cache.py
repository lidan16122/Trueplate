"""Hot cache in front of the ``barcode_products`` table.

Lookup order is Redis -> Postgres -> Open Food Facts. Redis is an accelerator,
never the source of truth: a cache miss must always be able to fall through, and
a flushed Redis must cost latency rather than data.

Interface only for now — barcode scanning is not built yet. It exists so the
caching order has a home, and so the shape is settled before the feature lands.
"""

from redis.asyncio import Redis

from app.stores import keys
from app.stores.json_cache import JSONCache

# Weeks, not minutes: a packaged product's nutrition panel effectively never
# changes, and a stale entry is corrected by the next reformulation anyway.
DEFAULT_TTL_SECONDS = 21 * 24 * 60 * 60


class BarcodeCache(JSONCache):
    def __init__(self, redis: Redis, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        super().__init__(redis, keys.barcode_key, ttl_seconds)
