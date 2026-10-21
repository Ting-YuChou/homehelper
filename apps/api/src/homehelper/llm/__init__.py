from homehelper.core.config import Settings
from homehelper.core.tracing import Tracer
from homehelper.llm.fake import FakeLLMClient
from homehelper.llm.litellm_client import LiteLLMClient, UsageSink
from homehelper.llm.registry import ModelRegistry
from homehelper.llm.types import LLMClient, LLMError, LLMUsage, Message
from homehelper.llm.usage import UsageTally, record_usage, track_usage

__all__ = [
    "FakeLLMClient",
    "LLMClient",
    "LLMError",
    "LLMUsage",
    "LiteLLMClient",
    "Message",
    "ModelRegistry",
    "UsageTally",
    "build_llm_client",
    "record_usage",
    "track_usage",
]


def build_llm_client(
    settings: Settings,
    *,
    registry: ModelRegistry | None = None,
    tracer: Tracer | None = None,
    usage_sink: UsageSink | None = None,
) -> LiteLLMClient:
    return LiteLLMClient(
        registry or ModelRegistry.load(),
        settings.provider_api_keys(),
        tracer=tracer,
        usage_sink=usage_sink,
    )
