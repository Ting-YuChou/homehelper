import { describe, expect, it } from "vitest";

import { filtersFromSearch, filtersToSearch, reviewQuery } from "./filters";

describe("review filters", () => {
  it("reads known values from the URL and drops the rest", () => {
    const filters = filtersFromSearch(
      new URLSearchParams("outcome=resolved&feedback=down&release=r1&annotated=no&sample=1&junk=x"),
    );
    expect(filters).toEqual({
      outcome: "resolved",
      feedback: "down",
      release: "r1",
      annotated: "no",
      sample: true,
    });
    expect(
      filtersFromSearch(new URLSearchParams("outcome=exploded&feedback=meh&annotated=maybe")),
    ).toEqual({ sample: false });
  });

  it("round-trips through the URL, leaving out defaults", () => {
    const filters = { outcome: "open", feedback: "up", annotated: "yes", sample: false } as const;
    const search = filtersToSearch(filters);
    expect(search).toBe("outcome=open&feedback=up&annotated=yes");
    expect(filtersFromSearch(new URLSearchParams(search))).toEqual(filters);
    expect(filtersToSearch({ sample: false })).toBe("");
  });

  it("trims the release and ignores a blank one", () => {
    expect(filtersFromSearch(new URLSearchParams("release=%20%20"))).toEqual({ sample: false });
    expect(filtersToSearch({ release: "  r2 ", sample: false })).toBe("release=r2");
  });

  it("maps to the admin API query", () => {
    expect(
      reviewQuery({ outcome: "escalated", annotated: "no", release: "r1", sample: false }),
    ).toEqual({ outcome: "escalated", annotated: false, release_id: "r1", limit: 50 });
    expect(reviewQuery({ feedback: "down", annotated: "yes", sample: true })).toEqual({
      feedback: "down",
      annotated: true,
      sample: 20,
    });
  });
});
