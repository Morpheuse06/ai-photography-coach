"""Tests for image content and resource-limit validation."""

from io import BytesIO
import unittest

from PIL import Image

from photography_coach.image_validation import ImageValidationError, validate_image


def _make_image(image_format: str, size: tuple[int, int] = (12, 8)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color=(40, 100, 160)).save(buffer, format=image_format)
    return buffer.getvalue()


def _make_animated_webp() -> bytes:
    buffer = BytesIO()
    frames = [
        Image.new("RGB", (12, 8), color=(40, 100, 160)),
        Image.new("RGB", (12, 8), color=(160, 100, 40)),
    ]
    frames[0].save(
        buffer,
        format="WEBP",
        save_all=True,
        append_images=frames[1:],
        duration=100,
        loop=0,
    )
    return buffer.getvalue()


class ImageValidationTests(unittest.TestCase):
    def test_accepts_supported_image_formats(self) -> None:
        content_types = {
            "JPEG": "image/jpeg",
            "PNG": "image/png",
            "WEBP": "image/webp",
        }

        for image_format, content_type in content_types.items():
            with self.subTest(image_format=image_format):
                data = _make_image(image_format)

                result = validate_image(data, content_type)

                self.assertEqual(result.format, image_format)
                self.assertEqual(result.media_type, content_type)
                self.assertEqual((result.width, result.height), (12, 8))
                self.assertEqual(result.size_bytes, len(data))

    def test_rejects_empty_content(self) -> None:
        with self.assertRaisesRegex(ImageValidationError, "empty"):
            validate_image(b"", "image/jpeg")

    def test_rejects_non_image_content(self) -> None:
        with self.assertRaisesRegex(ImageValidationError, "valid, complete image"):
            validate_image(b"This is not a photo.", "image/jpeg")

    def test_rejects_an_unsupported_image_format(self) -> None:
        gif_data = _make_image("GIF")

        with self.assertRaisesRegex(ImageValidationError, "Only JPEG, PNG, and WebP"):
            validate_image(gif_data, "image/gif")

    def test_rejects_animated_webp(self) -> None:
        with self.assertRaisesRegex(ImageValidationError, "Animated"):
            validate_image(_make_animated_webp(), "image/webp")

    def test_rejects_a_mismatched_content_type(self) -> None:
        png_data = _make_image("PNG")

        with self.assertRaisesRegex(ImageValidationError, "does not match"):
            validate_image(png_data, "image/jpeg")

    def test_rejects_content_over_the_byte_limit(self) -> None:
        jpeg_data = _make_image("JPEG")

        with self.assertRaisesRegex(ImageValidationError, "size limit"):
            validate_image(jpeg_data, "image/jpeg", max_bytes=len(jpeg_data) - 1)

    def test_rejects_images_over_the_pixel_limit(self) -> None:
        png_data = _make_image("PNG", size=(20, 20))

        with self.assertRaisesRegex(ImageValidationError, "resolution limit"):
            validate_image(png_data, "image/png", max_pixels=399)


if __name__ == "__main__":
    unittest.main()
