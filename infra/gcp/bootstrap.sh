#!/usr/bin/env bash
# One-time GCP setup for HomeHelper (M8-01, ADR-011). Safe to re-run: what exists is kept.
#
#   infra/gcp/bootstrap.sh --project <PROJECT_ID> [--billing <BILLING_ACCOUNT_ID>]
#                          [--region us-west1] [--repo owner/name] [--dry-run]
#
# Creates the Artifact Registry repo, the media and manuals buckets, the service accounts and
# their roles, Workload Identity Federation for GitHub Actions, and (with --billing) a monthly
# budget. It creates no Cloud Run services or jobs: deploy.yml does, once there is an image.
# Secrets come next, from infra/gcp/secrets.sh; alerts from infra/gcp/monitoring.sh.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=common.sh
source "$HERE/common.sh"

PROJECT="" BILLING="" REGION=$REGION_DEFAULT REPO=$REPO_DEFAULT BUDGET_USD=10
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT=$2; shift 2 ;;
    --billing) BILLING=$2; shift 2 ;;
    --region) REGION=$2; shift 2 ;;
    --repo) REPO=$2; shift 2 ;;
    --budget-usd) BUDGET_USD=$2; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) die "unknown argument: $1" ;;
  esac
done
[[ -n "$PROJECT" ]] || die "--project is required"
require_gcloud
G=(--project "$PROJECT")

echo "== APIs"
run gcloud services enable "${G[@]}" \
  run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com \
  iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com storage.googleapis.com \
  monitoring.googleapis.com logging.googleapis.com cloudbilling.googleapis.com \
  billingbudgets.googleapis.com

echo "== Artifact Registry"
if ! exists gcloud artifacts repositories describe "$AR_REPO" --location "$REGION" "${G[@]}"; then
  run gcloud artifacts repositories create "$AR_REPO" --repository-format=docker \
    --location "$REGION" --description="HomeHelper images" "${G[@]}"
fi
# Keep the 10 newest versions of each image; delete older ones after 30 days.
POLICY=$(mktemp)
trap 'rm -f "$POLICY"' EXIT
cat >"$POLICY" <<'JSON'
[
  {"name": "keep-recent", "action": {"type": "Keep"}, "mostRecentVersions": {"keepCount": 10}},
  {"name": "delete-old", "action": {"type": "Delete"}, "condition": {"tagState": "any", "olderThan": "30d"}}
]
JSON
run gcloud artifacts repositories set-cleanup-policies "$AR_REPO" --location "$REGION" \
  --policy "$POLICY" --no-dry-run "${G[@]}"

echo "== Buckets (private; uniform access)"
for bucket in "${PROJECT}-media" "${PROJECT}-manuals"; do
  if ! exists gcloud storage buckets describe "gs://$bucket" "${G[@]}"; then
    run gcloud storage buckets create "gs://$bucket" --location "$REGION" \
      --uniform-bucket-level-access --public-access-prevention "${G[@]}"
  fi
done

echo "== Service accounts"
for name in "$API_SA_NAME" "$WEB_SA_NAME" "$JOBS_SA_NAME" "$DEPLOYER_SA_NAME"; do
  if ! exists gcloud iam service-accounts describe "$(sa_email "$name")" "${G[@]}"; then
    run gcloud iam service-accounts create "$name" --display-name="HomeHelper $name" "${G[@]}"
  fi
done
API_SA=$(sa_email "$API_SA_NAME")
WEB_SA=$(sa_email "$WEB_SA_NAME")
JOBS_SA=$(sa_email "$JOBS_SA_NAME")
DEPLOYER_SA=$(sa_email "$DEPLOYER_SA_NAME")

echo "== Roles"
# API: read and write uploads; sign GCS URLs through IAM signBlob (no key file).
run gcloud storage buckets add-iam-policy-binding "gs://${PROJECT}-media" \
  --member "serviceAccount:$API_SA" --role roles/storage.objectUser "${G[@]}"
run gcloud iam service-accounts add-iam-policy-binding "$API_SA" \
  --member "serviceAccount:$API_SA" --role roles/iam.serviceAccountTokenCreator "${G[@]}"
