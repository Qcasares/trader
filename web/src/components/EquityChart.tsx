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
 *
 * Drawn in CSS pixels, at the width it is given. It used to draw on a fixed
 * canvas 900 units wide that the browser scaled to fit the card, and the text
 * scaled with everything else: 10 units rendered at 3.6px on a phone, too small
 * to read, and at 12.8px on a desktop, too wide for the margin reserved for it,
 * so the "$" of a six-figure axis label was cut off (web/DESIGN.md T-1, E-5).
 * The chart now measures its figure and uses that many units, so the axis text
 * is the size the stylesheet sets (`.axis`, `--t-sm`) at every width, and the
 * left margin is sized from the labels it has to hold rather than guessed.
 */

import { useEffect, useMemo, useState } from "react";
import type { EquityPoint } from "@/lib/api";
import { fmtPct, fmtUsd } from "@/lib/format";

interface Props {
  points: EquityPoint[];
  /** Sessions before this had an incomplete universe; shaded and labelled. */
  effectiveStart?: string | null;
  /**
   * The height at the width the chart was designed at. A narrower chart keeps
   * the proportion, down to a floor below which the drawdown panel is a sliver.
   */
  height?: number;
}

/** The width the chart was designed at, and draws at until it has measured. */
const DESIGN_WIDTH = 900;
const MIN_HEIGHT = 240;
/** `--t-sm`, the axis text's size (`.axis` in globals.css), in CSS px. */
const AXIS_TEXT_PX = 12;
/**
 * A monospace glyph's advance in em, rounded up over the faces `--mono` names:
 * DejaVu Sans Mono and Menlo 0.602, SF Mono 0.6, Consolas 0.55. The margins
 * are reserved from it, because the server renders before any text can be
 * measured.
 */
const MONO_ADVANCE = 0.62;
/** The gap between an axis label and the plot it labels. */
const LABEL_GAP = 8;
const PAD = { top: 16, right: 16, bottom: 28 };
const DRAWDOWN_RATIO = 0.3;

const textWidth = (text: string) => Math.ceil(text.length * AXIS_TEXT_PX * MONO_ADVANCE);

/**
 * The width, in CSS px, of the element the returned ref is attached to; null
 * until it has been measured. A callback ref rather than an object one: the
 * figure is not rendered while there are too few points to draw, and the
 * measurement has to start whenever it appears.
 */
