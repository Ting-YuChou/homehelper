// Display helpers for the /appliances page (pure, unit-tested in appliances.test.ts).
import type { Repair, Warranty } from "@/lib/api/types";

export type WarrantyTone = "active" | "ending" | "expired" | "unknown";

/** An active warranty with this many days or fewer left is flagged as ending soon. */
export const ENDING_SOON_DAYS = 30;

const dateFormat = new Intl.DateTimeFormat("en", {
  month: "short",
  day: "numeric",
  year: "numeric",
  timeZone: "UTC",
});

/** A calendar date from the API (`YYYY-MM-DD`), shown the same in every time zone. */
export function formatDate(isoDate: string): string {
  return dateFormat.format(new Date(`${isoDate}T00:00:00Z`));
}

export function warrantyBadge(warranty: Warranty): {
  label: string;
  tone: WarrantyTone;
  detail: string | null;
} {
  const until = warranty.warranty_until ? formatDate(warranty.warranty_until) : null;
  switch (warranty.status) {
    case "active": {
      const days = warranty.days_remaining ?? null;
      if (days !== null && days <= ENDING_SOON_DAYS) {
        const left = days === 0 ? "ends today" : `${days} ${days === 1 ? "day" : "days"} left`;
        return {
          label: "Warranty ending",
          tone: "ending",
          detail: `Covered until ${until}, ${left}`,
        };
      }
      return { label: "Under warranty", tone: "active", detail: until && `Covered until ${until}` };
    }
    case "expired":
      return { label: "Warranty expired", tone: "expired", detail: until && `Ended ${until}` };
    default:
      return {
        label: "Warranty unknown",
        tone: "unknown",
        detail: "No warranty date on file (e.g. owned by the landlord)",
      };
  }
}

const OUTCOMES: Record<Repair["outcome"], string> = {
  resolved: "Fixed",
  unresolved: "Not fixed",
  technician_booked: "Technician booked",
};

export function repairOutcomeLabel(outcome: Repair["outcome"]): string {
  return OUTCOMES[outcome] ?? outcome;
}

export function performedByLabel(performedBy: Repair["performed_by"]): string {
  return performedBy === "technician" ? "by a technician" : "yourself";
}
