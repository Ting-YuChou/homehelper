"use client";

import { type KeyboardEvent, type PointerEvent, useId, useRef, useState } from "react";

import { type MetricFormat, type SeriesPoint, formatMetric, scaleFor } from "@/lib/admin/trends";

// Drawing space; the SVG scales with its card, so these are proportions, not pixels.
const WIDTH = 320;
const HEIGHT = 132;
const PAD = { top: 12, right: 44, bottom: 22, left: 36 };
const PLOT_W = WIDTH - PAD.left - PAD.right;
const PLOT_H = HEIGHT - PAD.top - PAD.bottom;

const shortDate = new Intl.DateTimeFormat("en", { month: "short", day: "numeric" });

/** One metric of one suite over its runs: a 2px line, 8px markers, the latest value at the end,
 * and a crosshair that snaps to the nearest run (pointer or arrow keys). */
export function TrendChart({
  label,
  format,
  points,
}: {
  label: string;
  format: MetricFormat;
  points: SeriesPoint[];
}) {
  const titleId = useId();
  const svg = useRef<SVGSVGElement>(null);
  const [active, setActive] = useState<number | null>(null);
  const scale = scaleFor(
    format,
    points.map((p) => p.value),
  );
  const x = (i: number) =>
    PAD.left + (points.length === 1 ? PLOT_W / 2 : (i / (points.length - 1)) * PLOT_W);
  const y = (value: number) =>
    PAD.top + PLOT_H - ((value - scale.min) / (scale.max - scale.min || 1)) * PLOT_H;
  const ticks = [scale.min, (scale.min + scale.max) / 2, scale.max];
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(i)},${y(p.value)}`).join(" ");
  const last = points.at(-1);

  const nearest = (event: PointerEvent<SVGSVGElement>) => {
    const box = svg.current?.getBoundingClientRect();
    if (!box || points.length === 0) return;
    const at = ((event.clientX - box.left) / box.width) * WIDTH;
    let best = 0;
    points.forEach((_, i) => {
      if (Math.abs(x(i) - at) < Math.abs(x(best) - at)) best = i;
    });
    setActive(best);
  };
  const keys = (event: KeyboardEvent<SVGSVGElement>) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const step = event.key === "ArrowLeft" ? -1 : 1;
    setActive((i) => Math.min(points.length - 1, Math.max(0, (i ?? points.length - 1) + step)));
  };
  const shown = active === null ? null : points[active];

  return (
    <figure className="flex flex-col gap-2 rounded-lg border p-3">
      <figcaption id={titleId} className="text-sm font-medium">
        {label}
      </figcaption>
      <div className="relative">
        <svg
          ref={svg}
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="h-auto w-full touch-none overflow-visible outline-none focus-visible:ring-2 focus-visible:ring-ring"
          role="img"
          aria-labelledby={titleId}
          tabIndex={0}
          onPointerMove={nearest}
          onPointerLeave={() => setActive(null)}
          onKeyDown={keys}
          onFocus={() => setActive(points.length - 1)}
          onBlur={() => setActive(null)}
        >
          {ticks.map((tick) => (
            <g key={tick}>
              <line
                x1={PAD.left}
                x2={WIDTH - PAD.right}
                y1={y(tick)}
                y2={y(tick)}
                className="stroke-border"
                strokeWidth={1}
              />
              <text
                x={PAD.left - 6}
                y={y(tick)}
                textAnchor="end"
                dominantBaseline="middle"
                className="fill-muted-foreground text-[10px]"
              >
                {formatMetric(tick, format)}
              </text>
            </g>
          ))}
          {points.length > 1 && (
            <path
              d={line}
              fill="none"
              stroke="var(--series-1)"
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          )}
          {shown && active !== null && (
            <line
              x1={x(active)}
              x2={x(active)}
              y1={PAD.top}
              y2={PAD.top + PLOT_H}
              className="stroke-muted-foreground"
              strokeWidth={1}
            />
          )}
          {points.map((p, i) => (
            <circle
              key={p.id}
              cx={x(i)}
              cy={y(p.value)}
              r={4}
              className="stroke-background"
              strokeWidth={2}
              // A weakened run (shown only on request) is a hollow marker.
              fill={p.weakened ? "var(--background)" : "var(--series-1)"}
              style={p.weakened ? { stroke: "var(--series-1)" } : undefined}
            />
          ))}
          {last && (
            <text
              x={x(points.length - 1) + 8}
              y={y(last.value)}
              dominantBaseline="middle"
              className="fill-foreground text-[10px] font-medium tabular-nums"
            >
              {formatMetric(last.value, format)}
            </text>
          )}
          {points.length > 0 && (
            <>
              <text
                x={x(0)}
                y={HEIGHT - 4}
                textAnchor={points.length === 1 ? "middle" : "start"}
                className="fill-muted-foreground text-[10px]"
              >
                {shortDate.format(new Date(points[0].createdAt))}
              </text>
              {points.length > 1 && (
                <text
                  x={x(points.length - 1)}
                  y={HEIGHT - 4}
                  textAnchor="end"
                  className="fill-muted-foreground text-[10px]"
                >
                  {shortDate.format(new Date(points[points.length - 1].createdAt))}
                </text>
              )}
            </>
          )}
        </svg>
        {shown && active !== null && (
          <div
            role="status"
            className="pointer-events-none absolute top-0 z-10 flex -translate-x-1/2 flex-col rounded-md border bg-popover px-2 py-1 text-xs shadow-sm"
            style={{ left: `${(x(active) / WIDTH) * 100}%` }}
          >
            <span className="flex items-center gap-1.5 font-semibold tabular-nums">
              <span
                aria-hidden
                className="inline-block h-0.5 w-3 rounded"
                style={{ background: "var(--series-1)" }}
              />
              {formatMetric(shown.value, format)}
            </span>
            <span className="font-mono text-muted-foreground">{shown.release}</span>
            <span className="text-muted-foreground">
              {shortDate.format(new Date(shown.createdAt))}
              {shown.weakened && " · weakened run"}
            </span>
          </div>
        )}
      </div>
    </figure>
  );
}
