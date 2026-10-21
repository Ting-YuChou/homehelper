# HomeHelper

An appliance-repair support agent that walks users through troubleshooting one step at a time, grounds every step in the manufacturer's manual, and hands dangerous situations to a professional.

The design follows Sierra's agent approach: the LLM understands and expresses, while code controls the flow and the policies, and every change is measured with τ-bench-style simulated conversations.

> **Status:** under active development. Milestone M0 (foundation) is in progress. See [`docs/SPEC.md`](docs/SPEC.md) §19 for the roadmap.

## Architecture (planned)

- **API:** FastAPI, with a fixed LangGraph pipeline that runs declarative YAML journeys ([ADR-002](docs/adr/002-declarative-journeys-on-langgraph.md))
- **Knowledge:** LlamaParse, LlamaIndex, and Postgres + pgvector with hybrid search and rerank ([ADR-003](docs/adr/003-llamaindex-and-pgvector.md))
- **Integrations:** MCP servers for user profile, parts, tutorials, booking, and web search ([ADR-004](docs/adr/004-mcp-for-external-integrations.md))
- **Web:** Next.js chat UI that streams over SSE
- **Ops:** Langfuse tracing, Cloud Run, and GitHub Actions ([ADR-005](docs/adr/005-cloud-run-deployment.md))

## Local development

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/), [pnpm](https://pnpm.io/), and Node 24+.

```bash
cp .env.example .env      # fill in keys; tracing stays off without Langfuse keys
uv sync
pnpm install
pre-commit install
make up                   # postgres, redis, api (:8000), web (:3000)
```

| Command | What it does |
|---|---|
| `make up` / `make down` | Start or stop the local stack |
| `make test` | Unit tests |
| `make test-integration` | Unit + integration tests (needs `make up`) |
| `make lint` | ruff, pyright, eslint, tsc |
| `make fmt` | Auto-format Python |

Health checks: `GET /healthz` (liveness) and `GET /readyz` (Postgres + Redis).

## Repository layout

See [`CLAUDE.md`](CLAUDE.md) and [`docs/SPEC.md`](docs/SPEC.md) §6. The v1 prototype is kept in `legacy/` for reference.

## Data

Manual PDFs are not committed (copyright and size). They live in `data/manuals/pdfs/` locally and in a private bucket in production. `data/manuals/manifest.yaml` lists them.
