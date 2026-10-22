"""Images for the vision eval (M6-04): licence rules, checksums, and synthetic renders."""

import hashlib
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from homehelper_evals.vision import SyntheticSource, VisionCase, load_cases
from homehelper_evals.vision_media import fetch_case, normalize_licence, render_case, verify


def _web(**source: object) -> VisionCase:
    return VisionCase.model_validate(
        {
            "id": "web-1",
            "image": "web/web-1.jpg",
            "source": {
                "kind": "web",
                "url": "https://upload.wikimedia.org/x.jpg",
                "page_url": "https://commons.wikimedia.org/wiki/File:x.jpg",
                "licence": "CC BY-SA 4.0",
                "author": "Someone",
                **source,
            },
            "expect": {"category": "washing_machine"},
        }
    )


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("CC0 1.0", "cc0"),
        ("Public domain", "pdm"),
        ("pdm", "pdm"),
        ("CC BY 4.0", "cc-by"),
        ("cc-by-sa-3.0", "cc-by-sa"),
        ("by-sa", "cc-by-sa"),
    ],
)
def test_licences_are_normalized(raw: str, normalized: str) -> None:
    assert normalize_licence(raw) == normalized


@pytest.mark.parametrize(
    "licence", ["CC BY-NC 4.0", "CC BY-ND 2.0", "CC BY-NC-SA 3.0", "All rights reserved", ""]
)
def test_restrictive_licences_are_refused(licence: str) -> None:
    with pytest.raises(ValidationError, match="licence"):
        _web(licence=licence)


def test_web_images_must_come_from_known_hosts() -> None:
    with pytest.raises(ValidationError, match="host"):
        _web(url="https://example.com/photo.jpg")


class FakeHttp:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.urls: list[str] = []

    def get_bytes(self, url: str) -> bytes:
        self.urls.append(url)
        return self.body


def test_fetch_checks_the_pinned_checksum(tmp_path: Path) -> None:
    body = b"\xff\xd8\xffimage"
    case = _web(sha256=hashlib.sha256(body).hexdigest())
    fetch_case(case, tmp_path, FakeHttp(body))
    assert (tmp_path / "web" / "web-1.jpg").read_bytes() == body
    tampered = _web(sha256="0" * 64)
    with pytest.raises(ValueError, match="sha256"):
        fetch_case(tampered, tmp_path / "other", FakeHttp(body))
    assert not (tmp_path / "other" / "web" / "web-1.jpg").exists()


def test_fetch_skips_files_already_there(tmp_path: Path) -> None:
    body = b"\xff\xd8\xffimage"
    case = _web(sha256=hashlib.sha256(body).hexdigest())
    http = FakeHttp(body)
    fetch_case(case, tmp_path, http)
    fetch_case(case, tmp_path, http)
    assert len(http.urls) == 1


def test_synthetic_renders_follow_their_parameters(tmp_path: Path) -> None:
    for case in load_cases():
        if not isinstance(case.source, SyntheticSource):
            continue
        params = case.source.params
        # The labels come from the render parameters, so they can't drift apart.
        for field in ("brand", "model_number", "category", "displayed_error_code"):
            if field in params and getattr(case.expect, field) != "unset":
                assert getattr(case.expect, field) == params[field], (case.id, field)
    sample = next(c for c in load_cases() if c.source.kind == "synthetic")
    path = render_case(sample, tmp_path)
    with Image.open(path) as image:
        assert image.width >= 400
    first = path.read_bytes()
    assert render_case(sample, tmp_path, force=True).read_bytes() == first  # seeded


def test_verify_reports_missing_and_changed_files(tmp_path: Path) -> None:
    body = b"\xff\xd8\xffimage"
    case = _web(sha256=hashlib.sha256(body).hexdigest())
    assert verify([case], tmp_path) == {"web-1": "missing"}
    fetch_case(case, tmp_path, FakeHttp(body))
    assert verify([case], tmp_path) == {}
    (tmp_path / "web" / "web-1.jpg").write_bytes(b"changed")
    assert verify([case], tmp_path) == {"web-1": "sha256 mismatch"}
