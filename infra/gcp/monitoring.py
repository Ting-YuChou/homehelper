#!/usr/bin/env python3
"""Alerts for the deployed demo (M8-03, ADR-011). Run after the first deploy; safe to re-run.

    python3 infra/gcp/monitoring.py --project <PROJECT_ID> --email <ALERT_EMAIL> [--dry-run]

Creates an email notification channel, two log-based metrics, uptime checks for the web app and
the API, and four alert policies: an uptime check failing, 5xx above 5% of requests, p95 turn
latency above 30 s, and the day's LLM spend crossing 80% (and 100%) of DAILY_SPEND_CAP_USD.
Everything is matched by display name, so nothing is created twice. Uses the REST APIs with
`gcloud auth print-access-token`; standard library only.
"""

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API_SERVICE = "homehelper-api"
WEB_SERVICE = "homehelper-web"
CHANNEL_NAME = "HomeHelper alerts"
SERVICES = f'one_of("{API_SERVICE}", "{WEB_SERVICE}")'
TURNS = (
    f'resource.type="cloud_run_revision" AND resource.labels.service_name="{API_SERVICE}" '
    'AND jsonPayload.event="turn.completed"'
)
SPEND = (
    f'resource.type="cloud_run_revision" AND resource.labels.service_name="{API_SERVICE}" '
    'AND jsonPayload.event="spend.threshold_crossed"'
)


def log_metrics() -> list[dict[str, Any]]:
    return [
        {
            "name": "turn_latency_ms",
            "description": "Duration of each chat turn (`turn.completed`).",
            "filter": TURNS,
            "valueExtractor": "EXTRACT(jsonPayload.duration_ms)",
            "metricDescriptor": {"metricKind": "DELTA", "valueType": "DISTRIBUTION", "unit": "ms"},
            "bucketOptions": {
                "exponentialBuckets": {"numFiniteBuckets": 40, "growthFactor": 1.3, "scale": 100}
            },
        },
        {
            "name": "llm_spend_warnings",
            "description": "The day's LLM spend crossed 80% or 100% of the cap.",
            "filter": SPEND,
            "metricDescriptor": {"metricKind": "DELTA", "valueType": "INT64", "unit": "1"},
        },
    ]


def uptime_check(name: str, project: str, host: str, path: str) -> dict[str, Any]:
    return {
        "displayName": name,
        "monitoredResource": {
            "type": "uptime_url",
            "labels": {"project_id": project, "host": host},
        },
        "httpCheck": {"path": path, "port": 443, "useSsl": True, "validateSsl": True},
        "period": "300s",  # /healthz, not /readyz: Upstash's free tier counts every command
        "timeout": "10s",
    }


def policies(channel: str, check_ids: list[str]) -> list[dict[str, Any]]:
    def policy(name: str, condition: dict[str, Any], doc: str) -> dict[str, Any]:
        return {
            "displayName": name,
            "combiner": "OR",
            "conditions": [{"displayName": name, **condition}],
            "notificationChannels": [channel],
            "documentation": {"content": doc, "mimeType": "text/markdown"},
            "alertStrategy": {"autoClose": "86400s"},
        }

    checks = " OR ".join(f'metric.labels.check_id="{c}"' for c in check_ids)
    requests = (
        'metric.type="run.googleapis.com/request_count" AND resource.type="cloud_run_revision" '
        f"AND resource.labels.service_name={SERVICES}"
    )
    rate = {
        "alignmentPeriod": "300s",
        "perSeriesAligner": "ALIGN_RATE",
        "crossSeriesReducer": "REDUCE_SUM",
        "groupByFields": ["resource.labels.service_name"],
    }
    return [
        policy(
            "HomeHelper: uptime check failing",
            {
                "conditionThreshold": {
                    "filter": (
                        'metric.type="monitoring.googleapis.com/uptime_check/check_passed" '
                        f'AND resource.type="uptime_url" AND ({checks})'
                    ),
                    "aggregations": [
                        {
                            "alignmentPeriod": "300s",
                            "perSeriesAligner": "ALIGN_NEXT_OLDER",
                            "crossSeriesReducer": "REDUCE_COUNT_FALSE",
                            "groupByFields": ["metric.labels.check_id"],
                        }
                    ],
                    "comparison": "COMPARISON_GT",
                    "thresholdValue": 1,
                    "duration": "600s",
                    "trigger": {"count": 1},
                }
            },
            "The web app or the API stopped answering. See the README (Deployment, rollback).",
        ),
        policy(
            "HomeHelper: 5xx above 5%",
            {
                "conditionThreshold": {
                    "filter": f'{requests} AND metric.labels.response_code_class="5xx"',
                    "aggregations": [rate],
                    "denominatorFilter": requests,
                    "denominatorAggregations": [rate],
                    "comparison": "COMPARISON_GT",
                    "thresholdValue": 0.05,
                    "duration": "600s",
                    "trigger": {"count": 1},
                }
            },
            "More than 5% of requests failed for 10 minutes. Check the newest revision's logs.",
        ),
        policy(
            "HomeHelper: p95 turn latency above 30 s",
            {
                "conditionThreshold": {
                    "filter": (
                        'metric.type="logging.googleapis.com/user/turn_latency_ms" '
                        'AND resource.type="cloud_run_revision"'
                    ),
                    "aggregations": [
                        {
                            "alignmentPeriod": "600s",
                            "perSeriesAligner": "ALIGN_PERCENTILE_95",
                            "crossSeriesReducer": "REDUCE_MAX",
                        }
                    ],
                    "comparison": "COMPARISON_GT",
                    "thresholdValue": 30000,
                    "duration": "0s",
                    "trigger": {"count": 1},
                }
            },
            "Chat turns are slow (from `turn.completed` logs). Check LLM provider latency.",
        ),
        policy(
            "HomeHelper: daily LLM spend near the cap",
            {
                "conditionThreshold": {
                    "filter": (
                        'metric.type="logging.googleapis.com/user/llm_spend_warnings" '
                        'AND resource.type="cloud_run_revision"'
                    ),
                    "aggregations": [
                        {
                            "alignmentPeriod": "300s",
                            "perSeriesAligner": "ALIGN_SUM",
                            "crossSeriesReducer": "REDUCE_SUM",
                        }
                    ],
                    "comparison": "COMPARISON_GT",
                    "thresholdValue": 0,
                    "duration": "0s",
                    "trigger": {"count": 1},
                }
            },
            "Today's LLM spend crossed 80% of DAILY_SPEND_CAP_USD; at 100% the API goes into "
            "maintenance mode until 00:00 UTC.",
        ),
    ]


