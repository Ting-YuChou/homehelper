"""Images for the vision eval (M6-04). None of them go into git (`data/media/` is ignored).

    uv run python -m homehelper_evals.vision_media generate   # synthetic nameplates and displays
    uv run python -m homehelper_evals.vision_media discover "washing machine control panel"
    uv run python -m homehelper_evals.vision_media fetch      # reviewed web photos, sha256-checked
    uv run python -m homehelper_evals.vision_media verify

Two kinds of images:
- Synthetic, rendered here with Pillow from the case's parameters: nameplates and error displays
  of models in the manual manifest, sharp or degraded (blur, rotation, glare, low resolution).
  They test reading a brand and model number, which free photos rarely show for our models.
  Their labels are their parameters, so the two can't drift apart.
- Web photos under CC0, public domain, CC BY or CC BY-SA from Wikimedia Commons or Openverse:
  real appliances, real damage, real displays. `discover` lists candidates for a person to review;
  only reviewed ones are added to `vision.yaml`, with the licence, author and sha256 pinned.
"""

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path
from typing import Any, Protocol

import httpx
import yaml
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from homehelper_evals import REPORTS_DIR
from homehelper_evals.vision import (
    ALLOWED_LICENCES,
    MEDIA_DIR,
    SyntheticSource,
    VisionCase,
    WebSource,
    load_cases,
    normalize_licence,
)

__all__ = ["fetch_case", "normalize_licence", "render_case", "verify"]

# Wikimedia's API policy wants a URL or contact in the User-Agent; without one it answers 403.
USER_AGENT = "HomeHelper-eval/0.1 (https://github.com/Ting-YuChou/homehelper; private eval set)"
SIZE = (960, 600)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


def _seed(case: VisionCase) -> int:
    return int(hashlib.sha256(case.id.encode()).hexdigest()[:8], 16)


def _nameplate(params: dict[str, Any], rng: random.Random) -> Image.Image:
    image = Image.new("RGB", SIZE, (205, 208, 212))
    draw = ImageDraw.Draw(image)
    for y in range(SIZE[1]):  # brushed-metal shading
        shade = 195 + int(20 * (y / SIZE[1])) + rng.randint(-3, 3)
        draw.line([(0, y), (SIZE[0], y)], fill=(shade, shade + 2, shade + 5))
    draw.rectangle([20, 20, SIZE[0] - 20, SIZE[1] - 20], outline=(60, 60, 60), width=4)
    lines = [
        (params["brand"].upper(), 72),
        (f"MODEL  {params['model_number']}", 48),
        (f"SERIAL  {params.get('serial', rng.randint(10**9, 10**10 - 1))}", 34),
        (params.get("rating", "120V~ 60Hz 10A"), 30),
        (params.get("product", ""), 30),
        (params.get("extra_line", ""), 26),
    ]
    y = 55
    for text, size in lines:
        if text:
            draw.text((60, y), text, fill=(25, 25, 25), font=_font(size))
            y += size + 28
    return image


def _display(params: dict[str, Any], rng: random.Random) -> Image.Image:
    image = Image.new("RGB", SIZE, (40, 42, 46))
    draw = ImageDraw.Draw(image)
    if params.get("brand"):
        draw.text((50, 40), params["brand"], fill=(200, 200, 205), font=_font(44))
    draw.rounded_rectangle([280, 170, 680, 400], radius=18, fill=(8, 10, 8))
    draw.text(
        (330, 205),
        params["displayed_error_code"],
        fill=tuple(params.get("color", (255, 60, 40))),
        font=_font(150),
    )
    for i, label in enumerate(params.get("buttons", ["Start/Pause", "Options", "Power"])):
        draw.ellipse([90 + i * 280, 470, 140 + i * 280, 520], outline=(170, 170, 170), width=3)
        draw.text((155 + i * 280, 480), label, fill=(170, 170, 170), font=_font(28))
    return image


def _blank(params: dict[str, Any], rng: random.Random) -> Image.Image:
    base = tuple(params.get("color", (180, 170, 160)))
    image = Image.new("RGB", SIZE, base)  # type: ignore[arg-type]
    draw = ImageDraw.Draw(image)
    for _ in range(4000):
        x, y = rng.randrange(SIZE[0]), rng.randrange(SIZE[1])
        jitter = rng.randint(-12, 12)
        draw.point((x, y), fill=tuple(max(0, min(255, c + jitter)) for c in base))
    return image


def _text(params: dict[str, Any], rng: random.Random) -> Image.Image:
    image = Image.new("RGB", SIZE, (250, 248, 235))
    draw = ImageDraw.Draw(image)
    for i, line in enumerate(params.get("lines", ["Groceries", "- milk", "- eggs", "- bread"])):
        draw.text((80, 60 + i * 70), line, fill=(30, 30, 90), font=_font(48))
    return image


TEMPLATES = {"nameplate": _nameplate, "display": _display, "blank": _blank, "text": _text}


def _degrade(image: Image.Image, params: dict[str, Any], rng: random.Random) -> Image.Image:
    if params.get("glare"):
        overlay = Image.new("L", image.size, 0)
        x, y = rng.randint(200, 700), rng.randint(100, 400)
        ImageDraw.Draw(overlay).ellipse([x - 220, y - 120, x + 220, y + 120], fill=235)
        overlay = overlay.filter(ImageFilter.GaussianBlur(60))
        image = Image.composite(Image.new("RGB", image.size, "white"), image, overlay)
    if params.get("rotate"):
        image = image.rotate(params["rotate"], expand=True, fillcolor=(90, 90, 90))
    if params.get("scale"):
        small = image.resize(
            (int(image.width * params["scale"]), int(image.height * params["scale"]))
        )
        image = small.resize(image.size)
    if params.get("blur"):
        image = image.filter(ImageFilter.GaussianBlur(params["blur"]))
    return image


