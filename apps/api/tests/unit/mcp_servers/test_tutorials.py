import httpx
import pytest

from homehelper.mcp_servers.factory import video_search_for
from homehelper.mcp_servers.mock_data import MockData
from homehelper.mcp_servers.tutorials import (
    MockVideoSearch,
    YouTubeVideoSearch,
    build_tutorials_server,
)
from tests.conftest import make_settings
from tests.unit.mcp_servers.conftest import connect

YOUTUBE_RESPONSE = {
    "kind": "youtube#searchListResponse",
    "items": [
        {
            "id": {"kind": "youtube#video", "videoId": "abc123"},
            "snippet": {
                "title": "LG Washer &quot;OE&quot; Error &amp; Drain Filter",
                "channelTitle": "Fix It Fast",
                "thumbnails": {"default": {"url": "https://i.ytimg.com/vi/abc123/default.jpg"}},
            },
        },
        {"id": {"kind": "youtube#channel", "channelId": "UCx"}, "snippet": {"title": "skip me"}},
    ],
}


class FakeYouTube:
    """httpx transport standing in for the YouTube Data API."""

    def __init__(self, status: int = 200) -> None:
        self.requests: list[httpx.Request] = []
        self.status = status

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json=YOUTUBE_RESPONSE if self.status == 200 else {})

    def search(self) -> YouTubeVideoSearch:
        http = httpx.AsyncClient(transport=httpx.MockTransport(self.handler))
        return YouTubeVideoSearch("test-key", http)


async def test_youtube_search_query_parsing_and_cache() -> None:
    fake = FakeYouTube()
    server = build_tutorials_server(fake.search())
    async with connect(server) as client:
        args = {"query": "won't drain", "brand": "LG", "category": "washing_machine"}
        first = await client.call("search_videos", **args)
        second = await client.call("search_videos", **args)
    assert first == second
    assert len(fake.requests) == 1  # cached: the API allows ~100 searches a day
    params = fake.requests[0].url.params
    assert params["q"] == "LG washing machine won't drain"
    assert params["type"] == "video"
    assert params["safeSearch"] == "strict"
    assert params["key"] == "test-key"
    assert first == [
        {
            "video_id": "abc123",
            "title": 'LG Washer "OE" Error & Drain Filter',
            "channel": "Fix It Fast",
            "url": "https://www.youtube.com/watch?v=abc123",
            "thumbnail_url": "https://i.ytimg.com/vi/abc123/default.jpg",
            "duration_seconds": None,
            "source": "youtube",
        }
    ]


async def test_youtube_errors_become_tool_errors_without_leaking_the_key() -> None:
    server = build_tutorials_server(FakeYouTube(status=403).search())
    async with connect(server) as client:
        message = await client.error("search_videos", query="descale")
    assert "unavailable" in message
    assert "test-key" not in message


async def test_mock_videos_filter_by_category_and_brand(data: MockData) -> None:
    server = build_tutorials_server(MockVideoSearch(data.videos))
    async with connect(server) as client:
        lg = await client.call(
            "search_videos", query="washer won't drain", brand="LG", category="washing_machine"
        )
        bosch = await client.call(
            "search_videos", query="won't drain", brand="Bosch", category="dishwasher"
        )
    assert lg[0]["video_id"] == "mock_lg_drain_filter"
    assert lg[0]["source"] == "mock"
    assert lg[0]["url"].startswith("https://www.youtube.com/results?search_query=")
    assert all(v["video_id"].startswith("mock_bosch") for v in bosch)


@pytest.mark.parametrize(
    ("mode", "key", "expected"),
    [
        ("real", "k", YouTubeVideoSearch),
        ("real", "", MockVideoSearch),
        ("mock", "k", MockVideoSearch),
    ],
)
def test_youtube_only_in_real_mode_with_a_key(
    data: MockData, mode: str, key: str, expected: type
) -> None:
    settings = make_settings(mcp_mode=mode, youtube_api_key=key)
    assert isinstance(video_search_for(settings, data), expected)
