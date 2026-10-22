"""Video understanding with Gemini (spec §11.3, M6-03), through the official `google-genai` SDK.

LiteLLM has no Files API flow (upload, wait for processing, refer to the file), so this calls
Gemini directly and records usage the way `LiteLLMClient` does: `record_usage()` for the turn's
spend, plus an optional sink for evals. The uploaded file is always deleted afterwards; with a
paid key Google does not train on it.

The caller bounds the whole call with `timeout_s` (the `video` task's, default 60 s); a slow or
failed analysis degrades to "please describe it in words" (M-MEDIA-01), never an error.
"""

import asyncio
import io
import time
from collections.abc import Callable
from typing import Any, Protocol

from homehelper.core.config import Settings
from homehelper.core.logging import get_logger
from homehelper.llm import LLMUsage, ModelRegistry, record_usage
from homehelper.media.schemas import VideoResult

log = get_logger(__name__)
TASK = "video"
DELETE_TIMEOUT_S = 5


class VideoAnalysisError(RuntimeError):
    pass


class VideoAnalyzer(Protocol):
    timeout_s: float

    async def analyze(self, data: bytes, mime: str, prompt: str) -> VideoResult: ...


def _cost(model: str, input_tokens: int, output_tokens: int) -> float:
    try:
        import litellm

        prompt_cost, completion_cost = litellm.cost_per_token(
            model=model, prompt_tokens=input_tokens, completion_tokens=output_tokens
        )
        return float(prompt_cost + completion_cost)
    except Exception:
        return 0.0  # unknown pricing must never fail the call


class GeminiVideoAnalyzer:
    def __init__(
        self,
        client: Any,  # google.genai.Client; typed loosely so tests can pass a fake
        *,
        model: str,
        timeout_s: float = 60,
        max_tokens: int = 1024,
        poll_s: float = 2.0,
        usage_sink: Callable[[LLMUsage], None] | None = None,
    ) -> None:
        self._client = client
        self.model = model.removeprefix("gemini/")
        self.timeout_s = timeout_s
        self._max_tokens = max_tokens
        self._poll_s = poll_s
        self._usage_sink = usage_sink

    async def analyze(self, data: bytes, mime: str, prompt: str) -> VideoResult:
        """Any provider or SDK error becomes `VideoAnalysisError`; cancellation passes through."""
        from google.genai import types

        files = self._client.aio.files
        started = time.perf_counter()
        uploaded: Any = None
        try:
            uploaded = await files.upload(file=io.BytesIO(data), config={"mime_type": mime})
            while getattr(uploaded.state, "name", None) == "PROCESSING":
                await asyncio.sleep(self._poll_s)
                uploaded = await files.get(name=uploaded.name)
            state = getattr(uploaded.state, "name", None)
            if state != "ACTIVE":
                raise VideoAnalysisError(f"video processing ended in {state}")
            response = await self._client.aio.models.generate_content(
                model=self.model,
                contents=[uploaded, prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=VideoResult,
                    max_output_tokens=self._max_tokens,
                ),
            )
            # Billed whether or not the answer is usable.
            self._record(response, time.perf_counter() - started)
            if isinstance(response.parsed, VideoResult):
                return response.parsed
            return VideoResult.model_validate_json(response.text or "")
        except VideoAnalysisError:
            raise
        except Exception as exc:
            raise VideoAnalysisError(f"{type(exc).__name__}: {exc}") from exc
        finally:
            # A timeout during the upload leaves no name to delete; Gemini expires it in 48 h.
            if uploaded is not None:
                try:
                    async with asyncio.timeout(
                        DELETE_TIMEOUT_S
                    ):  # a hung API mustn't hold the turn
                        await files.delete(name=uploaded.name)
                except Exception:
                    log.warning("gemini_file_delete_failed", name=uploaded.name)

    def _record(self, response: Any, seconds: float) -> None:
        tokens = getattr(response, "usage_metadata", None)
        input_tokens = getattr(tokens, "prompt_token_count", 0) or 0
        output_tokens = getattr(tokens, "candidates_token_count", 0) or 0
        model = f"gemini/{self.model}"
        usage = LLMUsage(
            task=TASK,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=_cost(model, input_tokens, output_tokens),
            latency_ms=round(seconds * 1000, 1),
        )
        record_usage(usage)
        if self._usage_sink is not None:
            self._usage_sink(usage)


def build_video_analyzer(
    settings: Settings,
    registry: ModelRegistry,
    *,
    usage_sink: Callable[[LLMUsage], None] | None = None,
) -> GeminiVideoAnalyzer | None:
    """None without a Gemini key: videos then degrade to a request for words right away."""
    key = settings.gemini_api_key.get_secret_value()
    if not key:
        return None
    from google import genai

    config = registry.for_task(TASK)
    return GeminiVideoAnalyzer(
        genai.Client(api_key=key),
        model=config.model,
        timeout_s=config.timeout_s,
        max_tokens=config.max_tokens,
        usage_sink=usage_sink,
    )
