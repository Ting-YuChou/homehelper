import { describe, expect, it } from "vitest";

import { type ReportPoint, chartMetrics, formatMetric, scaleFor, series, suitesOf } from "./trends";

function report(id: string, suite: string, createdAt: string, metrics: object, weakened?: string) {
  return {
    id,
    release_id: `r-${id}`,
    suite,
    created_at: createdAt,
    metrics,
    weakened: weakened ?? null,
  } as ReportPoint;
}

const REPORTS = [
  report("b", "full", "2026-10-21T00:00:00Z", {
    resolution_rate: 0.7,
    pass_hat_k: { "1": 0.7, "4": 0.5 },
  }),
  report("a", "full", "2026-10-20T00:00:00Z", {
    resolution_rate: 0.6,
    pass_hat_k: { "1": 0.6, "4": 0.4 },
  }),
  report("c", "full", "2026-10-22T00:00:00Z", { resolution_rate: 0.9 }, "was run with --limit 5"),
  report("d", "safety", "2026-10-22T00:00:00Z", { safety_pass_rate: 1, resolution_rate: null }),
  report("e", "regression", "2026-10-22T00:00:00Z", { regression_pass_rate: 0.5 }),
];

describe("eval trends", () => {
  it("lists suites in a fixed order, then any others", () => {
    expect(suitesOf([...REPORTS, report("x", "custom", "2026-10-01T00:00:00Z", {})])).toEqual([
      "full",
      "safety",
      "regression",
      "custom",
    ]);
  });

  it("orders a series by run time and leaves out weakened runs by default", () => {
    const points = series(REPORTS, "full", "resolution_rate");
    expect(points.map((p) => [p.release, p.value])).toEqual([
      ["r-a", 0.6],
      ["r-b", 0.7],
    ]);
    const all = series(REPORTS, "full", "resolution_rate", { includeWeakened: true });
    expect(all.map((p) => [p.value, p.weakened])).toEqual([
      [0.6, false],
      [0.7, false],
      [0.9, true],
    ]);
  });

  it("reads pass^k at the largest k", () => {
    expect(series(REPORTS, "full", "pass_hat_k").map((p) => p.value)).toEqual([0.4, 0.5]);
  });

  it("charts only the metrics a suite has values for", () => {
    expect(chartMetrics(REPORTS, "safety").map((m) => m.key)).toEqual(["safety_pass_rate"]);
    expect(chartMetrics(REPORTS, "full").map((m) => m.key)).toEqual([
      "resolution_rate",
      "pass_hat_k",
    ]);
    expect(chartMetrics(REPORTS, "regression").map((m) => m.key)).toEqual(["regression_pass_rate"]);
  });

  it("formats values by kind", () => {
    expect(formatMetric(0.875, "rate")).toBe("87.5%");
    expect(formatMetric(1, "rate")).toBe("100%");
    expect(formatMetric(0.0123, "usd")).toBe("$0.0123");
    expect(formatMetric(1234, "ms")).toBe("1.2 s");
    expect(formatMetric(null, "rate")).toBe("—");
  });

  it("scales rates to 0–100% and other values from zero with headroom", () => {
    expect(scaleFor("rate", [0.2, 0.4])).toEqual({ min: 0, max: 1 });
    expect(scaleFor("usd", [0.02, 0.04])).toEqual({ min: 0, max: 0.044 });
    expect(scaleFor("ms", [])).toEqual({ min: 0, max: 1 });
  });
});
