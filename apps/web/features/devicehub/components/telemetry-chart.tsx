/**
 * features/devicehub/components/telemetry-chart.tsx
 * -------------------------------------------------
 * Purpose:    Dependency-free SVG charts for distance and the three IR
 *             channels. Two panels because cm and raw ADC counts must not
 *             share a scale.
 * Dependencies: telemetry-chart.module.css
 * Scope:      Dashboard detail view.
 */

"use client";

import type { ChartPoint } from "@/features/devicehub/types";
import styles from "./telemetry-chart.module.css";

const WIDTH = 1000;
const HEIGHT = 200;
const PAD = { top: 10, right: 12, bottom: 20, left: 42 };

interface Series {
  label: string;
  color: string;
  values: Array<number | null>;
}

function innerWidth(): number {
  return WIDTH - PAD.left - PAD.right;
}

function innerHeight(): number {
  return HEIGHT - PAD.top - PAD.bottom;
}

function xAt(index: number, count: number): number {
  if (count <= 1) return PAD.left + innerWidth() / 2;
  return PAD.left + (index / (count - 1)) * innerWidth();
}

function yAt(value: number, max: number): number {
  const clamped = Math.min(Math.max(value, 0), max);
  return PAD.top + innerHeight() - (clamped / max) * innerHeight();
}

/** A null breaks the line instead of drawing through a sensor dropout. */
function pathFor(values: Array<number | null>, max: number): string {
  const commands: string[] = [];
  let penDown = false;

  values.forEach((value, index) => {
    if (value === null || !Number.isFinite(value)) {
      penDown = false;
      return;
    }
    const command = penDown ? "L" : "M";
    commands.push(
      `${command}${xAt(index, values.length).toFixed(1)} ${yAt(value, max).toFixed(1)}`,
    );
    penDown = true;
  });

  return commands.join(" ");
}

function timeLabel(ts: number): string {
  return new Date(ts).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

interface PanelProps {
  title: string;
  unit: string;
  max: number;
  series: Series[];
  points: ChartPoint[];
}

function Panel({ title, unit, max, series, points }: PanelProps) {
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((fraction) => fraction * max);
  const first = points[0];
  const last = points[points.length - 1];
  const count = series.reduce(
    (total, s) => total + s.values.filter((v) => v !== null).length,
    0,
  );

  return (
    <figure className={styles.panel}>
      <figcaption className={styles.caption}>
        <span className={styles.panelTitle}>{title}</span>
        <span className={styles.panelMeta}>
          {unit} · {points.length} samples
        </span>
      </figcaption>

      <svg
        className={styles.svg}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={`${title} over time, ${count} readings, ${points.length} samples`}
      >
        {ticks.map((tick) => {
          const y = yAt(tick, max);
          return (
            <g key={tick}>
              <line
                className={styles.grid}
                x1={PAD.left}
                x2={WIDTH - PAD.right}
                y1={y}
                y2={y}
              />
              <text className={styles.tick} x={PAD.left - 8} y={y + 4}>
                {Math.round(tick)}
              </text>
            </g>
          );
        })}

        {series.map((s) => (
          <path
            key={s.label}
            className={styles.line}
            d={pathFor(s.values, max)}
            stroke={s.color}
            vectorEffect="non-scaling-stroke"
          />
        ))}

        {first ? (
          <text className={styles.time} x={PAD.left} y={HEIGHT - 4}>
            {timeLabel(first.ts)}
          </text>
        ) : null}
        {last ? (
          <text
            className={styles.time}
            x={WIDTH - PAD.right}
            y={HEIGHT - 4}
            textAnchor="end"
          >
            {timeLabel(last.ts)}
          </text>
        ) : null}
      </svg>

      <ul className={styles.legend}>
        {series.map((s) => (
          <li key={s.label} className={styles.legendItem}>
            <span
              className={styles.swatch}
              style={{ backgroundColor: s.color }}
              aria-hidden="true"
            />
            {s.label}
          </li>
        ))}
      </ul>
    </figure>
  );
}

export function TelemetryChart({ points }: { points: ChartPoint[] }) {
  if (points.length === 0) return null;

  const distancePeak = points.reduce(
    (peak, point) =>
      point.distance !== null && point.distance > peak ? point.distance : peak,
    0,
  );
  const distanceMax = Math.max(25, Math.ceil(distancePeak / 25) * 25);

  return (
    <div className={styles.container}>
      <Panel
        title="Distance"
        unit="cm"
        max={distanceMax}
        points={points}
        series={[
          {
            label: "Ultrasonic",
            color: "var(--accent)",
            values: points.map((p) => p.distance),
          },
        ]}
      />
      <Panel
        title="Line sensors"
        unit="raw ADC"
        max={1023}
        points={points}
        series={[
          { label: "L", color: "var(--green)", values: points.map((p) => p.l) },
          {
            label: "C",
            color: "var(--accent-ink)",
            values: points.map((p) => p.c),
          },
          {
            label: "R",
            color: "var(--orange)",
            values: points.map((p) => p.r),
          },
        ]}
      />
    </div>
  );
}