def render_case(case: VisionCase, media_dir: Path = MEDIA_DIR, *, force: bool = False) -> Path:
    source = case.source
    if not isinstance(source, SyntheticSource):
        raise ValueError(f"{case.id} is not synthetic")
    path = media_dir / case.image
    if path.exists() and not force:
        return path
    rng = random.Random(_seed(case))
    image = _degrade(TEMPLATES[source.template](source.params, rng), source.params, rng)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")
    return path


class Http(Protocol):
    def get_bytes(self, url: str) -> bytes: ...


class HttpxClient:
    def __init__(self) -> None:
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True
        )

    def get_bytes(self, url: str) -> bytes:
        response = self._client.get(url)
        response.raise_for_status()
        return response.content

    def get_json(self, url: str, params: dict[str, Any]) -> Any:
        response = self._client.get(url, params=params)
        response.raise_for_status()
        return response.json()


def fetch_case(case: VisionCase, media_dir: Path, http: Http) -> Path:
    source = case.source
    if not isinstance(source, WebSource):
        raise ValueError(f"{case.id} is not a web image")
    path = media_dir / case.image
    if path.exists():
        return path
    body = http.get_bytes(source.url)
    digest = hashlib.sha256(body).hexdigest()
    if source.sha256 is None:
        print(f"{case.id}: sha256 {digest} (pin it in vision.yaml)", file=sys.stderr)
    elif digest != source.sha256:
        raise ValueError(f"{case.id}: sha256 {digest} does not match the pinned {source.sha256}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def verify(cases: list[VisionCase], media_dir: Path = MEDIA_DIR) -> dict[str, str]:
    problems: dict[str, str] = {}
    for case in cases:
        path = media_dir / case.image
        if not path.exists():
            problems[case.id] = "missing"
        elif (
            isinstance(case.source, WebSource)
            and case.source.sha256
            and hashlib.sha256(path.read_bytes()).hexdigest() != case.source.sha256
        ):
            problems[case.id] = "sha256 mismatch"
    return problems


def discover(query: str, limit: int, http: HttpxClient) -> list[dict[str, Any]]:
    """Candidate photos with an allowed licence, for a person to review (not added anywhere)."""
    found: list[dict[str, Any]] = []
    try:
        found.extend(_commons(query, limit, http))
    except httpx.HTTPError as exc:
        print(f"Wikimedia Commons: {exc}", file=sys.stderr)
    try:
        found.extend(_openverse(query, limit, http))
    except httpx.HTTPError as exc:
        print(f"Openverse: {exc}", file=sys.stderr)
    return found


def _commons(query: str, limit: int, http: HttpxClient) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    commons = http.get_json(
        "https://commons.wikimedia.org/w/api.php",
        {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": f"filetype:bitmap {query}",
            "gsrnamespace": 6,
            "gsrlimit": limit,
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|size",
            "iiurlwidth": 1600,
        },
    )
    for page in (commons.get("query", {}).get("pages", {}) or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        licence = meta.get("LicenseShortName", {}).get("value", "")
        if normalize_licence(licence) in ALLOWED_LICENCES:
            found.append(
                {
                    "url": info.get("thumburl") or info.get("url"),
                    "page_url": info.get("descriptionurl"),
                    "licence": licence,
                    "author": meta.get("Artist", {}).get("value", ""),
                    "title": page.get("title"),
                }
            )
    return found


def _openverse(query: str, limit: int, http: HttpxClient) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    openverse = http.get_json(
        "https://api.openverse.org/v1/images/",
        {"q": query, "license": "cc0,pdm,by,by-sa", "page_size": limit},
    )
    for item in openverse.get("results", []):
        found.append(
            {
                "url": item.get("url"),
                "page_url": item.get("foreign_landing_url"),
                "licence": f"{item.get('license', '')} {item.get('license_version', '')}".strip(),
                "author": item.get("creator") or "",
                "title": item.get("title"),
            }
        )
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m homehelper_evals.vision_media")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("generate").add_argument("--force", action="store_true")
    commands.add_parser("fetch")
    commands.add_parser("verify")
    found = commands.add_parser("discover")
    found.add_argument("query")
    found.add_argument("--limit", type=int, default=20)
    parser.add_argument("--media-dir", type=Path, default=MEDIA_DIR)
    args = parser.parse_args(argv)

    cases = load_cases()
    if args.command == "generate":
        synthetic = [c for c in cases if isinstance(c.source, SyntheticSource)]
        for case in synthetic:
            render_case(case, args.media_dir, force=args.force)
        print(f"rendered {len(synthetic)} images into {args.media_dir}", file=sys.stderr)
    elif args.command == "fetch":
        http = HttpxClient()
        web = [c for c in cases if isinstance(c.source, WebSource)]
        for case in web:
            fetch_case(case, args.media_dir, http)
        print(f"fetched {len(web)} images into {args.media_dir}", file=sys.stderr)
    elif args.command == "verify":
        problems = verify(cases, args.media_dir)
        print(json.dumps(problems, indent=2))
        return 1 if problems else 0
    else:
        candidates = discover(args.query, args.limit, HttpxClient())
        out = REPORTS_DIR / "vision_candidates.yaml"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml.safe_dump({"query": args.query, "candidates": candidates}))
        print(f"{len(candidates)} candidates in {out}; review before adding any", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
