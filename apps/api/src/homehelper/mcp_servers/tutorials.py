"""`tutorials` MCP server: repair videos (spec §12.1, M5-04).

Real mode searches the YouTube Data API v3 (`search.list`); without `YOUTUBE_API_KEY`, or in mock
mode, it serves `videos.json`. The API allows about 100 searches a day, so results are cached.
"""

import html
import time
from typing import Annotated, Any, Protocol
from urllib.parse import quote_plus

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import Field

from homehelper.core.logging import get_logger
from homehelper.knowledge.schemas import CategoryId
from homehelper.mcp_servers.common import mcp_tool, new_server, words
from homehelper.mcp_servers.schemas import MockVideo, Video

log = get_logger(__name__)

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
CACHE_TTL_SECONDS = 6 * 3600

INSTRUCTIONS = "Short repair and maintenance videos for a home appliance problem."


class VideoSearch(Protocol):
    async def search(
        self, query: str, *, brand: str | None, category: CategoryId | None, max_results: int
    ) -> list[Video]: ...


def _query(query: str, brand: str | None, category: CategoryId | None) -> str:
    appliance = category.value.replace("_", " ") if category else None
    return " ".join(p for p in (brand, appliance, query) if p)


def _video(item: dict[str, Any]) -> Video | None:
    video_id = item.get("id", {}).get("videoId")
    snippet = item.get("snippet", {})
    if not video_id:
        return None
    thumbnails = snippet.get("thumbnails", {})
    thumbnail = next(
        (thumbnails[k]["url"] for k in ("medium", "high", "default") if k in thumbnails), None
    )
    return Video(
        video_id=video_id,
        title=html.unescape(snippet.get("title", "")),  # the API returns HTML entities
        channel=html.unescape(snippet.get("channelTitle", "")),
        url=f"https://www.youtube.com/watch?v={video_id}",
        thumbnail_url=thumbnail,
        source="youtube",
    )


class YouTubeVideoSearch:
    def __init__(self, api_key: str, http: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        self._http = http or httpx.AsyncClient(timeout=10.0)
        self._cache: dict[tuple[str, int], tuple[float, list[Video]]] = {}

    async def search(
        self, query: str, *, brand: str | None, category: CategoryId | None, max_results: int
    ) -> list[Video]:
        q = _query(query, brand, category)
        key = (q.lower(), max_results)
        cached = self._cache.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        params = {
            "part": "snippet",
            "type": "video",
            "q": q,
            "maxResults": max_results,
            "safeSearch": "strict",
            "relevanceLanguage": "en",
            "videoEmbeddable": "true",
            "key": self._api_key,
        }
        try:
            response = await self._http.get(YOUTUBE_SEARCH_URL, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            # Don't log the request URL: it carries the API key.
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            log.warning("youtube_search_failed", error=type(exc).__name__, status=status)
            raise ToolError("Video search is unavailable right now") from None
        videos = [v for item in response.json().get("items", []) if (v := _video(item))]
        self._cache[key] = (time.monotonic() + CACHE_TTL_SECONDS, videos)
        return videos


class MockVideoSearch:
    def __init__(self, videos: list[MockVideo]) -> None:
        self._videos = videos

    async def search(
        self, query: str, *, brand: str | None, category: CategoryId | None, max_results: int
    ) -> list[Video]:
        said = words(query)
        scored: list[tuple[int, MockVideo]] = []
        for video in self._videos:
            if category and video.category != category:
                continue
            if brand and video.brands and brand.lower() not in {b.lower() for b in video.brands}:
                continue
            known = words(video.title) | {w for k in video.keywords for w in words(k)}
            score = len(said & known)
            if score:
                scored.append((score + (1 if brand and video.brands else 0), video))
        scored.sort(key=lambda sv: -sv[0])
        return [
            Video(
                video_id=v.video_id,
                title=v.title,
                channel=v.channel,
                # Mock entries are not real uploads: link to a YouTube search for the title.
                url=f"https://www.youtube.com/results?search_query={quote_plus(v.title)}",
                duration_seconds=v.duration_seconds,
                source="mock",
            )
            for _, v in scored[:max_results]
        ]


def build_tutorials_server(videos: VideoSearch) -> FastMCP:
    server = new_server("tutorials", INSTRUCTIONS)

    @mcp_tool(server, title="Search repair videos", open_world=True)
    async def search_videos(
        query: Annotated[
            str, Field(min_length=2, max_length=200, description="The problem or task")
        ],
        brand: str | None = None,
        category: CategoryId | None = None,
        max_results: Annotated[int, Field(ge=1, le=10)] = 3,
    ) -> list[Video]:
        """Repair or how-to videos for the appliance problem, most relevant first."""
        return await videos.search(query, brand=brand, category=category, max_results=max_results)

    return server
