"use client";

/**
 * EquityChart.tsx
 * ---------------
 * Equity curve with a drawdown panel beneath it, drawn as inline SVG.
 *
 * No charting library. Two polylines and a pair of axes do not justify a
 * dependency, and hand-drawing them means the chart can mark the things that
 * matter here — the effective start date, and the region before it where the
 * strategy was not yet running its full universe — which a generic library
 * would make awkward.
 */

import { useMemo } from "react";
import type { EquityPoint } from "@/lib/api";
import { fmtPct, fmtUsd } from "@/lib/api";

interface Props {
  points: EquityPoint[];
  /** Sessions before this had an incomplete universe; shaded and labelled. */
  effectiveStart?: string | null;
  height?: number;
}

const PAD = { top: 16, right: 16, bottom: 28, left: 68 };
const DRAWDOWN_RATIO = 0.3;

export function EquityChart({ points, effectiveStart, height = 340 }: Props) {
  const width = 900;

  const geometry = useMemo(() => {
    if (points.length < 2) return null;

    const equityHeight = height * (1 - DRAWDOWN_RATIO);
    const ddHeight = height * DRAWDOWN_RATIO;
    const plotWidth = width - PAD.left - PAD.right;

    const equities = points.map((p) => p.equity);
    const minEq = Math.min(...equities);
    const maxEq = Math.max(...equities);
    const span = maxEq - minEq || 1;

    const worstDd = Math.min(...points.map((p) => p.drawdown_pct), 0);
    const ddSpan = Math.abs(worstDd) || 0.01;

    const x = (i: number) =>
      PAD.left + (i / (points.length - 1)) * plotWidth;
    const yEq = (v: number) =>
      PAD.top + (1 - (v - minEq) / span) * (equityHeight - PAD.top);
    const yDd = (v: number) =>
      equityHeight + (Math.abs(v) / ddSpan) * (ddHeight - PAD.bottom);

    const equityPath = points.map((p, i) => `${x(i)},${yEq(p.equity)}`).join(" ");
    const ddPath = points.map((p, i) => `${x(i)},${yDd(p.drawdown_pct)}`).join(" ");
    const ddArea = `${PAD.left},${equityHeight} ${ddPath} ${x(points.length - 1)},${equityHeight}`;

    // Where the full universe finally existed. Everything left of this is a
    // different strategy wearing the same name.
    let effectiveIndex = -1;
    if (effectiveStart) {
      effectiveIndex = points.findIndex((p) => p.session >= effectiveStart);
    }

    return {
      x,
      yEq,
      equityPath,
      ddArea,
      minEq,
      maxEq,
      worstDd,
      equityHeight,
      effectiveIndex,
    };
  }, [points, effectiveStart, height]);

  if (!geometry) {
    return (
      <div className="chart-empty">Not enough data points to draw a curve.</div>
    );
  }

  const { x, yEq, equityPath, ddArea, minEq, maxEq, worstDd, equityHeight, effectiveIndex } =
    geometry;

  const first = points[0];
  const last = points[points.length - 1];
  const gridValues = [minEq, (minEq + maxEq) / 2, maxEq];

  return (
    <figure className="chart">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label={`Equity curve from ${first.session} to ${last.session}`}
      >
        {gridValues.map((value) => (
          <g key={value}>
            <line
              x1={PAD.left}
              x2={width - PAD.right}
              y1={yEq(value)}
              y2={yEq(value)}
              className="grid"
            />
            <text x={PAD.left - 8} y={yEq(value) + 4} className="axis" textAnchor="end">
              {fmtUsd(value)}
            </text>
          </g>
        ))}

        {effectiveIndex > 0 && (
          <>
            <rect
              x={PAD.left}
              y={PAD.top}
              width={x(effectiveIndex) - PAD.left}
              height={equityHeight - PAD.top}
              className="warmup"
            />
            <line
              x1={x(effectiveIndex)}
              x2={x(effectiveIndex)}
              y1={PAD.top}
              y2={equityHeight}
              className="effective-line"
            />
            <text
              x={x(effectiveIndex) + 6}
              y={PAD.top + 12}
              className="effective-label"
            >
              full universe from {effectiveStart}
            </text>
          </>
        )}

        <polyline points={equityPath} className="equity-line" />
        <polygon points={ddArea} className="drawdown-area" />

        <line
          x1={PAD.left}
          x2={width - PAD.right}
          y1={equityHeight}
          y2={equityHeight}
          className="axis-line"
        />
        <text x={PAD.left} y={height - 8} className="axis">
          {first.session}
        </text>
        <text x={width - PAD.right} y={height - 8} className="axis" textAnchor="end">
          {last.session}
        </text>
        <text x={PAD.left - 8} y={equityHeight + 14} className="axis" textAnchor="end">
          0%
        </text>
        <text x={PAD.left - 8} y={height - PAD.bottom} className="axis" textAnchor="end">
          {fmtPct(worstDd, 0)}
        </text>
      </svg>
      <figcaption>
        Equity (line) and drawdown from peak (shaded).
        {effectiveIndex > 0 && (
          <>
            {" "}
            The shaded left region predates the full universe — figures spanning it
            describe a smaller strategy than the one named.
          </>
        )}
      </figcaption>
    </figure>
  );
}
