import io

import pytest
from PIL import Image

from homehelper.media.images import MAX_EDGE, MAX_PIXELS, normalize_image
from homehelper.media.validation import UploadRejected
from tests.unit.media.samples import GPS_IFD, heic_bytes, image_bytes


def _open(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def test_strips_exif_including_gps() -> None:
    original = image_bytes("JPEG", gps=True)
    assert _open(original).getexif().get_ifd(GPS_IFD)  # the fixture really has GPS
    result = normalize_image(original, "image/jpeg")
    assert len(_open(result.data).getexif()) == 0
    assert b"Exif" not in result.data
    assert (result.mime, result.ext) == ("image/jpeg", "jpg")


def test_orientation_is_applied_before_the_metadata_goes() -> None:
    # Orientation 6 = rotate 90° clockwise to display: a 64x48 sensor image is shown 48x64.
    result = normalize_image(image_bytes("JPEG", (64, 48), orientation=6), "image/jpeg")
    assert (result.width, result.height) == (48, 64)
    assert _open(result.data).size == (48, 64)


def test_heic_becomes_jpeg() -> None:
    result = normalize_image(heic_bytes(), "image/heic")
    assert (result.mime, result.ext) == ("image/jpeg", "jpg")
    assert _open(result.data).format == "JPEG"


@pytest.mark.parametrize(
    ("fmt", "mime", "ext"), [("PNG", "image/png", "png"), ("WEBP", "image/webp", "webp")]
)
def test_png_and_webp_keep_their_format(fmt: str, mime: str, ext: str) -> None:
    result = normalize_image(image_bytes(fmt, gps=True), mime)
    assert (result.mime, result.ext) == (mime, ext)
    assert _open(result.data).format == fmt
    assert len(_open(result.data).getexif()) == 0


def test_long_edge_is_downscaled() -> None:
    result = normalize_image(image_bytes("PNG", (MAX_EDGE * 2, 100)), "image/png")
    assert (result.width, result.height) == (MAX_EDGE, 50)


def test_small_images_are_not_upscaled() -> None:
    result = normalize_image(image_bytes("PNG", (30, 20)), "image/png")
    assert (result.width, result.height) == (30, 20)


def test_rejects_decompression_bombs() -> None:
    # A tiny PNG that claims a huge canvas: refused before its pixels are decoded.
    side = int(MAX_PIXELS**0.5) + 10
    out = io.BytesIO()
    Image.new("1", (side, side)).save(out, "PNG")
    with pytest.raises(UploadRejected) as raised:
        normalize_image(out.getvalue(), "image/png")
    assert raised.value.code == "too_large"


def test_rejects_corrupt_images() -> None:
    data = image_bytes("JPEG", (64, 48))
    with pytest.raises(UploadRejected) as raised:
        normalize_image(data[: len(data) // 3], "image/jpeg")
    assert raised.value.code == "unreadable"


def test_jpeg_comments_are_dropped_too() -> None:
    out = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(out, "JPEG", comment=b"Shot at 221B Baker St by alice")
    result = normalize_image(out.getvalue(), "image/jpeg")
    assert b"Baker" not in result.data
    assert "comment" not in _open(result.data).info
