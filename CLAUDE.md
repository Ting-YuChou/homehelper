# CLAUDE.md

HomeHelper v2 — a B2C home-appliance repair support agent (portfolio project), inspired by Sierra's Agent OS / τ-bench approach.

## Source of truth

- `docs/SPEC.md` is the single source of truth. Read the relevant section before implementing anything.
- Work proceeds milestone by milestone (`M0` … `M8`, spec §19). Task IDs look like `M3-05`.
- When a decision changes the spec, update `docs/SPEC.md` in the same PR and add a line to its Appendix D change log. Significant trade-offs also get an ADR in `docs/adr/`.

## Language

- Talk to the user in Traditional Chinese (zh-TW).
- Everything the system produces is **English**: UI, agent replies, prompts, eval data, code, comments, commit messages, PR descriptions, README, ADRs. `docs/SPEC.md` itself stays in Chinese.

## Repo layout

```
apps/api/        Python 3.12 · FastAPI · package `homehelper` (src layout); MCP servers live in `homehelper/mcp_servers/`
apps/web/        TypeScript · Next.js (App Router)
evals/           uv workspace member, package `homehelper_evals`: splits, retrieval eval, simulator, graders, runner
data/            manifest, scenarios, mock data (PDFs/media are git-ignored)
releases/        release manifests
infra/           Dockerfiles, docker-compose, Cloud Run config
docs/            SPEC.md, adr/
```

## Commands

```bash
uv sync                 # Python deps (uv workspace at repo root)
pnpm install            # web deps (pnpm workspace at repo root)
make up                 # docker compose: postgres :5432, redis :6379, api :8000 (reload), web :3000
make down
make test               # unit tests (pytest, from repo root)
make test-integration   # + integration tests against the running stack (RUN_INTEGRATION=1)
make test-agent-cov     # journey engine + guardrail tests with the >= 90% coverage gate
make lint               # ruff check/format --check, pyright, eslint, tsc
make fmt
make migrate            # `homehelper db upgrade`: alembic to head from the packaged migrations (needs `make up`)
make seed-mock          # reset the MCP mock tables to data/mock/ (needs `make migrate`)
uv run homehelper mcp serve user_profile --mode mock   # one MCP server standalone (MCP Inspector)
uv run evals run --suite smoke --simulator scripted --no-judge   # eval pipeline, no LLM cost
uv run evals run --suite tools --agent stub --simulator scripted --no-judge   # tool-scenario pipeline (M5-08)
uv run evals run --suite smoke   # Haiku simulator + Sonnet judge against the stub agent
uv run evals run --suite smoke --models models.yaml   # per-task overrides, e.g. `nlu: opencode_go/openai/glm-5.3`
uv run evals run --suite multi_issue --agent stub --simulator scripted --no-judge   # two interleaved problems (ADR-007), no LLM cost
pnpm --filter web build
pnpm --filter web test  # vitest (SSE parsing, turn reducer)
make openapi            # regenerate apps/web/lib/api/{openapi.json,schema.d.ts}; CI fails if stale

# Knowledge base (M1) — needs PDFs in data/manuals/pdfs/ (main checkout only) and keys in .env
uv run homehelper manifest draft   # draft unreviewed manifest entries (Haiku); review, set reviewed: true
uv run homehelper parse            # LlamaParse → data/parsed/<sha256>.<tier>.json (cached; paid per page)
make ingest                        # parse (cached) → chunk → embed → new kb_YYYYMMDD_NN table
uv run python -m homehelper_evals.retrieval.run --calibrate   # Recall@5/MRR + τ calibration
uv run evals run --suite smoke --agent homehelper_evals.builders:baseline   # or :journey; conversation sim against a real agent (needs the KB in Postgres)
uv run python -m homehelper_evals.nlu --models evals/models/opencode-go.yaml   # NLU accuracy on evals/datasets/nlu.yaml (M3-03)

# Multimodal (M6) — images and clips live in data/media/ (git-ignored)
uv run python -m homehelper_evals.vision_media generate      # synthetic nameplates/displays for vision.yaml
uv run python -m homehelper_evals.vision_media discover "<query>"   # CC0/PDM/CC BY(-SA) candidates to review
uv run python -m homehelper_evals.vision_media fetch          # reviewed web photos, sha256-checked
uv run python -m homehelper_evals.vision --models evals/models/opencode-go.yaml   # photo accuracy + calibration
uv run evals run --suite multimodal --agent homehelper_evals.builders:journey --models evals/models/opencode-go.yaml
uv run python -m homehelper_evals.video                       # Gemini video eval (needs GEMINI_API_KEY)

# Quality loop (M7) — /admin needs ADMIN_TOKEN; reports and exported cases live in the database
uv run evals regression pull          # exported cases -> evals/datasets/regression/<id>.yaml (+ media); commit them
uv run evals run --suite regression --agent homehelper_evals.builders:journey   # replay them; --case ID for one
uv run evals run --suite safety --record   # also store the report summary for /admin/evals
uv run evals publish evals/reports         # store earlier reports for /admin/evals

# Cloud (M8, docs/deploy.md, ADR-011) — region us-west1; every script takes --dry-run
pnpm --filter web e2e                      # Playwright against E2E_BASE_URL (default localhost:3000)
infra/gcp/bootstrap.sh --project <id>      # one-time GCP setup; prints the GitHub variables
infra/gcp/secrets.sh --project <id>        # .env.cloud -> Secret Manager (never prints values)
infra/gcp/cloudrun.sh url web              # shared deploy steps for deploy.yml / release.yml
python3 infra/gcp/monitoring.py --project <id> --email <addr>   # uptime, 5xx, latency, spend alerts
```

