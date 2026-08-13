"""Every Redis key this app writes, in one place.

Centralised so the namespace is auditable at a glance — you can see what is
stored, and just as importantly that user profiles, goals, and day totals are
*not*. Those are cheap Postgres queries; caching them would add an invalidation
problem in exchange for nothing.
"""

# --- auth: refresh-token rotation ---
REFRESH_TOKEN = "rt:tok:{token_hash}"  # HASH  active token -> user_id, family_id
REFRESH_USED = "rt:used:{token_hash}"  # HASH  tombstone -> family_id, rotated_at
REFRESH_FAMILY = "rt:family:{family_id}"  # HASH one device/session's metadata
REFRESH_USER_FAMILIES = "rt:user:{user_id}"  # SET  family ids, powers session list

# --- auth: optional instant access-token revocation ---
ACCESS_DENY = "at:deny:{jti}"

# --- rate limiting ---
# Sorted set of request timestamps inside the sliding window.
RATE_LIMIT = "rl:{scope}:{subject}"

# --- barcode hot cache, in front of the barcode_products table ---
BARCODE = "barcode:{upc}"

# --- AI food-detection results, keyed by image content ---
AI_DETECTION = "ai:detect:{image_hash}"

# Prefixes handed to Lua, which derives dependent keys from values it reads
# (a family id is only known after loading the token hash).
REFRESH_TOKEN_PREFIX = "rt:tok:"
REFRESH_FAMILY_PREFIX = "rt:family:"
REFRESH_USER_PREFIX = "rt:user:"


def refresh_token_key(token_hash: str) -> str:
    return REFRESH_TOKEN.format(token_hash=token_hash)


def refresh_used_key(token_hash: str) -> str:
    return REFRESH_USED.format(token_hash=token_hash)


def refresh_family_key(family_id: str) -> str:
    return REFRESH_FAMILY.format(family_id=family_id)


def refresh_user_families_key(user_id: str) -> str:
    return REFRESH_USER_FAMILIES.format(user_id=user_id)


def access_deny_key(jti: str) -> str:
    return ACCESS_DENY.format(jti=jti)


def rate_limit_key(scope: str, subject: str) -> str:
    return RATE_LIMIT.format(scope=scope, subject=subject)



def barcode_key(upc: str) -> str:
    return BARCODE.format(upc=upc)


def ai_detection_key(image_hash: str) -> str:
    return AI_DETECTION.format(image_hash=image_hash)
