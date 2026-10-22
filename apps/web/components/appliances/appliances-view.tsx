"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Wrench } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useEffect } from "react";

import { categoryLabel } from "@/components/cards/appliance-confirm-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/client";
import { appliancesQuery, meQuery } from "@/lib/api/queries";
import type { Appliance } from "@/lib/api/types";
import {
  formatDate,
  performedByLabel,
  repairOutcomeLabel,
  warrantyBadge,
  type WarrantyTone,
} from "@/lib/appliances";

const TONES: Record<WarrantyTone, string> = {
  active: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200",
  ending: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200",
  expired: "",
  unknown: "",
};

function ApplianceCard({ appliance }: { appliance: Appliance }) {
  const warranty = warrantyBadge(appliance.warranty);
  const category = categoryLabel(appliance.category);
  const title = appliance.nickname ?? `${appliance.brand} ${category.toLowerCase()}`;
  return (
    <section aria-label={title} className="flex flex-col gap-4 rounded-xl border p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 flex-col gap-1">
          <h2 className="font-medium">{title}</h2>
          <p className="text-sm text-muted-foreground">
            {appliance.brand} · {category} · model{" "}
            <span className="font-mono">{appliance.model_number}</span>
          </p>
          {appliance.purchase_date && (
            <p className="text-xs text-muted-foreground">
              Bought {formatDate(appliance.purchase_date)}
            </p>
          )}
        </div>
        <div className="flex flex-col items-end gap-1 text-right">
          <Badge variant="secondary" className={TONES[warranty.tone]}>
            {warranty.label}
          </Badge>
          {warranty.detail && (
            <span className="text-xs text-muted-foreground">{warranty.detail}</span>
          )}
        </div>
      </div>
      <div className="flex flex-col gap-2">
        <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
          Recent repairs
        </h3>
        {appliance.recent_repairs.length === 0 ? (
          <p className="text-sm text-muted-foreground">No repairs on record.</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {appliance.recent_repairs.map((repair) => (
              <li key={repair.record_id} className="flex gap-3 text-sm">
                <Wrench className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
                <div className="flex min-w-0 flex-col gap-0.5">
                  <p>
                    {repair.issue}
                    {repair.error_code && (
                      <>
                        {" "}
                        <span className="font-mono text-xs">({repair.error_code})</span>
                      </>
                    )}
                  </p>
                  <p className="text-muted-foreground">{repair.resolution}</p>
                  <p className="text-xs text-muted-foreground">
                    {formatDate(repair.date)} · {repairOutcomeLabel(repair.outcome)}{" "}
                    {performedByLabel(repair.performed_by)}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function ListSkeleton() {
  return (
    <div className="flex flex-col gap-4">
      <Skeleton className="h-36 w-full" />
      <Skeleton className="h-36 w-full" />
    </div>
  );
}

export function AppliancesView() {
  const router = useRouter();
  const pathname = usePathname();
  const me = useQuery(meQuery);
  const appliances = useQuery({ ...appliancesQuery, enabled: me.data?.is_demo === true });

  const unauthorized = me.error instanceof ApiError && me.error.status === 401;
  useEffect(() => {
    if (unauthorized) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [unauthorized, pathname, router]);

  let body: ReactNode;
  if ((me.isError && !unauthorized) || appliances.isError) {
    body = (
      <p className="text-muted-foreground">
        Can&apos;t reach the HomeHelper API right now. Please try again in a moment.
      </p>
    );
  } else if (!me.data) {
    body = <ListSkeleton />;
  } else if (!me.data.is_demo) {
    body = (
      <p className="text-muted-foreground">
        Guests don&apos;t have saved appliances.{" "}
        <Link href="/login?next=/appliances" className="underline underline-offset-4">
          Pick a demo user
        </Link>{" "}
        to see appliances, warranties and repair history.
      </p>
    );
  } else if (!appliances.data) {
    body = <ListSkeleton />;
  } else if (appliances.data.length === 0) {
    body = <p className="text-muted-foreground">No appliances registered yet.</p>;
  } else {
    body = (
      <div className="flex flex-col gap-4">
        {appliances.data.map((appliance) => (
          <ApplianceCard key={appliance.appliance_id} appliance={appliance} />
        ))}
      </div>
    );
  }

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-4 py-8">
      <div className="flex flex-col gap-3">
        <div>
          <Button asChild variant="ghost" size="sm">
            <Link href="/chat">
              <ArrowLeft data-icon="inline-start" aria-hidden />
              Back to chat
            </Link>
          </Button>
        </div>
        <h1 className="text-2xl font-semibold tracking-tight">My appliances</h1>
        <p className="text-sm text-muted-foreground">
          Registered appliances, their warranty today and the latest repairs. HomeHelper uses the
          same records to fill in your appliance during a chat.
        </p>
      </div>
      {body}
    </main>
  );
}