# Jobs (migrate, seed-mock, ingest): the manuals bucket holds PDFs and the parse cache.
run gcloud storage buckets add-iam-policy-binding "gs://${PROJECT}-manuals" \
  --member "serviceAccount:$JOBS_SA" --role roles/storage.objectUser "${G[@]}"
# Deployer (GitHub Actions): deploy services and jobs as the runtime accounts, push images,
# see which secrets exist, and read upload media for `evals regression pull`.
run gcloud projects add-iam-policy-binding "$PROJECT" \
  --member "serviceAccount:$DEPLOYER_SA" --role roles/run.admin --condition=None
run gcloud projects add-iam-policy-binding "$PROJECT" \
  --member "serviceAccount:$DEPLOYER_SA" --role roles/secretmanager.viewer --condition=None
run gcloud artifacts repositories add-iam-policy-binding "$AR_REPO" --location "$REGION" \
  --member "serviceAccount:$DEPLOYER_SA" --role roles/artifactregistry.writer "${G[@]}"
for sa in "$API_SA" "$WEB_SA" "$JOBS_SA"; do
  run gcloud iam service-accounts add-iam-policy-binding "$sa" \
    --member "serviceAccount:$DEPLOYER_SA" --role roles/iam.serviceAccountUser "${G[@]}"
done
run gcloud storage buckets add-iam-policy-binding "gs://${PROJECT}-media" \
  --member "serviceAccount:$DEPLOYER_SA" --role roles/storage.objectViewer "${G[@]}"

echo "== Workload Identity Federation (GitHub Actions of $REPO only)"
if ! exists gcloud iam workload-identity-pools describe "$WIF_POOL" --location global "${G[@]}"; then
  run gcloud iam workload-identity-pools create "$WIF_POOL" --location global \
    --display-name "GitHub Actions" "${G[@]}"
fi
if ! exists gcloud iam workload-identity-pools providers describe "$WIF_PROVIDER" \
  --workload-identity-pool "$WIF_POOL" --location global "${G[@]}"; then
  run gcloud iam workload-identity-pools providers create-oidc "$WIF_PROVIDER" \
    --workload-identity-pool "$WIF_POOL" --location global \
    --issuer-uri "https://token.actions.githubusercontent.com" \
    --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
    --attribute-condition "assertion.repository == '$REPO'" "${G[@]}"
fi
NUMBER=$(gcloud projects describe "$PROJECT" --format 'value(projectNumber)' 2>/dev/null || echo PROJECT_NUMBER)
POOL_ID="projects/$NUMBER/locations/global/workloadIdentityPools/$WIF_POOL"
run gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER_SA" \
  --member "principalSet://iam.googleapis.com/$POOL_ID/attribute.repository/$REPO" \
  --role roles/iam.workloadIdentityUser "${G[@]}"

if [[ -n "$BILLING" ]]; then
  echo "== Budget (${BUDGET_USD} USD a month; email alerts go to the billing account's admins)"
  NAME="HomeHelper monthly"
  if [[ -z "$(gcloud billing budgets list --billing-account "$BILLING" \
    --filter "displayName=\"$NAME\"" --format 'value(name)' 2>/dev/null)" ]]; then
    run gcloud billing budgets create --billing-account "$BILLING" --display-name "$NAME" \
      --budget-amount "${BUDGET_USD}USD" --filter-projects "projects/$PROJECT" \
      --threshold-rule percent=0.5 --threshold-rule percent=0.9 --threshold-rule percent=1.0
  fi
fi

cat <<OUT

Done. Next:
  1. infra/gcp/secrets.sh --project $PROJECT --env-file .env.cloud
  2. Set the GitHub Actions variables (none of these is a secret):
     gh variable set GCP_PROJECT_ID --body "$PROJECT"
     gh variable set GCP_PROJECT_NUMBER --body "$NUMBER"
     gh variable set GCP_REGION --body "$REGION"
     gh variable set GCP_WIF_PROVIDER --body "$POOL_ID/providers/$WIF_PROVIDER"
     gh variable set GCP_DEPLOYER_SA --body "$DEPLOYER_SA"
OUT
