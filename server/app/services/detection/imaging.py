"""Blocking pixel operations for the detection worker thread, with no external I/O."""

import io
import logging

from PIL import Image, ImageOps

from app.config import settings

logger = logging.getLogger(__name__)

# JPEG keeps photo requests small; metadata is deliberately omitted when encoding.
OUTPUT_MEDIA_TYPE = "image/jpeg"
PREPROCESSING_VERSION = "original-crops-v1"

ALLOWED_UPLOAD_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
)


def _encode(image: Image.Image, max_edge: int) -> bytes:
    """Bound visual tokens without enlarging pixels or retaining camera metadata."""
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=settings.detect_image_jpeg_quality, optimize=True)
    return buffer.getvalue()


def image_stats(data: bytes) -> dict[str, int]:
    """Describe encoded pixels without logging image content or invoking the model.

    Visual tokens are a patch estimate before provider resizing, excluding request overhead.
    """
    with Image.open(io.BytesIO(data)) as image:
        width, height = image.size
    return {
        "width": width,
        "height": height,
        "bytes": len(data),
        "visual_tokens": ((width + 27) // 28) * ((height + 27) // 28),
    }


def prepare_image(data: bytes) -> bytes:
    """Prepare an oriented overview; the original upload remains available for crops."""
    with Image.open(io.BytesIO(data)) as source:
        image = ImageOps.exif_transpose(source)
        original_size = image.size
        prepared = _encode(image, settings.detect_image_max_edge_px)
    logger.info(
        "photo preparation: original=%sx%s bytes=%d prepared=%s quality=%d",
        *original_size,
        len(data),
        image_stats(prepared),
        settings.detect_image_jpeg_quality,
    )
    return prepared


def crop_region(data: bytes, x: float, y: float, width: float, height: float) -> bytes:
    """Crop the oriented original using the overview's normalized coordinates.

    Encoding directly from original pixels preserves detail that overview resizing discards.
    """
    with Image.open(io.BytesIO(data)) as source:
        image = ImageOps.exif_transpose(source)
        img_w, img_h = image.size

        # Approximate boxes are clamped to a nonempty region inside the original.
        left = max(0, min(int(x * img_w), img_w - 1))
        top = max(0, min(int(y * img_h), img_h - 1))
        right = max(left + 1, min(int((x + width) * img_w), img_w))
        bottom = max(top + 1, min(int((y + height) * img_h), img_h))
        cropped = _encode(
            image.crop((left, top, right, bottom)), settings.detect_image_crop_max_edge_px
        )
    logger.info("photo crop: %s", image_stats(cropped))
    return cropped
