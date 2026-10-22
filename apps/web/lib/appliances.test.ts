import { describe, expect, it } from "vitest";

import { formatDate, performedByLabel, repairOutcomeLabel, warrantyBadge } from "./appliances";

describe("formatDate", () => {
  it("shows the calendar date regardless of the local time zone", () => {
    expect(formatDate("2027-02-10")).toBe("Feb 10, 2027");
    expect(formatDate("2023-01-01")).toBe("Jan 1, 2023");
  });
});

describe("warrantyBadge", () => {
  it("marks an active warranty with its end date", () => {
    expect(
      warrantyBadge({ status: "active", warranty_until: "2027-02-10", days_remaining: 113 }),
    ).toEqual({ label: "Under warranty", tone: "active", detail: "Covered until Feb 10, 2027" });
  });

  it("flags an active warranty that ends within 30 days", () => {
    const badge = warrantyBadge({
      status: "active",
      warranty_until: "2026-10-30",
      days_remaining: 10,
    });
    expect(badge.tone).toBe("ending");
    expect(badge.detail).toBe("Covered until Oct 30, 2026, 10 days left");
    expect(
      warrantyBadge({ status: "active", warranty_until: "2026-10-21", days_remaining: 1 }).detail,
    ).toBe("Covered until Oct 21, 2026, 1 day left");
    expect(
      warrantyBadge({ status: "active", warranty_until: "2026-10-20", days_remaining: 0 }).detail,
    ).toBe("Covered until Oct 20, 2026, ends today");
  });

  it("shows when an expired warranty ended", () => {
    expect(warrantyBadge({ status: "expired", warranty_until: "2023-06-04" })).toEqual({
      label: "Warranty expired",
      tone: "expired",
      detail: "Ended Jun 4, 2023",
    });
  });

  it("explains an unknown warranty", () => {
    const badge = warrantyBadge({ status: "unknown", warranty_until: null });
    expect(badge.tone).toBe("unknown");
    expect(badge.label).toBe("Warranty unknown");
  });
});

describe("repair labels", () => {
  it("names outcomes and who did the repair", () => {
    expect(repairOutcomeLabel("resolved")).toBe("Fixed");
    expect(repairOutcomeLabel("technician_booked")).toBe("Technician booked");
    expect(performedByLabel("technician")).toBe("by a technician");
    expect(performedByLabel("self")).toBe("yourself");
  });
});
