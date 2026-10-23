# ADR-011: Cloud deployment details: same-origin proxy, manifests on the revision, continuous main

- **Status:** Accepted
- **Date:** 2026-10-23
- **Spec:** §10.2, §11.1, §16.5, §17.3, §18.3–§18.4, Q10, Q11
- **Amends:** [ADR-005](005-cloud-run-deployment.md)

## Context

ADR-005 chose Cloud Run, Neon, Upstash, GCS and Workload Identity Federation. Building the M8
deployment exposed gaps that it did not settle:

1. On Cloud Run the web app and the API are two `*.run.app` sites. `run.app` is on the Public
   Suffix List, so browsers never send the API's `SameSite=Lax` session cookie on the web app's
   fetches (spec Q11).
2. The release manifest is not in the image, but the API in production refuses to start
   without one, and Cloud Run has no checkout of `releases/` to read.
3. Every push to main should deploy (M8-02), but a release manifest is produced only by the
   eval-gated `release.yml`.
4. Behind any front end, every visitor's requests seem to come from the same IP, so the
   per-IP rate limits would be shared by everyone.
5. Cloud Run refuses HTTP/1 requests over 32 MiB, but videos were allowed up to 100 MB.
6. Should the public demo serve the manual PDFs (spec Q10)?
7. Neon hands out `postgresql://...?sslmode=require&channel_binding=require`, which asyncpg
   rejects, and its pooler refuses the checkpointer's `search_path` startup option.

## Decision

1. **The web app proxies `/v1` to the API.**
   - A catch-all Route Handler (`apps/web/app/v1/[...path]/route.ts`) streams each request to the
     API (`API_URL`, read at request time) and streams the response back: SSE chunks pass
     through unbuffered, uploads are not buffered, and every `Set-Cookie` is kept.
   - The browser only talks to the web origin, so the cookies are first-party and the Origin
     check needs no change. The web image no longer bakes in an API URL.
   - Rejected: a shared custom domain. It needs a domain and DNS, and Cloud Run domain mappings
     are still in Preview; a load balancer costs about $18 a month. `SameSite=None` cookies
     are blocked by Safari.
2. **The manifest travels with the Cloud Run revision.**
   - `release.yml` passes the manifest as JSON in `RELEASE_MANIFEST`. Its `id` must equal
     `RELEASE_ID`. The file in `releases/` still works locally.
   - An environment variable belongs to the revision, so rolling traffic back to an earlier
     revision rolls the manifest back with it: the image digest plus the revision is the
     immutable release.
   - Rejected: mounting a bucket of manifests, which adds a cold-start mount and a second
     source of truth; reading manifests from the database, which would have to happen before
     the app's lifespan opens a connection.
3. **Main deploys continuously; releases are gated on top.**
   - `deploy.yml` runs after CI passes on main.
     - It builds `api:<sha>` and `web:<sha>` and runs the migrate job.
     - It deploys each service as a no-traffic `candidate`, smoke-tests it (the API's
       `/readyz` and `git_sha`; the Playwright chat tests against the web candidate), then
       moves traffic.
   - Its release is `main-<sha7>`: no manifest, models from `models.yaml`, and the KB pinned by
     the `KB_VERSION` variable. Production still refuses to start with neither a manifest nor
     `KB_VERSION`.
   - The image carries `GIT_SHA`, so the build records a `releases` row and its conversations
     join to a commit.
   - `release.yml` evaluates the commit the API serves (or a given one) and drafts the
     manifest with the image digest. When the gates pass, it deploys those exact digests with
     the manifest and opens a PR that commits `releases/<id>.yaml`.
   - The next deploy of main replaces the release. The project owner chose this over gating
     every deploy behind a paid eval run.
   - **Only one workflow at a time moves traffic.** Deploy and release share the `cloud-run`
     concurrency group, and promotion targets the revision the `candidate` tag points at, not
     the newest one.
   - **A release never rolls production back.** It refuses to deploy when main was deployed
     while its evals ran.
   - **"The commit production runs" comes from the live API's `/v1/meta`,** not from a service
     label: a label changes when a deploy starts, even if its smoke test then fails.
