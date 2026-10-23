"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { METRICS, type ReportPoint, formatMetric } from "@/lib/admin/trends";
import { ApiError } from "@/lib/api/client";
import { adminEvalQuery } from "@/lib/api/queries";

const passRate = (c: { successes: number; trials: number }) =>
  c.trials ? c.successes / c.trials : 0;

/** Route params may arrive encoded or not; a stray `%` must not throw. */
function reportId(raw: string): string {
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

const dateTime = new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" });

/** `/admin/evals/[id]`: one run's metrics, configuration and per-case results. */
export function EvalReportDetail() {
  const { id } = useParams<{ id: string }>();
  const report = useQuery(adminEvalQuery(reportId(id)));
  if (report.isPending) return <Skeleton className="h-96 w-full" />;
  if (report.isError) {
    const missing = report.error instanceof ApiError && report.error.status === 404;
    return (
      <p className="py-12 text-center text-sm text-muted-foreground">
        {missing ? "No such report." : "Couldn't load the report."}
      </p>
    );
  }
  const data = report.data;
  const metrics = data.metrics as ReportPoint["metrics"];
  const values = METRICS.map((m) => ({ ...m, value: m.get(metrics) })).filter(
    (m) => m.value !== null,
  );
  // Failing cases first, then by id.
  const cases = [...data.cases].sort(
    (a, b) => passRate(a) - passRate(b) || a.id.localeCompare(b.id),
  );
  const config = Object.entries(data.config).filter(([, value]) => value !== null);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <Button asChild variant="ghost" size="sm" className="self-start">
          <Link href="/admin/evals">
            <ArrowLeft data-icon="inline-start" aria-hidden />
            All reports
          </Link>
        </Button>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-semibold tracking-tight">
            {data.suite} · <span className="font-mono">{data.release_id}</span>
          </h1>
          {data.weakened && <Badge variant="outline">Weakened: {data.weakened}</Badge>}
        </div>
        <p className="text-sm text-muted-foreground">
          {dateTime.format(new Date(data.created_at))} · git{" "}
          <span className="font-mono">{data.git_sha?.slice(0, 7) ?? "—"}</span>
          {data.kb_version && (
            <>
              {" "}
              · <span className="font-mono">{data.kb_version}</span>
            </>
          )}
        </p>
      </div>

      <section
        aria-label="Metrics"
        className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4"
      >
        {values.map((metric) => (
          <div key={metric.key} className="flex flex-col gap-1 rounded-lg border p-3">
            <span className="text-xs text-muted-foreground">{metric.label}</span>
            <span className="text-lg font-semibold tabular-nums">
              {formatMetric(metric.value, metric.format)}
            </span>
          </div>
        ))}
      </section>

      <section aria-label="Run configuration" className="flex flex-col gap-2">
        <h2 className="text-sm font-medium">Run configuration</h2>
        <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
          {config.map(([key, value]) => (
            <div key={key} className="contents">
              <dt className="text-muted-foreground">{key}</dt>
              <dd className="font-mono text-xs break-all">
                {typeof value === "string" ? value : JSON.stringify(value)}
              </dd>
            </div>
          ))}
        </dl>
      </section>

      <section aria-label="Cases" className="flex flex-col gap-2">
        <h2 className="text-sm font-medium">Cases ({cases.length})</h2>
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Case</TableHead>
                <TableHead>Kind</TableHead>
                <TableHead className="text-right">Passed</TableHead>
                <TableHead>Failing checks</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {cases.map((item) => (
                <TableRow key={item.id}>
                  <TableCell className="font-mono text-xs">{item.id}</TableCell>
                  <TableCell>{item.kind}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {item.successes}/{item.trials}
                  </TableCell>
                  <TableCell>
                    <span className="flex flex-wrap gap-1">
                      {Object.entries(item.failed_checks ?? {}).map(([check, count]) => (
                        <Badge key={check} variant="outline">
                          {check} ×{count}
                        </Badge>
                      ))}
                    </span>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </section>
    </div>
  );
}
