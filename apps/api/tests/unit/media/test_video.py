from fractions import Fraction
from pathlib import Path

import av
import pytest

from homehelper.media.validation import MAX_VIDEO_SECONDS, UploadRejected
from homehelper.media.video import PyAVProbe, VideoInfo, process_video
from tests.unit.media.samples import write_video

LOCATION = "+37.7749-122.4194/"


class FakeProbe:
    def __init__(self, info: VideoInfo | Exception) -> None:
        self.info = info

    def probe(self, path: Path) -> VideoInfo:
        if isinstance(self.info, Exception):
            raise self.info
        return self.info


def test_pyav_reads_duration_and_size(tmp_path: Path) -> None:
    info = PyAVProbe().probe(write_video(tmp_path / "a.mp4", seconds=2.0))
    assert info.duration_s == pytest.approx(2.0, abs=0.2)
    assert (info.width, info.height) == (64, 48)


def test_pyav_reads_webm_duration(tmp_path: Path) -> None:
    info = PyAVProbe().probe(write_video(tmp_path / "a.webm", codec="libvpx"))
    assert info.duration_s == pytest.approx(1.0, abs=0.2)


def test_rejects_videos_over_the_limit(tmp_path: Path) -> None:
    src = write_video(tmp_path / "a.mp4")
    probe = FakeProbe(VideoInfo(duration_s=MAX_VIDEO_SECONDS + 1, width=64, height=48))
    with pytest.raises(UploadRejected) as raised:
        process_video(src, "video/mp4", tmp_path / "out.mp4", probe=probe)
    assert raised.value.code == "too_long"
    assert raised.value.status_code == 422


def test_rejects_videos_it_cannot_read(tmp_path: Path) -> None:
    src = tmp_path / "a.mp4"
    src.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)
    with pytest.raises(UploadRejected) as raised:
        process_video(src, "video/mp4", tmp_path / "out.mp4")
    assert raised.value.code == "unreadable"


@pytest.mark.parametrize(
    ("name", "mime", "codec"),
    [
        ("a.mp4", "video/mp4", "mpeg4"),
        ("a.mov", "video/quicktime", "mpeg4"),
        ("a.webm", "video/webm", "libvpx"),
    ],
)
def test_remux_drops_location_and_other_metadata(
    tmp_path: Path, name: str, mime: str, codec: str
) -> None:
    src = write_video(
        tmp_path / name, codec=codec, metadata={"location": LOCATION, "title": "home"}
    )
    out = tmp_path / f"out-{name}"
    result = process_video(src, mime, out)
    assert result.path == out
    with av.open(str(out)) as container:
        tags = {k.lower(): v for k, v in container.metadata.items()}
        assert not any(k.startswith("location") for k in tags)
        assert "title" not in tags
        assert container.streams.video[0].frames in (0, 10)  # stream copied, not re-encoded away
    assert result.duration_s == pytest.approx(1.0, abs=0.2)
    assert LOCATION.encode() not in out.read_bytes()


def test_a_video_longer_than_its_header_says_is_caught_while_remuxing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = write_video(tmp_path / "a.mp4", seconds=3.0)
    lying = FakeProbe(VideoInfo(duration_s=1.0, width=64, height=48))
    monkeypatch.setattr("homehelper.media.video.MAX_VIDEO_SECONDS", 2)
    with pytest.raises(UploadRejected) as raised:
        process_video(src, "video/mp4", tmp_path / "out.mp4", probe=lying)
    assert raised.value.code == "too_long"


def test_a_clip_that_starts_late_is_measured_from_its_start(tmp_path: Path) -> None:
    src = write_video(tmp_path / "a.mp4", seconds=10.0, start_s=55.0)
    result = process_video(src, "video/mp4", tmp_path / "out.mp4")
    assert result.duration_s < 11


def test_an_early_huge_timestamp_does_not_hide_the_length(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from homehelper.media import video

    class Packet:
        def __init__(self, pts: int) -> None:
            self.pts, self.dts, self.time_base = pts, pts, Fraction(1, 1)
            self.stream = type("S", (), {"index": 0})()

    spans = video.packet_span([Packet(p) for p in (10_000, 0, 30, 3600)])
    assert spans == 10_000
