# Deploying HomeHelper

How the demo runs on Google Cloud, and how to set it up, ship it, roll it back and keep it
cheap. The design is in [ADR-005](adr/005-cloud-run-deployment.md) and
[ADR-011](adr/011-cloud-deployment-details.md).

## What runs where

| Piece | Where |
|---|---|
| Web app (`homehelper-web`) | Cloud Run, `us-west1`. Proxies `/v1` to the API. |
| API (`homehelper-api`) | Cloud Run, `us-west1`. Journey agent, MCP servers mounted in-process. |
| Jobs | Cloud Run Jobs: `hh-migrate`, `hh-seed-mock`, `hh-ingest` |
| Postgres + pgvector | Neon, AWS `us-west-2` (direct endpoint) |
| Redis | Upstash, AWS `us-west-2` |
| Uploads | GCS `<project>-media` (private; signed URLs) |
| Manual PDFs and parse cache | GCS `<project>-manuals` (private; only the ingest job reads it) |
| Images | Artifact Registry `homehelper` (10 newest kept) |
| Secrets | Secret Manager. GitHub only holds non-secret variables. |
| CI/CD | GitHub Actions with Workload Identity Federation (no keys) |

| Workflow | When | What |
|---|---|---|
| `ci.yml` | every PR, push to main | lint, tests, contract, E2E (stub agent), image builds |
| `evals.yml` | PRs | retrieval eval on retrieval changes; smoke suite with the `run-eval` label |
| `deploy.yml` | CI green on main | images → migrate → API candidate → smoke → traffic → web candidate → Playwright → traffic |
| `ingest.yml` | manual | new `kb_version` in the cloud, plus a retrieval eval |
| `release.yml` | manual | eval gates → manifest → deploy those digests → PR with the manifest |

## First-time setup

Never paste a key into a chat, an issue or a commit. Everything secret goes into `.env.cloud`
(git-ignored) and from there into Secret Manager.

### 1. Accounts

1. **Google Cloud**
   1. Sign in at <https://console.cloud.google.com> and turn on billing (a card is required;
      new accounts get trial credit).
   2. Create a project and note its **Project ID**.
   3. Note the **billing account ID** (Billing → Account management, `XXXXXX-XXXXXX-XXXXXX`).
2. **gcloud**
   1. Install it with `brew install --cask gcloud-cli`.
   2. Sign in with `gcloud auth login`.
   3. Run `gcloud config set project <PROJECT_ID>`.
3. **Neon** (<https://neon.com>)
   1. Create a project with Postgres 17 in **AWS US West 2 (Oregon)**.
   2. Under *Connect*, switch **Connection pooling off** and copy the connection string.
4. **Upstash** (<https://upstash.com>)
   1. Create a Redis database: Regional, **AWS us-west-2 (Oregon)**, Free.
   2. Copy the `rediss://` URL.
5. **Recommended: monthly usage limits** in the Anthropic, OpenAI and OpenRouter consoles.

### 2. `.env.cloud`

```bash
cp .env.cloud.example .env.cloud   # then edit it
```

- **Fill in:** `DATABASE_URL` (Neon), `REDIS_URL` (Upstash), and the provider keys (from `.env`).
- **Leave empty:** `SESSION_SECRET`, `ADMIN_TOKEN`, `PROXY_SECRET` and `MCP_AUTH_TOKEN`.
  `secrets.sh` generates them.

### 3. Cloud resources

```bash
infra/gcp/bootstrap.sh --project <PROJECT_ID> --billing <BILLING_ID> --dry-run   # look first
infra/gcp/bootstrap.sh --project <PROJECT_ID> --billing <BILLING_ID>
infra/gcp/secrets.sh --project <PROJECT_ID> --env-file .env.cloud
gcloud storage rsync -r data/manuals/pdfs gs://<PROJECT_ID>-manuals/pdfs
gcloud storage rsync -r data/parsed gs://<PROJECT_ID>-manuals/parsed
```

- The parse cache lets the cloud ingest skip LlamaParse. Only embeddings cost money, about
  $0.20.
- Run the `gh variable set ...` lines that `bootstrap.sh` printed.
- In the repository settings, enable **Settings → Actions → General → Workflow permissions →
  Allow GitHub Actions to create and approve pull requests**. This is for `release.yml`.

### 4. First deploy

1. Run **Deploy** (Actions → Deploy → Run workflow). It pushes the images, migrates and seeds
   the database, then stops: there is no knowledge base yet.
2. Run **Ingest**. Its summary shows the new `kb_version` and its retrieval metrics.
3. Set the version: `gh variable set KB_VERSION --body kb_YYYYMMDD_NN`.
4. Run **Deploy** again. The summary lists the web URL.
5. Set up the alerts:

   ```bash
   python3 infra/gcp/monitoring.py --project <PROJECT_ID> --email <you@example.com>
   ```

6. Check that it works:
   - Open the web URL, sign in as a demo user and run a troubleshooting chat.
   - Open `/admin` and sign in with the `ADMIN_TOKEN` from `.env.cloud`.

## Everyday operations

- **Ship:** merge to main. Changes that only touch `docs/`, `evals/`, `releases/` or Markdown
  files don't redeploy.
- **Gated release:** run **Release** with a release id (for example `r2026.11.01-1`).
  - It costs real LLM money: about $20–40 on production models. A `models` file such as
    `evals/models/opencode-go.yaml` costs less.
  - When the gates pass, it deploys and opens a PR with the manifest. Merge that PR; it
    doesn't redeploy.
  - The next push to main replaces the release.
- **New manuals:** add the PDFs to `data/manuals/pdfs/` and to the manifest, then upload them:
  `gcloud storage rsync -r data/manuals/pdfs gs://<PROJECT_ID>-manuals/pdfs`.
  - Then run **Ingest**, set `KB_VERSION`, and run **Deploy**.
  - The previous version stays available for rollback. Retention keeps the 5 newest versions
    plus any that a release pins.
- **Rotate a secret:** edit `.env.cloud`, run `infra/gcp/secrets.sh` (it adds a version only
  for values that changed), then run **Deploy**. Rotating `ADMIN_TOKEN` ends every admin
  session.

## Rollback

Each service rolls back separately. Revisions keep their environment, including
`RELEASE_MANIFEST`, so a rollback restores the release too.

```bash
gcloud run revisions list --service homehelper-api --region us-west1      # pick the previous one
gcloud run services update-traffic homehelper-api --region us-west1 --to-revisions <REVISION>=100
gcloud run services update-traffic homehelper-web --region us-west1 --to-revisions <REVISION>=100
```

A rollback doesn't undo migrations. Migrations are additive, so an older revision still runs
on the newer schema. The next deploy of main moves traffic to the new revision again.

## Costs

When idle, the demo should cost a few dollars a month:

| Item | Cost |
|---|---|
| Cloud Run | Scales to zero (min instances 0; set 1 during a demo for no cold starts) |
| Artifact Registry | Cents |
| Secret Manager | About $0.06 per active secret beyond the free 6, so about $1 |
| Neon, Upstash | Free tiers (Upstash: 500K commands a month) |
| Monitoring | Free tier |

- **LLM spend is capped by `DAILY_SPEND_CAP_USD`** (default $5). Over the cap, the API goes into
  maintenance mode until 00:00 UTC, and an alert fires at 80%.
- The GCP budget alert emails the billing admins at 50%, 90% and 100% of $10.
