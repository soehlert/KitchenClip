import base64
import io
from typing import BinaryIO

from django.core.exceptions import ValidationError
from PIL import Image, ImageOps, UnidentifiedImageError

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # pragma: no cover
    pass

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB
MAX_IMAGE_DIMENSION = 1200
WEBP_QUALITY = 80


def process_uploaded_recipe_image(
    uploaded_file: BinaryIO,
    max_dimension: int = MAX_IMAGE_DIMENSION,
    quality: int = WEBP_QUALITY,
) -> str:
    """Validate, auto-orient, resize, and compress an uploaded image into a WebP data URI."""
    file_size = getattr(uploaded_file, "size", None)
    if file_size is not None and file_size > MAX_UPLOAD_BYTES:
        raise ValidationError("Image file is too large (maximum 20 MB).")

    try:
        uploaded_file.seek(0)
        raw_bytes = uploaded_file.read(MAX_UPLOAD_BYTES + 1)
    except Exception as exc:
        raise ValidationError("Could not read uploaded image file.") from exc

    if len(raw_bytes) > MAX_UPLOAD_BYTES:
        raise ValidationError("Image file is too large (maximum 20 MB).")
    if not raw_bytes:
        raise ValidationError("Uploaded image file is empty.")

    try:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            # Apply phone camera EXIF orientation before stripping metadata
            oriented = ImageOps.exif_transpose(img) or img

            # Flatten alpha channel onto white background so transparent PNGs render cleanly
            if oriented.mode in ("RGBA", "LA") or (
                oriented.mode == "P" and "transparency" in oriented.info
            ):
                rgba = oriented.convert("RGBA")
                background = Image.new("RGB", rgba.size, (255, 255, 255))
                background.paste(rgba, mask=rgba.split()[3])
                rgb_img = background
            elif oriented.mode != "RGB":
                rgb_img = oriented.convert("RGB")
            else:
                rgb_img = oriented.copy()

            rgb_img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

            output_buffer = io.BytesIO()
            rgb_img.save(output_buffer, format="WEBP", quality=quality, method=4)
            webp_bytes = output_buffer.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise ValidationError("Upload a valid image file (JPEG, PNG, WebP, or HEIC).") from exc

    encoded = base64.b64encode(webp_bytes).decode("ascii")
    return f"data:image/webp;base64,{encoded}"
