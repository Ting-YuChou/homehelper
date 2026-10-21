# ADR-003: LlamaIndex for ingestion and retrieval, Postgres + pgvector for storage

- **Status:** Accepted
- **Date:** 2026-10-21
- **Spec:** §10

## Context

v1 answered from live web search and never used its 98 manual PDFs, so answers had no grounding. v2 must cite manual pages for every repair step (P3) and filter by appliance category, brand, and model. Manuals are heavy on tables (troubleshooting, error codes), which naive text extraction breaks.

## Decision

- **LlamaParse** converts PDFs to Markdown with tables and page numbers preserved. Results are cached by PDF hash so unchanged manuals are never re-parsed.
- **LlamaIndex** handles chunking (Markdown structure first, then size; troubleshooting tables kept whole) and retrieval. It does **not** generate answers; the agent's `responder` does.
- **Postgres + pgvector** stores chunks with hybrid search (vector + full text, fused with RRF), then Cohere rerank.
- Metadata filters relax step by step: model pattern → brand + category → category → all.
- Each knowledge-base build is a frozen `kb_version` in its own table. A release pins a `kb_version`, so retrieval changes are versioned and reversible.

## Consequences

- One database for application data, agent checkpoints, and vectors: fewer services and simple local development.
- Frozen KB tables make retrieval evals reproducible and allow rollback.
- Hybrid search handles exact tokens (model numbers, error codes like `OE`) that pure vector search misses.
- We depend on hosted LlamaParse and Cohere; both have fallbacks (cached parses, skipping rerank).

## Alternatives considered

- **Dedicated vector DB (Pinecone, Qdrant, Weaviate):** another service to run and pay for, with no real benefit at about 100 manuals.
- **Local PDF parsing (pypdf, unstructured):** free, but table quality is noticeably worse, and tables are where the troubleshooting answers live.
- **LlamaIndex query engines for generation:** would bypass the journey and supervisor layers.
