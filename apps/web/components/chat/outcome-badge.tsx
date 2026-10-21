import { Badge } from "@/components/ui/badge";

const OUTCOMES: Record<string, { label: string; className: string }> = {
  resolved: {
    label: "Resolved",
    className: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200",
  },
  escalated: {
    label: "Technician",
    className: "bg-violet-100 text-violet-800 dark:bg-violet-950 dark:text-violet-200",
  },
  abandoned: { label: "Abandoned", className: "" },
  out_of_scope: { label: "Out of scope", className: "" },
};

export function OutcomeBadge({ outcome }: { outcome: string | null | undefined }) {
  const known = outcome ? OUTCOMES[outcome] : undefined;
  if (!known) return null;
  return (
    <Badge variant="secondary" className={known.className}>
      {known.label}
    </Badge>
  );
}
