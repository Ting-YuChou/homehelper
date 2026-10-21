# ADR-005: Deploy on Cloud Run with managed Postgres and Redis

- **Status:** Accepted
- **Date:** 2026-10-21
- **Spec:** §17.3, §18.3, §18.4

## Context

This is a portfolio project: traffic is low and bursty, cost should be near zero when idle, and the deployment should still show production practices (immutable releases, canary checks, rollback, no long-lived credentials).

## Decision

- **Cloud Run services** for `api` and `web`, and **Cloud Run Jobs** for `migrate`, `ingest`, and `eval`. Images live in Artifact Registry; secrets in Secret Manager.
- **Neon** (Postgres + pgvector) and **Upstash** (Redis) as managed data stores; GCS for uploads, manuals, parse cache, and eval reports.
- **Releases:** an image digest plus a release manifest (`releases/<id>.yaml`: `git_sha`, `kb_version`, model mapping, eval reports, gates) together form an immutable release. The manifest is not baked into the image; the service loads it from `RELEASE_ID`. Conversations record their `release_id`.
- **Deploy flow:** build → run `migrate` job → deploy with `--no-traffic --tag candidate` → smoke test the candidate URL → shift 100% of traffic. Rollback means shifting traffic back to the previous revision.
- GitHub Actions authenticates to GCP with **Workload Identity Federation**, so no service-account keys are stored.

## Consequences

- Scales to zero; idle cost is close to nothing. Cold starts are a trade-off (min-instances can be raised to 1 during demos).
- SSE works on Cloud Run with a 300 s request timeout, heartbeats, and buffering disabled.
- Neon and Upstash live outside GCP, adding cross-provider latency and two more accounts.

## Alternatives considered

- **Cloud SQL + Memorystore:** everything inside GCP, but fixed monthly cost, and Memorystore needs a VPC connector.
- **GKE / Kubernetes:** far more operational surface than this project needs.
- **Vercel for the web app:** a great fit for Next.js, but splitting platforms complicates the one-command deploy and rollback story.