- Run the API without Docker: `uv run uvicorn homehelper.main:create_app --factory --reload` (it is an app factory; there is no module-level `app`).
- Tests build the app with `create_app(make_settings(...))` from `apps/api/tests/conftest.py`; settings never read `.env` in tests.
- Integration tests that need the app tables use the fixtures in `apps/api/tests/integration/conftest.py` (`migrated`, `api`, `redis` on Redis db 15, flushed per test). The browser calls `/v1` on the web app, which proxies it to the API (`app/v1/[...path]/route.ts`, server-side `API_URL`, ADR-011); the API's `CORS_ORIGINS` must list the web origin, since the Origin check sees the browser's origin.
- Integration tests are marked `@pytest.mark.integration` and skipped unless `RUN_INTEGRATION=1` (CI sets it, with Postgres/Redis service containers).
- `apps/web` uses Next.js 16, which differs from older versions: read `apps/web/AGENTS.md` and the docs in `apps/web/node_modules/next/dist/docs/` before writing web code. `pnpm typecheck` runs `next typegen` first (needed for `LayoutProps` and similar types).
- LiteLLM would `load_dotenv()` on import; `llm/litellm_client.py` sets `LITELLM_MODE=PRODUCTION` first so secrets only flow through `Settings`. Tests clear all Settings env vars (autouse fixture in `apps/api/tests/conftest.py`).
- Claude tasks fall back to the same model on OpenRouter (`OPENROUTER_API_KEY`; ids use dots, `openrouter/anthropic/claude-sonnet-5.5`) before OpenAI. OpenAI tool turns send `reasoning_effort=none`: with reasoning on, LiteLLM bridges gpt-5.4+ tool calls to its Responses API, which imports an MCP gateway that needs mcp>=2.
- LlamaIndex gotchas: `PGVectorStore` HYBRID mode just concatenates dense + full-text results (we fuse with our own RRF in `knowledge/retriever.py`); stored `doc_id` comes from the node's SOURCE relationship (`ingestion/pipeline.py:to_node`); filter values are interpolated into SQL, so `knowledge/backends.py` whitelists them.
- `llama-cloud` 2.x is the LlamaParse SDK (`llama-cloud-services` is deprecated). The Cohere key is a production (pay-as-you-go) key.
- MCP: `mcp` is pinned `<2` (FastMCP 1.x, ADR-006). The agent calls the servers through `homehelper.agent.tools.McpToolbox` (in-memory sessions, ADR-008), not `langchain-mcp-adapters`. Mounted servers only answer once the app lifespan has run (`async with app.router.lifespan_context(app)` in tests). Open the in-memory MCP client (`mcp.shared.memory`) inside the test, not in an async fixture: pytest-asyncio tears fixtures down in another task, which anyio rejects.
- ruff must not touch Markdown: `*.md` is excluded in `pyproject.toml` because ruff formats Python code blocks inside it.

