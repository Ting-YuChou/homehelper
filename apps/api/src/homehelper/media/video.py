"""Video checks and metadata stripping (spec §11.1), with PyAV (its wheels bundle FFmpeg).

Videos are remuxed, not re-encoded: the streams are copied into a fresh container without the
original's tags. Phones store where a clip was filmed in those tags (`location`,
`com.apple.quicktime.location.ISO6709`), so this is the video counterpart of stripping EXIF.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import av
from av.container import InputContainer
from av.error import FFmpegError

from homehelper.media.validation import MAX_VIDEO_SECONDS, VIDEO_TYPES, UploadRejected

LENGTH_SLACK_S = 0.5  # rounding between the header's duration and packet timestamps
_FORMATS = {"video/mp4": "mp4", "video/quicktime": "mov", "video/webm": "webm"}


@dataclass(frozen=True)
class VideoInfo:
    duration_s: float
    width: int
    height: int


@dataclass(frozen=True)
class ProcessedVideo:
    path: Path
    mime: str
    ext: str
    duration_s: float
    width: int
    height: int


class VideoProbe(Protocol):
    def probe(self, path: Path) -> VideoInfo: ...


class PyAVProbe:
    def probe(self, path: Path) -> VideoInfo:
        with av.open(str(path)) as container:
            stream = container.streams.video[0]
            duration = (
                container.duration / av.time_base
                if container.duration
                else _scan_duration(container)
            )
            return VideoInfo(duration_s=duration, width=stream.width, height=stream.height)


def _scan_duration(container: InputContainer) -> float:
    """For containers without a duration header: the last packet's end time."""
    stream = container.streams.video[0]
    end = 0.0
    for packet in container.demux(stream):
        if packet.pts is not None and packet.time_base is not None:
            end = max(end, float((packet.pts + (packet.duration or 0)) * packet.time_base))
    return end


def _unreadable() -> UploadRejected:
    return UploadRejected("unreadable", "We couldn't read that video. Try another one.", 422)


def remux(src: Path, dst: Path, fmt: str, *, max_seconds: float | None = None) -> None:
    """Copy the audio and video streams into a fresh container. With `max_seconds`, stop with
    `too_long` once the packets run past it: a header can claim a shorter duration than the
    file holds, and the models bill by what is really there."""
    with av.open(str(src)) as source, av.open(str(dst), mode="w", format=fmt) as target:
        mapping = {}
        for stream in source.streams:
            if stream.type not in ("video", "audio"):
                continue  # data/subtitle tracks (e.g. Apple's metadata track) are dropped
            out = target.add_stream_from_template(stream)
            out.metadata.clear()
            mapping[stream.index] = out
        for packet in source.demux(*[source.streams[i] for i in mapping]):
            if packet.dts is None:
                continue  # demuxer flush packets
            if (
                max_seconds is not None
                and packet.pts is not None
                and packet.time_base
                and float(packet.pts * packet.time_base) > max_seconds + LENGTH_SLACK_S
            ):
                raise _too_long()
            packet.stream = mapping[packet.stream.index]
            target.mux(packet)


def _too_long() -> UploadRejected:
    return UploadRejected("too_long", f"Videos can be up to {MAX_VIDEO_SECONDS} seconds long.", 422)


def process_video(
    src: Path, mime: str, dst: Path, *, probe: VideoProbe | None = None
) -> ProcessedVideo:
    try:
        info = (probe or PyAVProbe()).probe(src)
    except (FFmpegError, IndexError, OSError) as exc:
        raise _unreadable() from exc
    if info.duration_s > MAX_VIDEO_SECONDS:
        raise _too_long()
    try:
        remux(src, dst, _FORMATS[mime], max_seconds=MAX_VIDEO_SECONDS)
    except (FFmpegError, OSError) as exc:
        raise _unreadable() from exc
    return ProcessedVideo(dst, mime, VIDEO_TYPES[mime], info.duration_s, info.width, info.height)
