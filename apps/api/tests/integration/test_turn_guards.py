"""Rate limits, the daily spend cap and the conversation lock on the message endpoint."""

from collections.abc import AsyncIterator

import httpx
import pytest
from redis.asyncio import Redis

from homehelper.agent.stub import StubAgent
from homehelper.channels.events import AgentEvent, InboundMessage
from homehelper.core.config import Settings
from homehelper.llm import LLMUsage, record_usage
from homehelper.main import create_app
from homehelper.ratelimit import ConversationLock, SpendLedger
from tests.integration.conftest import parse_sse

pytestmark = pytest.mark.integration


class CostlyAgent(StubAgent):
    async def handle(self, message: InboundMessage) -> AsyncIterator[AgentEvent]:
        record_usage(
            LLMUsage(
                task="respond",
                model="fake",
                input_tokens=1,
                output_tokens=1,
                cost_usd=0.02,
                latency_ms=1.0,
            )
        )
        async for event in super().handle(message):
            yield event


@pytest.fixture
async def guarded(api_settings: Settings, redis: Redis) -> AsyncIterator[httpx.AsyncClient]:
    settings = api_settings.model_copy(
        update={"rate_limit_per_hour": 2, "daily_spend_cap_usd": 0.03}
    )
    app = create_app(settings, agent=CostlyAgent())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/v1/auth/demo-login", json={"user_id": "demo_alex"})
        yield client
    await app.state.conversations.wait_idle()
    await app.state.redis.aclose()
    await app.state.db_engine.dispose()


async def _conversation(client: httpx.AsyncClient) -> str:
    return (await client.post("/v1/conversations", json={})).json()["id"]


async def test_cost_feeds_the_daily_cap_then_maintenance(
    guarded: httpx.AsyncClient, redis: Redis
) -> None:
    conversation_id = await _conversation(guarded)
    url = f"/v1/conversations/{conversation_id}/messages"
    assert (await guarded.post(url, json={"text": "Hi"})).status_code == 200
    assert (await guarded.post(url, json={"text": "Again"})).status_code == 200
    assert float(await redis.get(SpendLedger(redis, 0).key()) or 0) == pytest.approx(0.04)

    refused = await guarded.post(url, json={"text": "More"})
    assert refused.status_code == 503
    [(name, data)] = parse_sse(refused.text)
    assert (name, data["code"]) == ("error", "maintenance")


async def test_rate_limit_answers_429_with_retry_after(
    guarded: httpx.AsyncClient, redis: Redis
) -> None:
    conversation_id = await _conversation(guarded)
    url = f"/v1/conversations/{conversation_id}/messages"
    await guarded.post(url, json={"text": "Hi"})
    await redis.delete(SpendLedger(redis, 0).key())  # keep the spend cap out of the way
    await guarded.post(url, json={"text": "Hi"})
    await redis.delete(SpendLedger(redis, 0).key())

    refused = await guarded.post(url, json={"text": "Hi"})
    assert refused.status_code == 429
    assert 0 < int(refused.headers["retry-after"]) <= 3600
    [(name, data)] = parse_sse(refused.text)
    assert (name, data["code"]) == ("error", "rate_limited")


async def test_one_message_at_a_time_per_conversation(
    guarded: httpx.AsyncClient, redis: Redis
) -> None:
    conversation_id = await _conversation(guarded)
    url = f"/v1/conversations/{conversation_id}/messages"
    token = await ConversationLock(redis).acquire(conversation_id)  # a turn in flight
    assert token is not None

    refused = await guarded.post(url, json={"text": "Hi"})
    assert refused.status_code == 409
    assert parse_sse(refused.text)[0][1]["code"] == "conversation_busy"

    await ConversationLock(redis).release(conversation_id, token)
    assert (await guarded.post(url, json={"text": "Hi"})).status_code == 200
    # The finished turn released its own lock.
    assert await redis.get(ConversationLock.key(conversation_id)) is None
