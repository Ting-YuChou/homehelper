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
apps/api/        Python 3.12 · FastAPI · package `homehelper` (src layout)
apps/web/        TypeScript · Next.js (App Router)
mcp_servers/     MCP servers (FastMCP), each with real|mock mode
evals/           uv workspace member, package `homehelper_evals`: splits, retrieval eval, simulator, graders, runner
data/            manifest, scenarios, mock data (PDFs/media are git-ignored)
releases/        release manifests
infra/           Dockerfiles, docker-compose, Cloud Run config
legacy/          v1 code, reference only — do not import from it; deleted in M3-12
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
make lint               # ruff check/format --check, pyright, eslint, tsc
make fmt
pnpm --filter web build
```

- Run the API without Docker: `uv run uvicorn homehelper.main:create_app --factory --reload` (it is an app factory; there is no module-level `app`).
- Tests build the app with `create_app(make_settings(...))` from `apps/api/tests/conftest.py`; settings never read `.env` in tests.
- Integration tests are marked `@pytest.mark.integration` and skipped unless `RUN_INTEGRATION=1` (CI sets it, with Postgres/Redis service containers).
- `apps/web` uses Next.js 16, which differs from older versions: read `apps/web/AGENTS.md` and the docs in `apps/web/node_modules/next/dist/docs/` before writing web code. `pnpm typecheck` runs `next typegen` first (needed for `LayoutProps` and similar types).
- ruff must not touch Markdown: `*.md` is excluded in `pyproject.toml` because ruff formats Python code blocks inside it.

## Shared contracts (Wave 0) — import these, don't redefine them

| Contract | Module |
|---|---|
| `LLMClient` protocol, `Message`, `LLMError`, `LLMUsage` | `homehelper.llm` (`types.py`) |
| `LiteLLMClient` (fallbacks, structured output + one corrective retry, cost) / `FakeLLMClient` (scripted) | `homehelper.llm`; build with `build_llm_client(settings)` |
| Task → model mapping | `apps/api/src/homehelper/llm/models.yaml` (`ModelRegistry.load(overrides=...)`) |
| `CategoryId`, `ChunkMetadata`, `RetrievedChunk`, `Citation`, `RetrievalQuery`, `RetrievalResult`, `WebFinding` | `homehelper.knowledge.schemas` |
| `InboundMessage`, `StructuredAction`, cards, `AgentEvent` | `homehelper.channels.events` |
| `AgentRuntime` protocol, `AgentSnapshot`, `Outcome` | `homehelper.agent.protocol` |
| dev/test split | `data/scenarios/splits.json` via `homehelper_evals.splits` (`--check` verifies it is current) |

Changing a contract means updating every caller in the same PR and saying so in the PR description.

## Parallel development (spec §19)

Several sessions may work at once, each in its own worktree and branch. Stay inside your track's directories:

| Track | Branch | Owns |
|---|---|---|
| A — M1 knowledge base | `m1-knowledge-base` | `homehelper/knowledge/`, `homehelper/ingestion/`, `homehelper/db/` (Alembic), `homehelper/cli.py`, `evals/homehelper_evals/retrieval/`, `data/manuals/`, `config/web_whitelist.yaml` |
| B — M2 eval framework | `m2-eval-framework` | `evals/` except `homehelper_evals/retrieval/` and `splits.py`; `data/scenarios/` except `splits.json` |
| C — M3 journey engine & guardrails | `m3-journey-engine` | `homehelper/agent/engine/`, `homehelper/agent/guardrails/`, `homehelper/agent/journeys/`, `homehelper/agent/state.py` |

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
