"""Pixel handling for the photo detection path.

Pure functions over bytes: no I/O, no ORM, no model calls. Kept separate from
``detection.py`` because these are the parts worth testing without an API key.
"""

import io
import logging

from PIL import Image, ImageOps

from app.config import settings

logger = logging.getLogger(__name__)

# What we send upstream regardless of what the phone produced. JPEG because a
# plate photo is a photograph — PNG would multiply the byte size for no visual
# gain, and the model sees the same pixels either way.
OUTPUT_MEDIA_TYPE = "image/jpeg"
_JPEG_QUALITY = 88

# Anything a browser will hand us from a file input or a camera capture.
ALLOWED_UPLOAD_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
)


def prepare_image(data: bytes) -> bytes:
    """Normalise an uploaded photo for the vision call.

    Three things happen here, and each is load-bearing:

    - **EXIF rotation is baked in.** Phone cameras store the sensor's raw
      orientation plus a rotation flag. Strip the flag without applying it and a
      portrait plate arrives sideways, which measurably degrades portion
      estimates for no reason a reader would ever guess from the code.
    - **Downscaled to the configured long edge.** Image tokens dominate the cost
      of a detection, and a modern phone sends several times more pixels than
      the model can use.
    - **Re-encoded as JPEG**, which also discards any remaining metadata —
      including GPS coordinates, which we have no reason to send anywhere.
    """
    with Image.open(io.BytesIO(data)) as image:
        image = ImageOps.exif_transpose(image)
        if image.mode not in ("RGB", "L"):
            # JPEG cannot hold an alpha channel; a PNG screenshot of a menu would
            # otherwise fail to encode.
            image = image.convert("RGB")

        max_edge = settings.detect_image_max_edge_px
        if max(image.size) > max_edge:
            image.thumbnail((max_edge, max_edge), Image.LANCZOS)

        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
        return buffer.getvalue()


def crop_region(data: bytes, x: float, y: float, width: float, height: float) -> bytes:
    """Crop a normalised (0-1) region and enlarge it back to a useful size.

    Coordinates are fractions of the image rather than pixels so the model never
    has to know what resolution we happened to send it.

    The upscale at the end is the point of the whole tool: a sauce occupying 8%
    of a plate is a handful of pixels once the photo is downscaled, and returning
    that crop at its native size tells the model nothing it could not already
    see. Enlarging it spends tokens to buy detail exactly where the model said it
    was uncertain.
    """
    with Image.open(io.BytesIO(data)) as image:
        image = ImageOps.exif_transpose(image)
        img_w, img_h = image.size

        # Clamp rather than reject. An out-of-range box is the model being
        # approximate, not an error worth failing a detection over.
        left = max(0, min(int(x * img_w), img_w - 1))
        top = max(0, min(int(y * img_h), img_h - 1))
        right = max(left + 1, min(int((x + width) * img_w), img_w))
        bottom = max(top + 1, min(int((y + height) * img_h), img_h))

        cropped = image.crop((left, top, right, bottom))
        if cropped.mode not in ("RGB", "L"):
            cropped = cropped.convert("RGB")

        target = settings.detect_image_max_edge_px
        if max(cropped.size) < target:
            scale = target / max(cropped.size)
            cropped = cropped.resize(
                (int(cropped.width * scale), int(cropped.height * scale)), Image.LANCZOS
            )

        buffer = io.BytesIO()
        cropped.save(buffer, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
        return buffer.getvalue()
