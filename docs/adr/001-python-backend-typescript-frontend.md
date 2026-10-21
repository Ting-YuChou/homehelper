# ADR-001: Python backend, TypeScript frontend

- **Status:** Accepted
- **Date:** 2026-10-21
- **Spec:** §4, §4.1

## Context

The backend is dominated by LLM orchestration, retrieval, and evaluation. The frontend is a chat UI with streaming and interactive cards. The v1 data tooling (scenario generation, evaluation) is already Python.

## Decision

The API, agent runtime, ingestion, MCP servers, and evals are Python 3.12 (FastAPI, Pydantic v2, SQLAlchemy 2.0 async), managed as a `uv` workspace. The web app is TypeScript on Next.js (App Router), managed with `pnpm`. TypeScript API types are generated from the FastAPI OpenAPI schema with `openapi-typescript`, and CI fails if the generated types drift.

## Consequences

- We use the most mature versions of LlamaIndex (hybrid PGVector retrieval, Cohere rerank, LlamaParse) and LangGraph (Postgres checkpointer).
- Two toolchains in one repo: CI runs separate Python and web jobs.
- The OpenAPI schema is the contract between the two languages; backend response models must be explicit.

## Alternatives considered

- **TypeScript end to end:** one language, but LlamaIndex.TS and LangGraph.js lag their Python counterparts, and the eval/data tooling would need a rewrite.
- **Python end to end (server-rendered UI):** simpler deployment, but a weak fit for a streaming, card-based chat UI and a poorer portfolio signal for frontend work.
