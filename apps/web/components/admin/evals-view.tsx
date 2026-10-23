"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { type ReportPoint, chartMetrics, formatMetric, series, suitesOf } from "@/lib/admin/trends";
import { adminEvalsQuery } from "@/lib/api/queries";
import type { EvalReport } from "@/lib/api/types";

import { TrendChart } from "./trend-chart";

const dateTime = new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" });

function SuiteReports({ reports, suite }: { reports: EvalReport[]; suite: string }) {
  const [includeWeakened, setIncludeWeakened] = useState(false);
  const points = reports as unknown as ReportPoint[];
  const metrics = chartMetrics(points, suite, { includeWeakened });
  const runs = reports.filter((r) => r.suite === suite);
  const headline = metrics.slice(0, 3);
  const checkboxId = `weakened-${suite}`;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <Checkbox
          id={checkboxId}
          checked={includeWeakened}
          onCheckedChange={(checked) => setIncludeWeakened(checked === true)}
        />
        <Label htmlFor={checkboxId} className="font-normal">
          Include weakened runs (no judge, scripted simulator, --limit) as hollow points
        </Label>
      </div>
      {metrics.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No full runs of this suite yet; tick the box above to see trial runs.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {metrics.map((metric) => (
            <TrendChart
              key={metric.key}
              label={metric.label}
              format={metric.format}
              points={series(points, suite, metric.key, { includeWeakened })}
            />
          ))}
        </div>
      )}
      <div className="overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Release</TableHead>
              <TableHead>Run</TableHead>
              {headline.map((metric) => (
                <TableHead key={metric.key} className="text-right">
                  {metric.label}
                </TableHead>
              ))}
              <TableHead>Git</TableHead>
              <TableHead>Knowledge base</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {runs.map((run) => (
              <TableRow key={run.id}>
                <TableCell>
                  <Link
                    href={`/admin/evals/${encodeURIComponent(run.id)}`}
                    className="font-mono text-xs underline-offset-4 hover:underline"
                  >
                    {run.release_id}
                  </Link>
                </TableCell>
                <TableCell className="whitespace-nowrap text-muted-foreground">
                  {dateTime.format(new Date(run.created_at))}
                </TableCell>
                {headline.map((metric) => (
                  <TableCell key={metric.key} className="text-right tabular-nums">
                    {formatMetric(metric.get(run.metrics as ReportPoint["metrics"]), metric.format)}
                  </TableCell>
                ))}
                <TableCell className="font-mono text-xs">
                  {run.git_sha?.slice(0, 7) ?? "—"}
                </TableCell>
                <TableCell className="font-mono text-xs">{run.kb_version ?? "—"}</TableCell>
                <TableCell>
                  {run.weakened && (
                    <Badge variant="outline" title={`This run ${run.weakened}`}>
                      Weakened
                    </Badge>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

/** `/admin/evals`: each suite's runs over time (spec §15.2, M7-04). */
export function EvalsView() {
  const reports = useQuery(adminEvalsQuery);
  if (reports.isPending) return <Skeleton className="h-96 w-full" />;
  if (reports.isError) {
    return <p className="text-sm text-destructive">Couldn&apos;t load the eval reports.</p>;
  }
  const suites = suitesOf(reports.data as unknown as ReportPoint[]);
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold tracking-tight">Eval reports</h1>
        <p className="text-sm text-muted-foreground">
          Recorded with <code className="text-xs">evals run --record</code> or{" "}
          <code className="text-xs">evals publish</code>.
        </p>
      </div>
      {suites.length === 0 ? (
        <p className="py-12 text-center text-sm text-muted-foreground">No reports recorded yet.</p>
      ) : (
        <Tabs defaultValue={suites[0]}>
          <TabsList>
            {suites.map((suite) => (
              <TabsTrigger key={suite} value={suite}>
                {suite}
              </TabsTrigger>
            ))}
          </TabsList>
          {suites.map((suite) => (
            <TabsContent key={suite} value={suite} className="pt-3">
              <SuiteReports reports={reports.data} suite={suite} />
            </TabsContent>
          ))}
        </Tabs>
      )}
    </div>
  );
}
