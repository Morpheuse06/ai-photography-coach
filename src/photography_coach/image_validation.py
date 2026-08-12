"""Safe, framework-independent validation for uploaded photos."""

from dataclasses import dataclass
from io import BytesIO
import warnings

from PIL import Image, UnidentifiedImageError


MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000

SUPPORTED_FORMATS = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}


class ImageValidationError(ValueError):
    """Raised when uploaded bytes do not satisfy the photo requirements."""


class ImageTooLargeError(ImageValidationError):
    """Raised when uploaded bytes exceed the configured request limit."""


@dataclass(frozen=True, slots=True)
class ValidatedImage:
    """Trusted metadata obtained from the decoded image, not its filename."""

    format: str
    media_type: str
    width: int
    height: int
    size_bytes: int


def validate_image(
    data: bytes,
    declared_content_type: str | None = None,
    *,
    max_bytes: int = MAX_IMAGE_BYTES,
    max_pixels: int = MAX_IMAGE_PIXELS,
) -> ValidatedImage:
    """Validate photo bytes and return metadata derived from their real content."""
    if not data:
        raise ImageValidationError("The image file is empty.")
    if len(data) > max_bytes:
        raise ImageTooLargeError(f"The image exceeds the {max_bytes}-byte size limit.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)

            with Image.open(BytesIO(data)) as image:
                image_format = image.format or ""
                if image_format not in SUPPORTED_FORMATS:
                    raise ImageValidationError("Only JPEG, PNG, and WebP images are supported.")

                expected_content_type = SUPPORTED_FORMATS[image_format]
                normalized_content_type = _normalize_content_type(declared_content_type)
                if normalized_content_type and normalized_content_type != expected_content_type:
                    raise ImageValidationError(
                        "The declared content type does not match the image content."
                    )

                if getattr(image, "is_animated", False):
                    raise ImageValidationError("Animated images are not supported.")

                width, height = image.size
                if width <= 0 or height <= 0 or width * height > max_pixels:
                    raise ImageValidationError(
                        f"The image exceeds the {max_pixels}-pixel resolution limit."
                    )

                image.verify()
    except ImageValidationError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
    ) as exc:
        raise ImageValidationError("The file is not a valid, complete image.") from exc

    return ValidatedImage(
        format=image_format,
        media_type=expected_content_type,
        width=width,
        height=height,
        size_bytes=len(data),
    )


def _normalize_content_type(content_type: str | None) -> str | None:
    """Normalize an optional HTTP media type before comparing it."""
    if content_type is None:
        return None
    return content_type.split(";", maxsplit=1)[0].strip().lower()
