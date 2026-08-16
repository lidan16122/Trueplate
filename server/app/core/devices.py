"""Turning a User-Agent string into a device label.

Split out of ``security.py``, whose subject is minting and verifying access
tokens. Parsing UA strings is a presentation concern that changes for entirely
unrelated reasons — a new browser, a new phone — and had no business sharing a
file with the signing code.
"""


def describe_device(user_agent: str) -> str:
    """A human label for the sessions list.

    Crude on purpose: this is a hint to help someone recognise their own device
    in a list, not analytics. Full UA string is stored alongside it.
    """
    ua = user_agent or ""
    lowered = ua.lower()

    if "iphone" in lowered:
        platform = "iPhone"
    elif "ipad" in lowered:
        platform = "iPad"
    elif "android" in lowered:
        platform = "Android"
    elif "mac os" in lowered or "macintosh" in lowered:
        platform = "Mac"
    elif "windows" in lowered:
        platform = "Windows"
    elif "linux" in lowered:
        platform = "Linux"
    else:
        return "Unknown device"

    for name, marker in (
        ("Edge", "edg/"),
        ("Chrome", "chrome/"),
        ("Firefox", "firefox/"),
        ("Safari", "safari/"),
    ):
        if marker in lowered:
            # Chrome and Edge both claim Safari; the ordering above resolves it.
            return f"{name} on {platform}"

    return platform
