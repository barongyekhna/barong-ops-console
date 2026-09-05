"use client";

import type { HomeTrafficDay } from "./home-api";

type TrafficBarsProps = {
  days: HomeTrafficDay[];
  height?: number;
  /** 最后一根柱是否是「今天」——用主色标出日期。 */
  highlightLast?: boolean;
};

const WIDTH = 600;
const PAD_LEFT = 30;
const PAD_RIGHT = 8;
const PAD_TOP = 12;
const PAD_BOTTOM = 22;

/**
 * 纯 SVG 双柱图：深柱访客、浅柱浏览，x 轴每根柱下标日期。
 * 只用主题令牌上色，白天黑夜和三皮肤自动跟随。
 */
export function TrafficBars({ days, height = 150, highlightLast = true }: TrafficBarsProps) {
  const count = Math.max(1, days.length);
  const max = Math.max(1, ...days.map((day) => day.views));
  const innerWidth = WIDTH - PAD_LEFT - PAD_RIGHT;
  const slot = innerWidth / count;
  const barWidth = Math.min(slot * 0.62, 26);
  const y = (value: number) => PAD_TOP + (height - PAD_TOP - PAD_BOTTOM) * (1 - value / max);
  const labelStep = count > 14 ? Math.ceil(count / 10) : 1;
  const ticks = [0, max / 2, max];

  return (
    <svg
      aria-label="每日浏览与访客"
      className="hs-bars"
      preserveAspectRatio="none"
      role="img"
      style={{ height: `${height}px` }}
      viewBox={`0 0 ${WIDTH} ${height}`}
    >
      {ticks.map((tick) => (
        <g key={tick}>
          <line
            stroke="var(--color-line)"
            strokeWidth="1"
            x1={PAD_LEFT}
            x2={WIDTH - PAD_RIGHT}
            y1={y(tick)}
            y2={y(tick)}
          />
          <text className="hs-bars-tick" textAnchor="end" x={PAD_LEFT - 4} y={y(tick) + 3}>
            {Math.round(tick)}
          </text>
        </g>
      ))}
      {days.map((day, index) => {
        const x = PAD_LEFT + index * slot + (slot - barWidth) / 2;
        const isLast = index === count - 1;
        const label = day.day.slice(5);
        return (
          <g key={day.day}>
            <title>{`${day.day} · 浏览 ${day.views} · 访客 ${day.visitors}`}</title>
            <rect
              fill="color-mix(in srgb, var(--color-primary) 32%, transparent)"
              height={Math.max(0, height - PAD_BOTTOM - y(day.views))}
              rx="2"
              width={barWidth}
              x={x}
              y={y(day.views)}
            />
            <rect
              fill="var(--color-primary)"
              height={Math.max(0, height - PAD_BOTTOM - y(day.visitors))}
              rx="2"
              width={barWidth}
              x={x}
              y={y(day.visitors)}
            />
            {index % labelStep === 0 || isLast ? (
              <text
                className={isLast && highlightLast ? "hs-bars-tick hs-bars-today" : "hs-bars-tick"}
                textAnchor="middle"
                x={x + barWidth / 2}
                y={height - 6}
              >
                {label}
              </text>
            ) : null}
          </g>
        );
      })}
    </svg>
  );
}
