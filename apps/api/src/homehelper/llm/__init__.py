from homehelper.core.config import Settings
from homehelper.core.tracing import Tracer
from homehelper.llm.fake import FakeLLMClient
from homehelper.llm.litellm_client import LiteLLMClient, UsageSink
from homehelper.llm.registry import ModelRegistry
from homehelper.llm.types import LLMClient, LLMError, LLMUsage, Message

__all__ = [
    "FakeLLMClient",
    "LLMClient",
    "LLMError",
    "LLMUsage",
    "LiteLLMClient",
    "Message",
    "ModelRegistry",
    "build_llm_client",
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