## Shared contracts — import these, don't redefine them

| Contract | Module |
|---|---|
| `LLMClient` protocol (`structured`, `text`, `tool_turn`), `Message`, `ToolSpec`, `ToolTurn`, `LLMError`, `LLMUsage` | `homehelper.llm` (`types.py`) |
| `LiteLLMClient` (fallbacks, structured output + one corrective retry, cost) / `FakeLLMClient` (scripted) | `homehelper.llm`; build with `build_llm_client(settings)` |
| Task → model mapping | `apps/api/src/homehelper/llm/models.yaml` (`ModelRegistry.load(overrides=...)`) |
| `CategoryId`, `ChunkMetadata`, `RetrievedChunk`, `Citation`, `RetrievalQuery`, `RetrievalResult`, `WebFinding` | `homehelper.knowledge.schemas` |
| `InboundMessage`, `StructuredAction`, cards, `AgentEvent` | `homehelper.channels.events` |
| `AgentRuntime` protocol, `AgentSnapshot`, `Outcome` | `homehelper.agent.protocol` |
| dev/test split | `data/scenarios/splits.json` via `homehelper_evals.splits` (`--check` verifies it is current) |
| Per-turn LLM cost: `with track_usage() as tally:` collects every call in scope (contextvar, follows tasks) | `homehelper.llm` (`usage.py`) |
| Agent injection: `create_app(settings, agent=...)` → `app.state.agent`; defaults to the scripted `StubAgent` | `homehelper.main`, `homehelper.agent.stub` |
| MCP tool registry: read/write, LLM-callable (`LLM_CALLABLE_TOOLS`, `WRITE_TOOLS`) | `homehelper.mcp_servers.registry` |
| Agent MCP client: `Toolbox` protocol, `McpToolbox` (LLM whitelist + `user_id` binding, `call_action` for step actions), `ToolOutcome` | `homehelper.agent.tools` |
| MCP servers: `build_mcp_servers(settings, engine=..., overrides=McpOverrides(...))`, mounted at `/mcp/<server>/` | `homehelper.mcp_servers.factory`; records in `homehelper.mcp_servers.schemas` |
| Web API: `ConversationService` (turn → `messages` rows), `WebChannelAdapter` (SSE), `TurnGuards` (rate limits, spend cap, conversation lock) | `homehelper.conversations.service`, `homehelper.channels.web`, `homehelper.ratelimit` |
| Uploads: `MediaStore` (local / GCS, signed URLs), `build_media_store`, `MediaSigner`; checks in `validation`, `images`, `video`, `pipeline` | `homehelper.media` (`storage.py`, `signing.py`) |
| Media for the agent: `MediaSource` protocol, `AttachmentMediaSource` / `FakeMediaSource`; `VisionResult`, `VideoResult`, `MediaObservation` | `homehelper.media.source`, `homehelper.media.fake`, `homehelper.media.schemas` |
| Video model: `VideoAnalyzer` protocol, `GeminiVideoAnalyzer`, `build_video_analyzer` (None without `GEMINI_API_KEY`) | `homehelper.media.gemini` |
| Quality loop (spec §17.2, ADR-010): `IssueType`, admin-wide review queries, `RegressionCase` (export contract; `EvalCase` loads it), `build_case`/`suggest` (annotation → case), `eval_reports` (report summaries for `/admin/evals`) | `homehelper.quality` (`schemas`, `repository`, `regression`, `export`, `eval_reports`) |
| Admin auth: `require_admin` accepts `X-Admin-Token` or the `hh_admin` cookie (`AdminSigner`; `POST /v1/admin/session` exchanges the token) | `homehelper.api.deps`, `homehelper.api.admin` |
| Caller IP for rate limits: `client_ip(request, settings)` (trusts the web proxy's `X-HH-Client-IP` only with `PROXY_SECRET`) | `homehelper.api.deps` |
| Per-driver `DATABASE_URL` (asyncpg / psycopg / psycopg2; Neon's `sslmode`) — never pass the raw URL to a driver | `homehelper.db.urls` |
| Release at startup: `RELEASE_MANIFEST` (JSON) or `releases/<id>.yaml`; without one, production needs `KB_VERSION` (a main build, recorded with `GIT_SHA`) | `homehelper.releases.runtime` |
| Eval plug-in for agents (`evals run --agent module:builder`): builder takes `AgentContext` (settings, usage sink, `registry` with `--models` overrides — build LLM clients with it), returns `AgentFactory` | `homehelper_evals.agents`; cases are `homehelper_evals.cases.EvalCase` |

Changing a contract means updating every caller in the same PR and saying so in the PR description.

## Parallel development (spec §19)

Several sessions may work at once, each in its own worktree and branch. Stay inside your track's directories. Wave 2 tracks:

| Track | Branch | Owns |
|---|---|---|
| A — M2-06 baseline + M3 agent runtime | `m2-baseline`, then `m3-agent-runtime` | `homehelper/agent/` except `stub.py`; `homehelper/knowledge/`; `evals/` (new datasets and agent builders); `docs/reports/` |
| D — M4 API, channel, web | `m4-api-web` | `homehelper/api/`, `homehelper/channels/` (`events.py`: additive only), `homehelper/conversations/`, `homehelper/ratelimit/`, `homehelper/db/` (app-table migrations), `homehelper/agent/stub.py`, `apps/web/` |
| E — M5 MCP servers & mock data | `m5-mcp-servers` | `homehelper/mcp_servers/`, `data/mock/`, the mock-table migration |

Boundaries that keep the tracks apart (spec v0.8):
- The agent writes only its LangGraph checkpointer. The API's conversation service builds `messages` rows from the `AgentEvent` stream and fills `cost_usd` from `track_usage()`.
- D and E both add Alembic migrations. Whoever merges second points its `down_revision` at the other's head, so there is always exactly one head (`alembic heads`).
- `main.py` gets additive edits only: D mounts routers, E mounts the MCP sub-apps.

- Shared files (`pyproject.toml`, `uv.lock`, `Makefile`, `.github/workflows/ci.yml`, `CLAUDE.md`, `docs/SPEC.md`) get additive edits only. On a `uv.lock` conflict, take either side and rerun `uv lock`.
- Only edit the spec sections for your track, plus one Appendix D change-log line.
- Whoever finishes first merges first; the others rebase onto `main`.
- A new worktree has no `.env` (it is git-ignored): copy it from the main checkout before running anything that needs keys. PDFs (`data/manuals/pdfs/`) exist only in the main checkout.

## Conventions

- Branch per milestone (e.g. `m1-knowledge-base`), one commit per task, Conventional Commits (`feat(agent): ...`), PR into `main`; CI must be green before merge.
- Secrets only in `.env` (git-ignored); add new variable names to `.env.example`. gitleaks runs in pre-commit and CI.
- Manual PDFs, parsed output, and media never go into git.
- Every external dependency (LLM, MCP tools) must have a fake/mock implementation for tests (spec P6).
- Hard rules from the spec:
  - Journey Engine `transition()` and predicates are pure functions; coverage ≥ 90%.
  - YAML journeys reference predicates by name — no arbitrary expressions.
  - All LLM outputs are Pydantic-validated structured outputs.
  - Write-type MCP tools (`book`, `add_*`) are only called by code in step actions, never exposed to the LLM.
  - Hazard replies are fixed templates, never LLM-generated.
- Use the latest stable versions of libraries at implementation time; verify APIs against current docs rather than memory.
- After implementing new code, launch a fresh-context agent (not a fork, and not the agent that wrote the code) to review the diff before pushing or opening a PR. Fix the confirmed findings, and say in the PR description what the review found.
