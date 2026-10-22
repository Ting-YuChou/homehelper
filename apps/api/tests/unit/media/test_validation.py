import io

import pytest
from PIL import Image

from homehelper.media.validation import (
    MAX_IMAGE_BYTES,
    MAX_VIDEO_BYTES,
    UploadRejected,
    check_size,
    sniff,
)
from tests.unit.media.samples import heic_bytes, image_bytes, write_video


@pytest.mark.parametrize(
    ("data", "kind", "mime"),
    [
        (image_bytes("JPEG"), "image", "image/jpeg"),
        (image_bytes("PNG"), "image", "image/png"),
        (image_bytes("WEBP"), "image", "image/webp"),
        (heic_bytes(), "image", "image/heic"),
    ],
)
def test_sniff_detects_allowed_images(data: bytes, kind: str, mime: str) -> None:
    sniffed = sniff(data[:512])
    assert (sniffed.kind, sniffed.mime) == (kind, mime)


@pytest.mark.parametrize(
    ("name", "codec", "mime"),
    [
        ("a.mp4", "mpeg4", "video/mp4"),
        ("a.mov", "mpeg4", "video/quicktime"),
        ("a.webm", "libvpx", "video/webm"),
    ],
)
def test_sniff_detects_allowed_videos(tmp_path, name: str, codec: str, mime: str) -> None:
    head = write_video(tmp_path / name, codec=codec).read_bytes()[:512]
    assert sniff(head).mime == mime


def test_the_bytes_decide_not_the_file_name() -> None:
    # A PNG uploaded as "clip.mp4" is still a PNG; nothing here looks at names.
    assert sniff(image_bytes("PNG")[:512]).mime == "image/png"


@pytest.mark.parametrize(
    "data",
    [
        b"just some text pretending to be a photo",
        b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n",
        b'<svg xmlns="http://www.w3.org/2000/svg"></svg>',
        b"",
    ],
)
def test_rejects_unsupported_types(data: bytes) -> None:
    with pytest.raises(UploadRejected) as raised:
        sniff(data)
    assert raised.value.code == "unsupported_type"
    assert raised.value.status_code == 415


def test_rejects_gif() -> None:
    out = io.BytesIO()
    Image.new("RGB", (4, 4)).save(out, "GIF")
    with pytest.raises(UploadRejected, match="JPEG, PNG, WebP or HEIC"):
        sniff(out.getvalue())


@pytest.mark.parametrize(
    ("kind", "size", "ok"),
    [
        ("image", MAX_IMAGE_BYTES, True),
        ("image", MAX_IMAGE_BYTES + 1, False),
        ("video", MAX_VIDEO_BYTES, True),
        ("video", MAX_VIDEO_BYTES + 1, False),
        ("image", 0, False),
    ],
)
def test_size_limits(kind: str, size: int, ok: bool) -> None:
    if ok:
        check_size(kind, size)  # type: ignore[arg-type]
        return
    with pytest.raises(UploadRejected) as raised:
        check_size(kind, size)  # type: ignore[arg-type]
    assert raised.value.status_code in (413, 422)