function useWidth(): [(element: HTMLElement | null) => void, number | null] {
  const [element, setElement] = useState<HTMLElement | null>(null);
  const [width, setWidth] = useState<number | null>(null);
  useEffect(() => {
    if (!element) return;
    const measure = () => {
      const next = Math.floor(element.getBoundingClientRect().width);
      if (next > 0) setWidth(next);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [element]);
  return [setElement, width];
}

export function EquityChart({ points, effectiveStart, height = 340 }: Props) {
  const [figure, measured] = useWidth();
  const width = measured ?? DESIGN_WIDTH;
  const chartHeight =
    measured === null
      ? height
      : Math.max(MIN_HEIGHT, Math.round((height * width) / DESIGN_WIDTH));

  const geometry = useMemo(() => {
    if (points.length < 2) return null;

    const equities = points.map((p) => p.equity);
    const minEq = Math.min(...equities);
    const maxEq = Math.max(...equities);
    const span = maxEq - minEq || 1;
    const worstDd = Math.min(...points.map((p) => p.drawdown_pct), 0);
    const ddSpan = Math.abs(worstDd) || 0.01;

    // A scale's ticks are positions, not amounts anyone reads to the cent, and
    // the cents are what pushed the widest of them past its margin.
    const gridValues = [minEq, (minEq + maxEq) / 2, maxEq];
    const equityLabels = gridValues.map((value) => fmtUsd(value, 0));
    const ddLabels = [fmtPct(0, 0), fmtPct(worstDd, 0)];
    const left =
      Math.max(...[...equityLabels, ...ddLabels].map(textWidth)) + LABEL_GAP + 4;

    const equityHeight = chartHeight * (1 - DRAWDOWN_RATIO);
    const ddHeight = chartHeight * DRAWDOWN_RATIO;
    const plotWidth = Math.max(width - left - PAD.right, 1);

    const x = (i: number) => left + (i / (points.length - 1)) * plotWidth;
    const yEq = (v: number) =>
      PAD.top + (1 - (v - minEq) / span) * (equityHeight - PAD.top);
    const yDd = (v: number) =>
      equityHeight + (Math.abs(v) / ddSpan) * (ddHeight - PAD.bottom);

    const equityPath = points.map((p, i) => `${x(i)},${yEq(p.equity)}`).join(" ");
    const ddPath = points.map((p, i) => `${x(i)},${yDd(p.drawdown_pct)}`).join(" ");
    const ddArea = `${left},${equityHeight} ${ddPath} ${x(points.length - 1)},${equityHeight}`;

    // Where the full universe finally existed. Everything left of this is a
    // different strategy wearing the same name.
    let effectiveIndex = -1;
    if (effectiveStart) {
      effectiveIndex = points.findIndex((p) => p.session >= effectiveStart);
    }

    // Its label goes on whichever side of the line has room, on one line if
    // it fits and on two if it does not: at phone width neither side holds
    // the sentence whole, and a label drawn past the plot is cut off.
    let effectiveLabel: {
      x: number;
      anchor: "start" | "end";
      lines: string[];
    } | null = null;
    if (effectiveIndex > 0 && effectiveStart) {
      const at = x(effectiveIndex);
      const roomRight = width - PAD.right - (at + 6);
      const roomLeft = at - 6 - left;
      const whole = [`full universe from ${effectiveStart}`];
      const split = ["full universe", `from ${effectiveStart}`];
      const fits = (lines: string[], room: number) =>
        Math.max(...lines.map(textWidth)) <= room;
      const lines = fits(whole, Math.max(roomRight, roomLeft)) ? whole : split;
      effectiveLabel = fits(lines, roomRight) || roomRight >= roomLeft
        ? { x: at + 6, anchor: "start", lines }
        : { x: at - 6, anchor: "end", lines };
    }

    return {
      x,
      yEq,
      left,
      gridValues,
      equityLabels,
      ddLabels,
      equityPath,
      ddArea,
      equityHeight,
      effectiveIndex,
      effectiveLabel,
    };
  }, [points, effectiveStart, width, chartHeight]);

  if (!geometry) {
    return (
      <div className="chart-empty">Not enough data points to draw a curve.</div>
    );
  }

  const {
    x,
    yEq,
    left,
    gridValues,
    equityLabels,
    ddLabels,
    equityPath,
    ddArea,
    equityHeight,
    effectiveIndex,
    effectiveLabel,
  } = geometry;

  const first = points[0];
  const last = points[points.length - 1];

  return (
    <figure className="chart" ref={figure}>
      <svg
        width={width}
        height={chartHeight}
        viewBox={`0 0 ${width} ${chartHeight}`}
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label={`Equity curve from ${first.session} to ${last.session}`}
      >
        {gridValues.map((value, i) => (
          <g key={i}>
            <line
              x1={left}
              x2={width - PAD.right}
              y1={yEq(value)}
              y2={yEq(value)}
              className="grid"
            />
            <text x={left - LABEL_GAP} y={yEq(value) + 4} className="axis" textAnchor="end">
              {equityLabels[i]}
            </text>
          </g>
        ))}

        {effectiveIndex > 0 && (
          <>
            <rect
              x={left}
              y={PAD.top}
              width={x(effectiveIndex) - left}
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
            {effectiveLabel ? (
              <text
                x={effectiveLabel.x}
                y={PAD.top + 12}
                className="effective-label"
                textAnchor={effectiveLabel.anchor}
              >
                {effectiveLabel.lines.map((line, i) => (
                  <tspan key={line} x={effectiveLabel.x} dy={i === 0 ? 0 : "1.2em"}>
                    {line}
                  </tspan>
                ))}
              </text>
            ) : null}
          </>
        )}

        <polyline points={equityPath} className="equity-line" />
        <polygon points={ddArea} className="drawdown-area" />

        <line
          x1={left}
          x2={width - PAD.right}
          y1={equityHeight}
          y2={equityHeight}
          className="axis-line"
        />
        <text x={left} y={chartHeight - 8} className="axis">
          {first.session}
        </text>
        <text x={width - PAD.right} y={chartHeight - 8} className="axis" textAnchor="end">
          {last.session}
        </text>
        {/* The drawdown axis's top, through the same formatter as its bottom,
            so the two ends of one scale cannot be written two ways; a line of
            text below the equity axis's lowest label, so the two do not touch. */}
        <text
          x={left - LABEL_GAP}
          y={equityHeight + AXIS_TEXT_PX + 4}
          className="axis"
          textAnchor="end"
        >
          {ddLabels[0]}
        </text>
        <text x={left - LABEL_GAP} y={chartHeight - PAD.bottom} className="axis" textAnchor="end">
          {ddLabels[1]}
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
