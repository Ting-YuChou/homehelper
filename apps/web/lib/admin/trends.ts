// Per-release trends on /admin/evals (spec §15.2, M7-04): one small chart per metric, one line
// per suite's runs over time. Runs that can't gate a release (no judge, --limit, ...) are left
// out of the lines by default, so a cheap trial run never reads as a regression.

import { formatLatency } from "./format";

export type MetricFormat = "rate" | "usd" | "ms";

type Metrics = {
  pass_hat_k?: Record<string, number | null>;
  cost_usd?: Record<string, number | null>;
  latency_ms?: Record<string, number | null>;
  [key: string]: unknown;
};

export type ReportPoint = {
  id: string;
  release_id: string;
  suite: string;
  created_at: string;
  metrics: Metrics;
  weakened: string | null;
};

export type MetricSpec = {
  key: string;
  label: string;
  format: MetricFormat;
  get: (metrics: Metrics) => number | null;
};

const number = (value: unknown) => (typeof value === "number" ? value : null);
const field = (key: string) => (metrics: Metrics) => number(metrics[key]);

function highestK(values: Record<string, number | null> | undefined): number | null {
  const ks = Object.keys(values ?? {})
    .map(Number)
    .filter((k) => Number.isFinite(k))
    .sort((a, b) => b - a);
  return ks.length ? number(values?.[String(ks[0])]) : null;
}

export const METRICS: readonly MetricSpec[] = [
  {
    key: "resolution_rate",
    label: "Resolution rate",
    format: "rate",
    get: field("resolution_rate"),
  },
  {
    key: "pass_hat_k",
    label: "pass^k",
    format: "rate",
    get: (m) => highestK(m.pass_hat_k),
  },
  {
    key: "safety_pass_rate",
    label: "Safety pass rate",
    format: "rate",
    get: field("safety_pass_rate"),
  },
  {
    key: "injection_resistance",
    label: "Injection resistance",
    format: "rate",
    get: field("injection_resistance"),
  },
  {
    key: "out_of_scope_pass_rate",
    label: "Out-of-scope pass rate",
    format: "rate",
    get: field("out_of_scope_pass_rate"),
  },
  {
    key: "multi_issue_pass_rate",
    label: "Multi-issue pass rate",
    format: "rate",
    get: field("multi_issue_pass_rate"),
  },
  {
    key: "tool_scenario_pass_rate",
    label: "Tools pass rate",
    format: "rate",
    get: field("tool_scenario_pass_rate"),
  },
  {
    key: "multimodal_pass_rate",
    label: "Multimodal pass rate",
    format: "rate",
    get: field("multimodal_pass_rate"),
  },
  {
    key: "regression_pass_rate",
    label: "Regression pass rate",
    format: "rate",
    get: field("regression_pass_rate"),
  },
  { key: "success_rate", label: "All checks passed", format: "rate", get: field("success_rate") },
  {
    key: "citation_accuracy",
    label: "Citation accuracy",
    format: "rate",
    get: field("citation_accuracy"),
  },
  {
    key: "cost_per_conversation",
    label: "Agent cost per conversation",
    format: "usd",
    get: (m) => number(m.cost_usd?.agent_per_conversation),
  },
  {
    key: "latency_p95",
    label: "Agent turn latency p95",
    format: "ms",
    get: (m) => number(m.latency_ms?.agent_turn_p95),
  },
];

const SUITE_ORDER = ["full", "safety", "smoke", "multi_issue", "tools", "multimodal", "regression"];

export function suitesOf(reports: readonly ReportPoint[]): string[] {
  const present = new Set(reports.map((r) => r.suite));
  const known = SUITE_ORDER.filter((suite) => present.has(suite));
  const others = [...present].filter((suite) => !SUITE_ORDER.includes(suite)).sort();
  return [...known, ...others];
}

export type SeriesPoint = {
  id: string;
  release: string;
  createdAt: string;
  value: number;
  weakened: boolean;
};

export function series(
  reports: readonly ReportPoint[],
  suite: string,
  metricKey: string,
  { includeWeakened = false }: { includeWeakened?: boolean } = {},
): SeriesPoint[] {
  const metric = METRICS.find((m) => m.key === metricKey);
  if (!metric) return [];
  return reports
    .filter((r) => r.suite === suite && (includeWeakened || !r.weakened))
    .map((r) => ({
      id: r.id,
      release: r.release_id,
      createdAt: r.created_at,
      value: metric.get(r.metrics),
      weakened: Boolean(r.weakened),
    }))
    .filter((p): p is SeriesPoint => p.value !== null)
    .sort((a, b) => a.createdAt.localeCompare(b.createdAt) || a.id.localeCompare(b.id));
}

/** The metrics with at least one value among the suite's (included) runs. */
export function chartMetrics(
  reports: readonly ReportPoint[],
  suite: string,
  options: { includeWeakened?: boolean } = {},
): MetricSpec[] {
  return METRICS.filter((m) => series(reports, suite, m.key, options).length > 0);
}

export function formatMetric(value: number | null | undefined, format: MetricFormat): string {
  if (value === null || value === undefined) return "—";
  if (format === "rate") return `${Number((value * 100).toFixed(1))}%`;
  // Per-conversation costs are cents; four decimals keep their changes visible.
  if (format === "usd") return value < 1 ? `$${value.toFixed(4)}` : `$${value.toFixed(2)}`;
  return formatLatency(value);
}

/** The y-scale: rates always 0–100% (so charts compare); other values from 0, with headroom. */
export function scaleFor(format: MetricFormat, values: readonly number[]) {
  if (format === "rate") return { min: 0, max: 1 };
  const max = Math.max(0, ...values);
  return { min: 0, max: max > 0 ? Number((max * 1.1).toPrecision(6)) : 1 };
}
