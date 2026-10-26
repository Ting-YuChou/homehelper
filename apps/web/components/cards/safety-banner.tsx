import { ShieldAlert } from "lucide-react";

import type { SafetyCard } from "@/lib/api/types";

const HAZARDS: Record<string, string> = {
  gas_smell: "Possible gas leak",
  smoke_or_burning: "Smoke or burning smell",
  sparks: "Sparks or electrical arcing",
  high_voltage_internal: "High-voltage parts",
  refrigerant: "Refrigerant leak",
  water_near_electric: "Water near electricity",
  damaged_cord: "Damaged cord or plug",
  injury: "Injury",
};

export function SafetyBanner({ card }: { card: SafetyCard }) {
  return (
    <section
      role="alert"
      className="flex gap-3 rounded-xl border border-red-300 bg-red-50 p-4 text-red-950 dark:border-red-900 dark:bg-red-950/40 dark:text-red-100"
    >
      <ShieldAlert className="mt-0.5 size-5 shrink-0 text-red-600" aria-hidden />
      <div className="flex flex-col gap-2">
        <h3 className="font-semibold">
          Safety first: {HAZARDS[card.hazard] ?? card.hazard.replaceAll("_", " ")}
        </h3>
        <ul className="flex list-disc flex-col gap-1 pl-4 text-sm">
          {card.instructions.map((instruction) => (
            <li key={instruction}>{instruction}</li>
          ))}
        </ul>
      </div>
    </section>
  );
}
