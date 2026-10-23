import { describe, expect, it } from "vitest";

import { formatCost, formatLatency } from "./format";

describe("admin number formats", () => {
  it.each([
    [null, "—"],
    [0, "$0"],
    [0.00123, "$0.0012"],
    [0.0451, "$0.05"],
    [3, "$3.00"],
  ])("cost %s", (usd, text) => expect(formatCost(usd)).toBe(text));

  it.each([
    [undefined, "—"],
    [840.4, "840 ms"],
    [1234, "1.2 s"],
  ])("latency %s", (ms, text) => expect(formatLatency(ms)).toBe(text));
});