4. **The proxy vouches for the visitor's IP.**
   - Cloud Run appends the connecting address to `X-Forwarded-For`, so its last entry is the
     one a visitor can't forge. The proxy sends that address in `X-HH-Client-IP`, together
     with `PROXY_SECRET`.
   - The API believes that header only with the secret. Otherwise it takes the last
     `X-Forwarded-For` entry, and locally the socket peer.
   - All per-IP limits use `client_ip()`.
5. **Videos are capped at 30 MB** everywhere, so an upload plus its multipart wrapper fits one
   Cloud Run request. The 60 s limit is unchanged. Uploading straight to GCS with resumable
   signed URLs would lift the cap; it isn't worth the complexity yet.
6. **The demo serves no PDFs** (Q10). The API image has none, so a manual's `url` is null, and
   a citation shows the manual's name and page. PDFs live in the private manuals bucket, and
   only the ingest job reads them.
7. **One `DATABASE_URL`, spelled per driver.**
   - `homehelper.db.urls` derives the asyncpg (`ssl=`), psycopg (`sslmode=`) and psycopg2
     forms. Neon is used through its **direct** (non-pooler) endpoint.
   - The API runs at most two instances, which keeps it within the free tier's connection
     limit.
8. **The cloud operations are scripted rather than written in Terraform.**
   - `infra/gcp/bootstrap.sh` sets up the APIs, Artifact Registry, buckets, least-privilege
     service accounts, WIF limited to this repository, and a budget. `infra/gcp/secrets.sh`
     copies `.env.cloud` into Secret Manager without printing values.
   - `infra/gcp/cloudrun.sh` holds the deploy steps that `deploy.yml` and `release.yml` share.
     `infra/gcp/monitoring.py` sets up the alerts.
   - Every script accepts `--dry-run`. Secrets live only in Secret Manager; GitHub holds
     non-secret variables, and workflows read secrets through WIF.
   - Two identities act through WIF:
     - `gh-deployer` can change production. Only workflows running on `main` may use it:
       deploy, release and ingest.
     - Pull-request evals run PR code, so they use `hh-evals`, which can only read the eval
       secrets.
9. **Jobs and evals.**
   - `migrate` runs `homehelper db upgrade`, since the image has no `alembic.ini`.
   - `ingest` mounts the manuals bucket's `pdfs/` and `parsed/` where the pipeline reads them.
     Its retention also keeps every `kb_version` that a `releases` row pins, because the cloud
     has no `releases/` checkout.
   - There is **no eval job**. The evals package is not in the API image, so evals run in
     GitHub Actions: `release.yml`, `ingest.yml`, and the PR `Evals` workflow (retrieval on
     retrieval changes, smoke on `run-eval`).
10. **Monitoring** uses log lines the API writes: `turn.completed` (duration, cost, outcome) and
    `spend.threshold_crossed` (80% and 100% of the daily cap). On top of them come uptime
    checks, a 5xx ratio, p95 turn latency and spend alerts. Cloud Run's own latency metric is
    not used, because SSE turns stretch it.
11. **Region: `us-west1` (Oregon)**, next to Neon and Upstash in AWS `us-west-2`, and close to
    the US-hosted LLM APIs.

## Consequences

- One image per service runs in every environment; nothing environment-specific is built in.
- Every browser request takes one more hop through the web service: a few milliseconds, and
  the web service has to stay up for the API to be reachable from browsers.
- **The API is still public.** It has its own authentication and limits, and a caller who
  bypasses the proxy is identified by the address Cloud Run saw.
- Between the API's promotion and the web app's there are a few minutes of new API with old
  web. API changes are additive, so this is safe.
- A gated release lasts until the next push to main. Conversations record their `release_id`,
  so A/B data stays clean.
- Main-only deploys spend a few cents per deploy on the smoke tests, and those count toward
  the daily cap.
- Old revisions keep their manifests; rollback is `gcloud run services update-traffic`
  (`docs/deploy.md`).
