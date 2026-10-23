#!/usr/bin/env bash
# Cloud Run deploy steps shared by deploy.yml and release.yml (M8-02, ADR-011).
#
#   cloudrun.sh jobs       --image <api image>            deploy the migrate/seed-mock/ingest jobs
#   cloudrun.sh run-job    <migrate|seed-mock|ingest>     execute a job and wait
#   cloudrun.sh deploy-api --image <img> --sha <sha> --release-id <id>
#                          [--kb-version <kb>] [--manifest <file.json>]
#   cloudrun.sh deploy-web --image <img> --sha <sha>
#   cloudrun.sh promote    <api|web>                      send 100% of traffic to the candidate
#   cloudrun.sh url        <api|web> [--candidate]
#
# A deploy creates a revision with no traffic under the `candidate` tag (the first deploy of a
# service has nothing to protect and goes live directly); `promote` moves traffic once the
# workflow's smoke test passed. Project and region come from GCP_PROJECT_ID, GCP_REGION and
# GCP_PROJECT_NUMBER (the GitHub Actions variables bootstrap.sh prints). --dry-run prints.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=common.sh
source "$HERE/common.sh"

PROJECT=${GCP_PROJECT_ID:?set GCP_PROJECT_ID}
REGION=${GCP_REGION:-$REGION_DEFAULT}
NUMBER=${GCP_PROJECT_NUMBER:?set GCP_PROJECT_NUMBER}
G=(--project "$PROJECT" --region "$REGION")
TAG=candidate

# Who reads which secret (must match secrets.sh). Only secrets that exist are mounted.
API_SECRETS="DATABASE_URL REDIS_URL SESSION_SECRET ADMIN_TOKEN PROXY_SECRET MCP_AUTH_TOKEN
  ANTHROPIC_API_KEY OPENAI_API_KEY OPENROUTER_API_KEY GEMINI_API_KEY COHERE_API_KEY
  TAVILY_API_KEY YOUTUBE_API_KEY LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY LANGFUSE_BASE_URL
  LANGFUSE_PROJECT_ID"
WEB_SECRETS="PROXY_SECRET"
JOB_SECRETS="DATABASE_URL OPENAI_API_KEY LLAMA_CLOUD_API_KEY"

service_name() {
  case "$1" in
    api) echo "$API_SERVICE" ;;
    web) echo "$WEB_SERVICE" ;;
    *) die "unknown service: $1 (api or web)" ;;
  esac
}

# The service's run.app URL (deterministic, so it is known before the first deploy).
url_of() {
  local prefix=""
  [[ "${2:-}" == "--candidate" ]] && prefix="${TAG}---"
  echo "https://${prefix}$(service_name "$1")-${NUMBER}.${REGION}.run.app"
}

# `--set-secrets` for the listed names that exist in Secret Manager.
secret_flags() {
  local existing pairs="" name
  existing=$(gcloud secrets list --project "$PROJECT" --format 'value(name)' 2>/dev/null |
    sed 's#.*/##' || true)
  for name in $1; do
    if grep -qx "$name" <<<"$existing"; then pairs+="${pairs:+,}$name=$name:latest"; fi
  done
  [[ -n "$pairs" ]] && echo "--set-secrets=$pairs"
  return 0
}

# Deploy flags that keep traffic where it is, unless the service is new.
traffic_flags() {
  if exists gcloud run services describe "$1" "${G[@]}"; then
    echo "--no-traffic --tag=$TAG"
  else
    echo "--tag=$TAG"
  fi
}

# An env vars file for gcloud (YAML), from KEY=VALUE arguments.
env_file() {
  local file pair
  file=$(mktemp)
  for pair in "$@"; do
    # JSON strings are valid YAML scalars and need no further escaping.
    printf '%s: %s\n' "${pair%%=*}" "$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "${pair#*=}")" >>"$file"
  done
  # No secrets go in here (those are --set-secrets), so a dry run may show it.
  [[ "$DRY_RUN" == 0 ]] || sed 's/^/    env /' "$file" >&2
  echo "$file"
}

cmd_jobs() {
  local image=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --image) image=$2; shift 2 ;;
      *) die "unknown argument: $1" ;;
    esac
  done
  [[ -n "$image" ]] || die "--image is required"
  local secrets common
  secrets=$(secret_flags "$JOB_SECRETS")
  common=(--image "$image" --service-account "$(sa_email "$JOBS_SA_NAME")" --max-retries 0
    --set-env-vars APP_ENV=production "${G[@]}")
  # shellcheck disable=SC2086  # secrets is one flag or nothing
  run gcloud run jobs deploy hh-migrate "${common[@]}" $secrets \
    --command homehelper --args db,upgrade --task-timeout 600s
  # shellcheck disable=SC2086
  run gcloud run jobs deploy hh-seed-mock "${common[@]}" $secrets \
    --command homehelper --args mcp,seed --task-timeout 600s
  # The manuals bucket holds the PDFs and the LlamaParse cache, mounted where ingest reads them
  # (Settings.data_dir is /app/data; the manual manifest ships in the image).
  # shellcheck disable=SC2086
  run gcloud run jobs deploy hh-ingest "${common[@]}" $secrets \
    --command homehelper --args ingest --task-timeout 3600s --memory 2Gi --cpu 2 \
    --execution-environment gen2 \
    --add-volume "name=pdfs,type=cloud-storage,bucket=${PROJECT}-manuals,readonly=true,mount-options=only-dir=pdfs" \
    --add-volume-mount volume=pdfs,mount-path=/app/data/manuals/pdfs \
    --add-volume "name=parsed,type=cloud-storage,bucket=${PROJECT}-manuals,mount-options=only-dir=parsed" \
    --add-volume-mount volume=parsed,mount-path=/app/data/parsed
}

