#!/usr/bin/env bash
# Copy production settings from an env file into Secret Manager (M8-01, ADR-011). Prints names,
# never values. Safe to re-run: a secret gets a new version only when its value changed.
#
#   infra/gcp/secrets.sh --project <PROJECT_ID> [--env-file .env.cloud] [--dry-run]
#
# SESSION_SECRET, ADMIN_TOKEN, PROXY_SECRET and MCP_AUTH_TOKEN are generated (and written back
# to the env file) when they are empty. Empty values are skipped: deploy.yml only mounts the
# secrets that exist. Each secret is readable only by the accounts that use it.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=common.sh
source "$HERE/common.sh"

PROJECT="" ENV_FILE=$HERE/../../.env.cloud
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT=$2; shift 2 ;;
    --env-file) ENV_FILE=$2; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) die "unknown argument: $1" ;;
  esac
done
[[ -n "$PROJECT" ]] || die "--project is required"
[[ -f "$ENV_FILE" ]] || die "no $ENV_FILE (copy .env.cloud.example and fill it in)"
require_gcloud
G=(--project "$PROJECT")

GENERATED="SESSION_SECRET ADMIN_TOKEN PROXY_SECRET MCP_AUTH_TOKEN DEMO_ACCESS_CODE"
# Who reads what. The API runs the agent; the web app only needs the proxy secret; the jobs
# migrate and ingest; GitHub Actions runs the evals (release.yml, ingest.yml, retrieval in CI).
API_KEYS="DATABASE_URL REDIS_URL SESSION_SECRET ADMIN_TOKEN PROXY_SECRET MCP_AUTH_TOKEN
  DEMO_ACCESS_CODE ANTHROPIC_API_KEY OPENAI_API_KEY OPENROUTER_API_KEY GEMINI_API_KEY
  COHERE_API_KEY TAVILY_API_KEY YOUTUBE_API_KEY LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY
  LANGFUSE_BASE_URL LANGFUSE_PROJECT_ID"
WEB_KEYS="PROXY_SECRET"
JOBS_KEYS="DATABASE_URL OPENAI_API_KEY LLAMA_CLOUD_API_KEY"
DEPLOYER_KEYS="DATABASE_URL DEMO_ACCESS_CODE ANTHROPIC_API_KEY OPENAI_API_KEY OPENROUTER_API_KEY
  GEMINI_API_KEY COHERE_API_KEY OPENCODE_GO_API_KEY LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY
  LANGFUSE_BASE_URL LANGFUSE_PROJECT_ID"
# Pull-request evals (evals.yml): retrieval and the smoke suite.
EVALS_KEYS="DATABASE_URL ANTHROPIC_API_KEY OPENAI_API_KEY OPENROUTER_API_KEY COHERE_API_KEY
  LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY LANGFUSE_BASE_URL LANGFUSE_PROJECT_ID"
# shellcheck disable=SC2086  # the lists are split on purpose
ALL_KEYS=$(printf '%s\n' $API_KEYS $WEB_KEYS $JOBS_KEYS $DEPLOYER_KEYS $EVALS_KEYS | sort -u)

# The value of KEY in the env file (no shell evaluation; one pair of surrounding quotes removed).
value_of() {
  local line
  line=$(grep -E "^$1=" "$ENV_FILE" | tail -n 1 || true)
  line=${line#*=}
  line=${line%$'\r'}
  if [[ "$line" =~ ^\"(.*)\"$ || "$line" =~ ^\'(.*)\'$ ]]; then
    line=${BASH_REMATCH[1]}
  fi
  printf '%s' "$line"
}

set_value() {
  local tmp
  tmp=$(mktemp)
  grep -vE "^$1=" "$ENV_FILE" >"$tmp" || true
  printf '%s=%s\n' "$1" "$2" >>"$tmp"
  cat "$tmp" >"$ENV_FILE"
  rm -f "$tmp"
}

contains() {
  case " $(echo "$1" | tr '\n' ' ') " in *" $2 "*) return 0 ;; *) return 1 ;; esac
}

for key in $GENERATED; do
  if [[ -z "$(value_of "$key")" ]]; then
    echo "generating $key (written to $ENV_FILE)"
    # The access code is typed in by hand, so it is short; the login rate limit guards it.
    length=32
    [[ "$key" == DEMO_ACCESS_CODE ]] && length=5
    [[ "$DRY_RUN" == 1 ]] || set_value "$key" "$(openssl rand -hex "$length")"
  fi
done

for key in $ALL_KEYS; do
  value=$(value_of "$key")
  if [[ -z "$value" ]]; then
    echo "skip $key (empty)"
    continue
  fi
  if ! exists gcloud secrets describe "$key" "${G[@]}"; then
    run gcloud secrets create "$key" --replication-policy automatic "${G[@]}"
    current=""
  else
    current=$(gcloud secrets versions access latest --secret "$key" "${G[@]}" 2>/dev/null || true)
  fi
  if [[ "$value" != "$current" ]]; then
    echo "+ gcloud secrets versions add $key --data-file=- (value from $ENV_FILE)"
    [[ "$DRY_RUN" == 1 ]] || printf '%s' "$value" |
      gcloud secrets versions add "$key" --data-file=- "${G[@]}" >/dev/null
  else
    echo "unchanged $key"
  fi
  for pair in "$API_SA_NAME:$API_KEYS" "$WEB_SA_NAME:$WEB_KEYS" "$JOBS_SA_NAME:$JOBS_KEYS" \
    "$DEPLOYER_SA_NAME:$DEPLOYER_KEYS" "$EVALS_SA_NAME:$EVALS_KEYS"; do
    if contains "${pair#*:}" "$key"; then
      echo "+ grant ${pair%%:*} read access to $key"
      [[ "$DRY_RUN" == 1 ]] || gcloud secrets add-iam-policy-binding "$key" \
        --member "serviceAccount:$(sa_email "${pair%%:*}")" \
        --role roles/secretmanager.secretAccessor "${G[@]}" --quiet >/dev/null
    fi
  done
done
echo "Done. Redeploy (re-run the deploy workflow) for the services to pick up new values."
