import type { Metadata } from "next";

import { AppliancesView } from "@/components/appliances/appliances-view";

export const metadata: Metadata = { title: "My appliances" };

export default function AppliancesPage() {
  return <AppliancesView />;
}
