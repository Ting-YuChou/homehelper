#!/usr/bin/env bash
# GitHub Actions only: export the named Secret Manager secrets that exist into the job's
# environment, masked in the logs. Missing ones are skipped (an optional provider key).
#
#   infra/gcp/ci-secrets.sh DATABASE_URL OPENAI_API_KEY ...
set -euo pipefail
: "${GCP_PROJECT_ID:?set GCP_PROJECT_ID}" "${GITHUB_ENV:?only for GitHub Actions}"
for name in "$@"; do
  if ! value=$(gcloud secrets versions access latest --secret "$name" --project "$GCP_PROJECT_ID" 2>/dev/null); then
    echo "skip $name (no such secret)"
    continue
  fi
  [[ -n "$value" ]] || continue
  # A mask covers one line; mask every line of a multi-line value.
  while IFS= read -r line; do
    if [[ -n "$line" ]]; then echo "::add-mask::$line"; fi
  done <<<"$value"
  delimiter="EOF_$(openssl rand -hex 8)"
  printf '%s<<%s\n%s\n%s\n' "$name" "$delimiter" "$value" "$delimiter" >>"$GITHUB_ENV"
  echo "loaded $name"
done
