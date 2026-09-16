"use client";

import styles from "./AmzOverview.module.css";
import type { AmzSeriesDay } from "./api";

type Props = {
  days: AmzSeriesDay[];
  pick: (day: AmzSeriesDay) => number | null;
  unit: "%" | "$";
  target?: number;
  targetLabel?: string;
  tone: "accent" | "good";
};

const W = 520;
const H = 170;
const PAD = { l: 44, r: 12, t: 16, b: 26 };

/**
 * 纯 SVG 折线(照 home/TrafficBars 的路子:只用主题令牌上色,白天黑夜三皮肤自动跟随)。
 * 单轴;缺值(当天没销售)断线不画零。种子期是日粒度,A1 接上 API 后换「今天 vs 昨天按小时累计」。
 */
export function AmzSeriesChart({ days, pick, unit, target, targetLabel, tone }: Props) {
  const points = days.map((day, index) => ({ index, date: day.date, value: pick(day) }));
  const values = points.map((p) => p.value).filter((v): v is number => v !== null && Number.isFinite(v));
  if (values.length === 0) {
    return <div className={styles.empty}>没有数据。</div>;
  }
  const maxRaw = Math.max(...values, target ?? 0);
  const max = niceMax(maxRaw);
  const innerW = W - PAD.l - PAD.r;
  const innerH = H - PAD.t - PAD.b;
  const x = (i: number) => PAD.l + (points.length <= 1 ? 0 : (i / (points.length - 1)) * innerW);
  const y = (v: number) => PAD.t + innerH - (v / max) * innerH;
  const stroke = tone === "good" ? "var(--color-success)" : "var(--color-primary)";

  // 断线:null 处断开
  const segments: string[] = [];
  let current: string[] = [];
  for (const p of points) {
    if (p.value === null) {
      if (current.length) segments.push(current.join(" "));
      current = [];
      continue;
    }
    current.push(`${current.length ? "L" : "M"}${x(p.index).toFixed(1)} ${y(p.value).toFixed(1)}`);
  }
  if (current.length) segments.push(current.join(" "));
  const last = [...points].reverse().find((p) => p.value !== null);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => max * f);
  const fmt = (v: number) => (unit === "%" ? `${Math.round(v)}%` : v >= 1000 ? `$${(v / 1000).toFixed(v >= 10000 ? 0 : 1)}k` : `$${Math.round(v)}`);
  const labelEvery = Math.max(1, Math.ceil(points.length / 5));

  return (
    <svg className={styles.svg} viewBox={`0 0 ${W} ${H}`} role="img" aria-label="走势">
      {ticks.map((t) => (
        <g key={t}>
          <line stroke="var(--color-line)" strokeWidth="1" x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} />
          <text className={styles.tick} textAnchor="end" x={PAD.l - 6} y={y(t) + 3}>
            {fmt(t)}
          </text>
        </g>
      ))}
      {target !== undefined ? (
        <g>
          <line stroke="var(--color-subtle)" strokeDasharray="4 5" strokeWidth="1" x1={PAD.l} x2={W - PAD.r} y1={y(target)} y2={y(target)} />
          <text className={styles.tick} textAnchor="end" x={W - PAD.r} y={y(target) - 4}>
            {targetLabel ?? `目标 ${fmt(target)}`}
          </text>
        </g>
      ) : null}
      {segments.map((d, i) => (
        <path d={d} fill="none" key={i} stroke={stroke} strokeLinejoin="round" strokeWidth="2" />
      ))}
      {last && last.value !== null ? (
        <g>
          <circle cx={x(last.index)} cy={y(last.value)} fill={stroke} r="4" stroke="var(--color-canvas)" strokeWidth="2" />
          <text className={styles.endLabel} textAnchor="end" x={Math.min(x(last.index), W - PAD.r) - 8} y={y(last.value) - 8}>
            {fmt(last.value)}
          </text>
        </g>
      ) : null}
      {points.map((p) =>
        p.index % labelEvery === 0 || p.index === points.length - 1 ? (
          <text className={styles.tick} key={p.date} textAnchor="middle" x={x(p.index)} y={H - 8}>
            {p.date.slice(5)}
          </text>
        ) : null,
      )}
    </svg>
  );
}

function niceMax(value: number) {
  if (value <= 0) return 1;
  const exp = Math.pow(10, Math.floor(Math.log10(value)));
  const n = value / exp;
  const nice = n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10;
  return nice * exp;
}
