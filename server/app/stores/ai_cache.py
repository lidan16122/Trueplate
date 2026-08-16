"""Cache for AI food-detection results, keyed by image content.

Re-logging the same meal — a photo retried after a dropped connection, the same
packaged breakfast every morning — should not spend another vision call. The key
is a hash of the image bytes, so identical input hits regardless of filename,
upload time, or which user sent it.

Interface only for now; the Claude call is not wired yet.
"""

import hashlib

from redis.asyncio import Redis

from app.stores import keys
from app.stores.json_cache import JSONCache

# Long enough to cover repeat meals, short enough that a change in the detection
# prompt or model works its way out without a manual flush.
DEFAULT_TTL_SECONDS = 30 * 24 * 60 * 60


def hash_image(data: bytes) -> str:
    """Content address for an image.

    Content-based rather than per-user: the same photo yields the same foods
    whoever uploaded it, and sharing the entry across users is the whole saving.
    Nothing user-identifying is stored under the key — only the detected foods.
    """
    return hashlib.sha256(data).hexdigest()


class AIDetectionCache(JSONCache):
    def __init__(self, redis: Redis, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        super().__init__(redis, keys.ai_detection_key, ttl_seconds)