cmd_run_job() {
  [[ $# -eq 1 ]] || die "usage: cloudrun.sh run-job <migrate|seed-mock|ingest>"
  run gcloud run jobs execute "hh-$1" --wait "${G[@]}"
}

cmd_deploy_api() {
  local image="" sha="" release="" kb="" manifest=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --image) image=$2; shift 2 ;;
      --sha) sha=$2; shift 2 ;;
      --release-id) release=$2; shift 2 ;;
      --kb-version) kb=$2; shift 2 ;;
      --manifest) manifest=$2; shift 2 ;;
      *) die "unknown argument: $1" ;;
    esac
  done
  [[ -n "$image" && -n "$sha" && -n "$release" ]] || die "--image, --sha and --release-id are required"
  [[ -n "$kb" || -n "$manifest" ]] || die "--kb-version or --manifest is required in production"
  local origins vars env secrets traffic
  # The browser's Origin for writes: the web app's URL and its candidate's (the smoke test).
  origins=$(printf '["%s","%s"]' "$(url_of web)" "$(url_of web --candidate)")
  vars=(APP_ENV=production "RELEASE_ID=$release" AGENT_RUNTIME=journey MCP_MODE=real
    MEDIA_BACKEND=gcs "GCS_MEDIA_BUCKET=${PROJECT}-media" "CORS_ORIGINS=$origins" LOG_LEVEL=INFO)
  [[ -n "$kb" ]] && vars+=("KB_VERSION=$kb")
  # The manifest travels with the revision (ADR-011); a rollback restores it.
  [[ -n "$manifest" ]] && vars+=("RELEASE_MANIFEST=$(tr -d '\n' <"$manifest")")
  env=$(env_file "${vars[@]}")
  secrets=$(secret_flags "$API_SECRETS")
  traffic=$(traffic_flags "$API_SERVICE")
  # shellcheck disable=SC2086  # secrets and traffic are flags or nothing
  run gcloud run deploy "$API_SERVICE" --image "$image" "${G[@]}" \
    --service-account "$(sa_email "$API_SA_NAME")" --env-vars-file "$env" $secrets $traffic \
    --labels "git-sha=$sha" --allow-unauthenticated --execution-environment gen2 \
    --timeout 300 --concurrency 20 --min-instances 0 --max-instances 2 --memory 1Gi --cpu 1 \
    --cpu-boost --startup-probe "httpGet.path=/healthz,initialDelaySeconds=0,periodSeconds=2,failureThreshold=30"
  rm -f "$env"
}

cmd_deploy_web() {
  local image="" sha=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --image) image=$2; shift 2 ;;
      --sha) sha=$2; shift 2 ;;
      *) die "unknown argument: $1" ;;
    esac
  done
  [[ -n "$image" && -n "$sha" ]] || die "--image and --sha are required"
  local env secrets traffic
  env=$(env_file "API_URL=$(url_of api)")
  secrets=$(secret_flags "$WEB_SECRETS")
  traffic=$(traffic_flags "$WEB_SERVICE")
  # shellcheck disable=SC2086
  run gcloud run deploy "$WEB_SERVICE" --image "$image" "${G[@]}" \
    --service-account "$(sa_email "$WEB_SA_NAME")" --env-vars-file "$env" $secrets $traffic \
    --labels "git-sha=$sha" --allow-unauthenticated \
    --timeout 300 --concurrency 80 --min-instances 0 --max-instances 2 --memory 512Mi --cpu 1
  rm -f "$env"
}

cmd_promote() {
  [[ $# -eq 1 ]] || die "usage: cloudrun.sh promote <api|web>"
  # The newest revision is the candidate the workflow just deployed and smoke-tested.
  run gcloud run services update-traffic "$(service_name "$1")" --to-latest "${G[@]}"
}

cmd_url() {
  url_of "$@"
}

[[ $# -gt 0 ]] || die "usage: cloudrun.sh <jobs|run-job|deploy-api|deploy-web|promote|url> ..."
command=$1
shift
ARGS=()
for arg in "$@"; do
  if [[ "$arg" == "--dry-run" ]]; then DRY_RUN=1; else ARGS+=("$arg"); fi
done
set -- ${ARGS[@]+"${ARGS[@]}"}
case "$command" in
  jobs) cmd_jobs "$@" ;;
  run-job) cmd_run_job "$@" ;;
  deploy-api) cmd_deploy_api "$@" ;;
  deploy-web) cmd_deploy_web "$@" ;;
  promote) cmd_promote "$@" ;;
  url) cmd_url "$@" ;;
  *) die "unknown command: $command" ;;
esac
