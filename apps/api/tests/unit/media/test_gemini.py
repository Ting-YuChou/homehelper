"""Video understanding through the Gemini Files API (M6-03, spec §11.3), with a fake client."""

import io
from types import SimpleNamespace
from typing import Any

import pytest

from homehelper.llm import ModelRegistry, track_usage
from homehelper.media.gemini import (
    GeminiVideoAnalyzer,
    VideoAnalysisError,
    build_video_analyzer,
)
from homehelper.media.schemas import VideoResult
from tests.conftest import make_settings

RESULT = VideoResult(
    category="washing_machine",
    brand="LG",
    symptom_description="loud banging during spin",
    audio_cues=["rhythmic metal knocking during spin"],
    visible_error_codes=["UE"],
    key_timestamps=["0:12 drum wobbles"],
    confidence=0.8,
)


class FakeFiles:
    def __init__(self, states: list[str]) -> None:
        self.states = states
        self.uploaded: list[dict[str, Any]] = []
        self.deleted: list[str] = []

    async def upload(self, *, file: Any, config: Any = None) -> Any:
        self.uploaded.append(
            {"bytes": file.read() if isinstance(file, io.IOBase) else file, "config": config}
        )
        return SimpleNamespace(
            name="files/abc",
            state=SimpleNamespace(name=self.states.pop(0)),
            uri="u",
            mime_type="video/mp4",
        )

    async def get(self, *, name: str, config: Any = None) -> Any:
        return SimpleNamespace(
            name=name,
            state=SimpleNamespace(name=self.states.pop(0)),
            uri="u",
            mime_type="video/mp4",
        )

    async def delete(self, *, name: str, config: Any = None) -> None:
        self.deleted.append(name)


class FakeModels:
    def __init__(self, reply: VideoResult | Exception) -> None:
        self.reply = reply
        self.calls: list[dict[str, Any]] = []

    async def generate_content(self, *, model: str, contents: Any, config: Any = None) -> Any:
        self.calls.append({"model": model, "contents": contents, "config": config})
        if isinstance(self.reply, Exception):
            raise self.reply
        usage = SimpleNamespace(prompt_token_count=1200, candidates_token_count=150)
        return SimpleNamespace(
            parsed=self.reply, text=self.reply.model_dump_json(), usage_metadata=usage
        )


def _client(states: list[str], reply: VideoResult | Exception = RESULT) -> Any:
    return SimpleNamespace(aio=SimpleNamespace(files=FakeFiles(states), models=FakeModels(reply)))


def _analyzer(client: Any, **kwargs: Any) -> GeminiVideoAnalyzer:
    return GeminiVideoAnalyzer(client, model="gemini-3.8-flash", poll_s=0, **kwargs)


async def test_uploads_waits_for_processing_and_reads_the_answer() -> None:
    client = _client(["PROCESSING", "PROCESSING", "ACTIVE"])
    result = await _analyzer(client).analyze(b"video-bytes", "video/mp4", "Describe it.")
    assert result == RESULT
    files, models = client.aio.files, client.aio.models
    assert files.uploaded[0]["bytes"] == b"video-bytes"
    [call] = models.calls
    assert call["model"] == "gemini-3.8-flash"
    assert call["contents"][1] == "Describe it."
    assert files.deleted == ["files/abc"]


async def test_usage_is_recorded_for_the_spend_cap() -> None:
    client = _client(["ACTIVE"])
    sink: list[Any] = []
    with track_usage() as tally:
        await _analyzer(client, usage_sink=sink.append).analyze(b"v", "video/mp4", "p")
    [usage] = tally.calls
    assert (usage.task, usage.model, usage.input_tokens, usage.output_tokens) == (
        "video",
        "gemini/gemini-3.8-flash",
        1200,
        150,
    )
    assert sink == [usage]


async def test_the_remote_file_is_deleted_when_analysis_fails() -> None:
    client = _client(["ACTIVE"], RuntimeError("quota"))
    with pytest.raises(VideoAnalysisError):
        await _analyzer(client).analyze(b"v", "video/mp4", "p")
    assert client.aio.files.deleted == ["files/abc"]


async def test_failed_processing_is_an_error() -> None:
    client = _client(["PROCESSING", "FAILED"])
    with pytest.raises(VideoAnalysisError, match="FAILED"):
        await _analyzer(client).analyze(b"v", "video/mp4", "p")
    assert client.aio.files.deleted == ["files/abc"]
    assert client.aio.models.calls == []


def test_no_key_means_no_analyzer() -> None:
    assert build_video_analyzer(make_settings(), ModelRegistry.load()) is None
    analyzer = build_video_analyzer(make_settings(gemini_api_key="k"), ModelRegistry.load())
    assert isinstance(analyzer, GeminiVideoAnalyzer)
    assert analyzer.timeout_s == ModelRegistry.load().for_task("video").timeout_s == 60


def test_models_yaml_has_a_video_task() -> None:
    config = ModelRegistry.load().for_task("video")
    assert config.model.startswith("gemini/")
