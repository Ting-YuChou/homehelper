# Shared by the infra/gcp scripts (sourced, not run). ADR-011 describes what they set up.
# shellcheck shell=bash
# shellcheck disable=SC2034  # the variables are used by the scripts that source this

REGION_DEFAULT=us-west1
REPO_DEFAULT=Ting-YuChou/homehelper
DRY_RUN=0

# Names every script and workflow agrees on.
AR_REPO=homehelper
API_SERVICE=homehelper-api
WEB_SERVICE=homehelper-web
API_SA_NAME=hh-api
WEB_SA_NAME=hh-web
JOBS_SA_NAME=hh-jobs
DEPLOYER_SA_NAME=gh-deployer
WIF_POOL=github
WIF_PROVIDER=github-actions

die() {
  echo "error: $*" >&2
  exit 1
}

# Print a command, then run it unless --dry-run.
run() {
  printf '+'
  printf ' %q' "$@"
  printf '\n'
  if [[ "$DRY_RUN" == 0 ]]; then
    "$@"
  fi
}

# True when a read-only command succeeds (used to skip creating what exists).
exists() {
  "$@" >/dev/null 2>&1
}

sa_email() {
  echo "$1@${PROJECT}.iam.gserviceaccount.com"
}

require_gcloud() {
  command -v gcloud >/dev/null || die "install the gcloud CLI first: brew install --cask gcloud-cli"
  [[ -n "$(gcloud config get-value account 2>/dev/null)" ]] || die "run 'gcloud auth login' first"
}
