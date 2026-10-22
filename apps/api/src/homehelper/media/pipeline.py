"""One upload, start to finish: sniff the real type, check the limits, strip metadata (spec §11.1).

Blocking (Pillow, FFmpeg); the API runs it in a worker thread.
"""

from dataclasses import dataclass
from pathlib import Path

from homehelper.media.images import normalize_image
from homehelper.media.validation import SNIFF_BYTES, MediaKind, check_size, sniff
from homehelper.media.video import VideoProbe, process_video


@dataclass(frozen=True)
class PreparedUpload:
    kind: MediaKind
    mime: str
    ext: str
    path: Path  # the cleaned file, inside the caller's work directory
    size: int
    width: int | None
    height: int | None
    duration_s: float | None = None


def prepare_upload(
    source: Path, work_dir: Path, *, probe: VideoProbe | None = None
) -> PreparedUpload:
    """Raises `UploadRejected` for anything we don't accept."""
    with source.open("rb") as file:
        sniffed = sniff(file.read(SNIFF_BYTES))
    check_size(sniffed.kind, source.stat().st_size)
    if sniffed.kind == "image":
        image = normalize_image(source.read_bytes(), sniffed.mime)
        out = work_dir / f"clean.{image.ext}"
        out.write_bytes(image.data)
        return PreparedUpload(
            "image", image.mime, image.ext, out, len(image.data), image.width, image.height
        )
    video = process_video(source, sniffed.mime, work_dir / "clean.video", probe=probe)
    return PreparedUpload(
        "video",
        video.mime,
        video.ext,
        video.path,
        video.path.stat().st_size,
        video.width,
        video.height,
        round(video.duration_s, 2),
    )
