"""Photo normalisation (spec §11.1): every image is decoded and re-encoded, so no metadata survives.

Re-encoding without `exif=` drops EXIF, GPS included; the orientation is applied to the pixels
first so the photo still displays upright. HEIC becomes JPEG, which the models and browsers read.
"""

import io
import warnings
from dataclasses import dataclass

import pi_heif
from PIL import Image, ImageOps

from homehelper.media.validation import UploadRejected

pi_heif.register_heif_opener()

MAX_EDGE = 1568  # longest side sent to vision models; larger only costs tokens
MAX_PIXELS = 50_000_000  # claimed canvas size above which we refuse (decompression bombs)
JPEG_QUALITY = 88
# Everything in `info` that describes the photo rather than its pixels (`transparency` stays).
METADATA_KEYS = ("exif", "comment", "icc_profile", "xmp", "XML:com.adobe.xmp", "dpi", "photoshop")

_OUTPUT = {
    "image/jpeg": ("JPEG", "image/jpeg", "jpg"),
    "image/heic": ("JPEG", "image/jpeg", "jpg"),
    "image/png": ("PNG", "image/png", "png"),
    "image/webp": ("WEBP", "image/webp", "webp"),
}


@dataclass(frozen=True)
class ProcessedImage:
    data: bytes
    mime: str
    ext: str
    width: int
    height: int


def _unreadable() -> UploadRejected:
    return UploadRejected("unreadable", "We couldn't read that photo. Try another one.", 422)


def normalize_image(data: bytes, mime: str) -> ProcessedImage:
    fmt, out_mime, ext = _OUTPUT[mime]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as probe:
                width, height = probe.size
                if width * height > MAX_PIXELS:
                    raise UploadRejected("too_large", "That photo is too large.", 413)
                probe.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                upright = ImageOps.exif_transpose(image)
    except UploadRejected:
        raise
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Warning) as exc:
        raise _unreadable() from exc

    upright.thumbnail((MAX_EDGE, MAX_EDGE))
    if fmt == "JPEG" and upright.mode != "RGB":
        upright = upright.convert("RGB")
    for key in METADATA_KEYS:  # they ride in `info` and would be saved again
        upright.info.pop(key, None)
    out = io.BytesIO()
    options = {"quality": JPEG_QUALITY} if fmt in ("JPEG", "WEBP") else {}
    upright.save(out, fmt, **options)  # no exif=, icc_profile=, pnginfo=: nothing is carried over
    return ProcessedImage(out.getvalue(), out_mime, ext, upright.width, upright.height)
