"""What an upload may be (spec §11.1). The file's own bytes decide its type, never its name."""

from dataclasses import dataclass
from typing import Literal

import filetype

MediaKind = Literal["image", "video"]

IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/heic": "heic"}
VIDEO_TYPES = {"video/mp4": "mp4", "video/quicktime": "mov", "video/webm": "webm"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
# Cloud Run caps an HTTP/1 request at 32 MiB, multipart wrapper included (ADR-011).
MAX_VIDEO_BYTES = 30 * 1024 * 1024
MAX_VIDEO_SECONDS = 60
SNIFF_BYTES = 512  # enough for every signature above (filetype reads at most 262 bytes)

UNSUPPORTED = "Send a photo (JPEG, PNG, WebP or HEIC) or a video (MP4, MOV or WebM)."


class UploadRejected(Exception):
    """An upload we refuse; `code` and `status_code` go to the client as they are."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class Sniffed:
    kind: MediaKind
    mime: str


def sniff(head: bytes) -> Sniffed:
    guess = filetype.guess(head) if head else None
    mime = guess.mime if guess else None
    if mime in IMAGE_TYPES:
        return Sniffed("image", mime)
    if mime in VIDEO_TYPES:
        return Sniffed("video", mime)
    raise UploadRejected("unsupported_type", UNSUPPORTED, 415)


def check_size(kind: MediaKind, size: int) -> None:
    if size <= 0:
        raise UploadRejected("empty", "The file is empty.", 422)
    limit = MAX_IMAGE_BYTES if kind == "image" else MAX_VIDEO_BYTES
    if size > limit:
        noun = "Photos" if kind == "image" else "Videos"
        raise UploadRejected("too_large", f"{noun} can be up to {limit // 2**20} MB.", 413)