class Client:
    def __init__(self, project: str, dry_run: bool) -> None:
        self.project = project
        self.dry_run = dry_run
        self.token = gcloud("auth", "print-access-token")

    def call(
        self, method: str, url: str, body: dict[str, Any] | None = None, *, retries: int = 0
    ) -> dict[str, Any]:
        """`retries`: on a 400 or 404, try again after a pause (a new log metric takes a minute
        or two before an alert policy may refer to it)."""
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(retries + 1):
            request = urllib.request.Request(url, data=data, method=method)
            request.add_header("Authorization", f"Bearer {self.token}")
            request.add_header("Content-Type", "application/json")
            request.add_header("x-goog-user-project", self.project)
            try:
                with urllib.request.urlopen(request) as response:
                    return json.loads(response.read() or b"{}")
            except urllib.error.HTTPError as error:
                if attempt < retries and error.code in (400, 404):
                    print(f"  not ready yet ({error.code}); retrying in 20 s")
                    time.sleep(20)
                    continue
                sys.exit(f"{method} {url}: {error.code} {error.read().decode()}")
        raise AssertionError("unreachable")

    def ensure(
        self,
        kind: str,
        list_url: str,
        items_key: str,
        key: str,
        body: dict[str, Any],
        *,
        retries: int = 0,
    ) -> str:
        """The resource's name; created when no resource with the same `key` value exists."""
        page: dict[str, Any] = {}
        found: list[dict[str, Any]] = []
        while True:
            token = page.get("nextPageToken")
            url = list_url + (f"?pageToken={urllib.parse.quote(token)}" if token else "")
            page = self.call("GET", url)
            found += page.get(items_key, [])
            if not page.get("nextPageToken"):
                break
        for item in found:
            if item.get(key) == body[key]:
                print(f"exists  {kind}: {body[key]}")
                return item["name"]
        print(f"create  {kind}: {body[key]}")
        if self.dry_run:
            return f"<new {kind}>"
        return self.call("POST", list_url, body, retries=retries)["name"]


def gcloud(*args: str) -> str:
    return subprocess.run(
        ["gcloud", *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def service_host(project: str, region: str, service: str) -> str:
    url = gcloud(
        "run",
        "services",
        "describe",
        service,
        "--region",
        region,
        "--project",
        project,
        "--format",
        "value(status.url)",
    )
    if not url:
        sys.exit(f"{service} is not deployed yet: run the deploy workflow first")
    return urllib.parse.urlparse(url).netloc


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--project", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--region", default="us-west1")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    client = Client(args.project, args.dry_run)
    monitoring = f"https://monitoring.googleapis.com/v3/projects/{args.project}"
    logging_api = f"https://logging.googleapis.com/v2/projects/{args.project}"

    channel = client.ensure(
        "notification channel",
        f"{monitoring}/notificationChannels",
        "notificationChannels",
        "displayName",
        {"type": "email", "displayName": CHANNEL_NAME, "labels": {"email_address": args.email}},
    )
    for metric in log_metrics():
        client.ensure("log metric", f"{logging_api}/metrics", "metrics", "name", metric)
    checks = []
    for service, path in ((WEB_SERVICE, "/login"), (API_SERVICE, "/healthz")):
        host = service_host(args.project, args.region, service)
        name = client.ensure(
            "uptime check",
            f"{monitoring}/uptimeCheckConfigs",
            "uptimeCheckConfigs",
            "displayName",
            uptime_check(service, args.project, host, path),
        )
        checks.append(name.rsplit("/", 1)[-1])
    for body in policies(channel, checks):
        client.ensure(
            "alert policy",
            f"{monitoring}/alertPolicies",
            "alertPolicies",
            "displayName",
            body,
            retries=9,  # up to 3 minutes for the new log metrics to be usable
        )


if __name__ == "__main__":
    main()
