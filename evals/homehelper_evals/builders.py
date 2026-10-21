"""Real agents for `evals run --agent homehelper_evals.builders:<name>` (spec §16.4).

Each builder receives the runner's `AgentContext` and returns an `AgentFactory`. Heavy resources
(the KB connection, the LLM client) are created once per run and shared by every case; what a
case changes is only its mock web search.

Web search in evals is always a mock (spec §16.4): a case with `web_results` gets exactly those
hits, every other case gets no web fallback at all. The mock hits' hosts are added to the
whitelist, because the injection set models a poisoned page on an allowed site; the whitelist
itself is not what is being tested.
"""

import asyncio
from urllib.parse import urlparse

from homehelper.agent.baseline import BaselineAgent
from homehelper.agent.deps import AgentDeps
from homehelper.agent.engine import default_catalog
from homehelper.agent.runtime import JourneyAgent
from homehelper.core.config import Settings
from homehelper.db.engine import create_engine
from homehelper.knowledge.backends import build_retriever
from homehelper.knowledge.retriever import KnowledgeRetriever
from homehelper.knowledge.schemas import RetrievalQuery, RetrievalResult
from homehelper.knowledge.web import SearchHit, WebKnowledge, Whitelist
from homehelper.llm import LLMClient, ModelRegistry, build_llm_client
from homehelper_evals.agents import AgentContext, AgentFactory
from homehelper_evals.cases import EvalCase, WebResult


class MockWebSearch:
    """`WebSearchClient` that serves one case's fixed results."""

    def __init__(self, results: list[WebResult]) -> None:
        self._hits = [SearchHit(url=r.url, title=r.title, content=r.content) for r in results]

    async def search(self, query: str, domains: list[str], max_results: int) -> list[SearchHit]:
        return self._hits[:max_results]


class SharedRetriever:
    """Builds the KB retriever on first use (it needs the event loop) and shares it."""

    def __init__(self, settings: Settings, registry: ModelRegistry | None = None) -> None:
        self._settings = settings
        self._registry = registry
        self._retriever: KnowledgeRetriever | None = None
        self._lock = asyncio.Lock()

    async def get(self) -> KnowledgeRetriever:
        async with self._lock:
            if self._retriever is None:
                engine = create_engine(self._settings.database_url)
                self._retriever, _ = await build_retriever(
                    self._settings, engine, registry=self._registry
                )
            return self._retriever


class CaseRetriever:
    """The shared retriever with one case's mock web fallback."""

    def __init__(self, shared: SharedRetriever, web: WebKnowledge | None) -> None:
        self._shared = shared
        self._web = web

    async def search(self, query: RetrievalQuery) -> RetrievalResult:
        retriever = await self._shared.get()
        return await retriever.with_web(self._web).search(query)


def case_web(case: EvalCase, llm: LLMClient, whitelist: Whitelist) -> WebKnowledge | None:
    if not case.web_results:
        return None
    hosts = sorted({urlparse(r.url).hostname or "" for r in case.web_results} - {""})
    allowed = whitelist.model_copy(update={"general": [*whitelist.general, *hosts]})
    return WebKnowledge(MockWebSearch(case.web_results), llm, allowed)


def baseline(context: AgentContext) -> AgentFactory:
    llm = build_llm_client(
        context.settings, registry=context.registry, usage_sink=context.usage_sink
    )
    shared = SharedRetriever(context.settings, context.registry)
    whitelist = Whitelist.load(context.settings.web_whitelist_path)

    def factory(case: EvalCase) -> BaselineAgent:
        return BaselineAgent(llm, CaseRetriever(shared, case_web(case, llm, whitelist)))

    return factory


def journey(context: AgentContext) -> AgentFactory:
    """The M3 journey agent, with an in-memory checkpointer per case."""
    llm = build_llm_client(
        context.settings, registry=context.registry, usage_sink=context.usage_sink
    )
    shared = SharedRetriever(context.settings, context.registry)
    whitelist = Whitelist.load(context.settings.web_whitelist_path)
    catalog = default_catalog()
    release_id = context.settings.release_id

    def factory(case: EvalCase) -> JourneyAgent:
        retriever = CaseRetriever(shared, case_web(case, llm, whitelist))
        return JourneyAgent(AgentDeps(llm, retriever, catalog, release_id=release_id))

    return factory
