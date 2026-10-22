"""Small media files built in tests: images with EXIF/GPS, HEIC, and short videos."""

import io
from fractions import Fraction
from pathlib import Path

import av
import pillow_heif
from PIL import Image

GPS_IFD = 0x8825
MAKE = 0x010F
ORIENTATION = 0x0112


def image_bytes(
    fmt: str = "JPEG",
    size: tuple[int, int] = (64, 48),
    *,
    gps: bool = False,
    orientation: int | None = None,
    color: str = "red",
) -> bytes:
    image = Image.new("RGB", size, color)
    exif = Image.Exif()
    if gps:
        exif[MAKE] = "TestCam"
        exif.get_ifd(GPS_IFD).update({1: "N", 2: (37.0, 46.0, 30.0), 3: "W", 4: (122.0, 25.0, 9.0)})
    if orientation is not None:
        exif[ORIENTATION] = orientation
    out = io.BytesIO()
    kwargs = {"exif": exif.tobytes()} if len(exif) else {}
    image.save(out, fmt, **kwargs)
    return out.getvalue()


def heic_bytes(size: tuple[int, int] = (64, 48)) -> bytes:
    heif = pillow_heif.from_pillow(Image.new("RGB", size, "blue"))
    out = io.BytesIO()
    heif.save(out, quality=50)
    return out.getvalue()


def write_video(
    path: Path,
    *,
    seconds: float = 1.0,
    fps: int = 10,
    fmt: str | None = None,
    codec: str = "mpeg4",
    metadata: dict[str, str] | None = None,
    start_s: float = 0.0,
) -> Path:
    with av.open(str(path), mode="w", format=fmt) as container:
        if metadata:
            container.metadata.update(metadata)
        stream = container.add_stream(codec, rate=fps)
        assert isinstance(stream, av.VideoStream)
        stream.width, stream.height, stream.pix_fmt = 64, 48, "yuv420p"
        stream.time_base = Fraction(1, fps)
        for i in range(round(seconds * fps)):
            frame = av.VideoFrame.from_image(Image.new("RGB", (64, 48), (i * 20 % 255, 0, 0)))
            frame.pts = i + round(start_s * fps)
            frame.time_base = Fraction(1, fps)
            container.mux(stream.encode(frame))
        container.mux(stream.encode(None))
    return path
