"use client";

import { AlertTriangle, Loader2, Search } from "lucide-react";
import type { FormEvent } from "react";

import styles from "./RadarScan.module.css";

type RadarCounts = {
  matched: number | null;
  processed: number | null;
  pass: number | null;
  aiPass: number | null;
};

const GOLDEN_ANGLE = 137.508;

function blipPositions(count: number, seedOffset: number) {
  const items: Array<{ left: string; top: string; delay: string }> = [];
  const bounded = Math.max(0, Math.min(count, 28));
  for (let index = 0; index < bounded; index += 1) {
    const angle = ((index + seedOffset) * GOLDEN_ANGLE * Math.PI) / 180;
    const radius = 14 + ((index * 17 + seedOffset * 7) % 30); // 14%~44% 半径
    const left = 50 + radius * Math.cos(angle);
    const top = 50 + radius * Math.sin(angle);
    items.push({
      left: `${left.toFixed(1)}%`,
      top: `${top.toFixed(1)}%`,
      delay: `${((index * 331) % 2600) / 1000}s`,
    });
  }
  return items;
}

export function RadarScan({
  running,
  query,
  onQueryChange,
  onSubmit,
  counts,
  statusText,
  error,
  runError,
}: {
  running: boolean;
  query: string;
  onQueryChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  counts: RadarCounts;
  statusText: string | null;
  error: string | null;
  runError: string | null;
}) {
  const passBlips = blipPositions(counts.pass ?? 0, 3);
  const scanBlips = blipPositions(
    Math.max(0, (counts.processed ?? 0) - (counts.pass ?? 0)),
    11,
  );

  return (
    <section className={styles.radarBand} data-running={running ? "true" : "false"}>
      <div className={styles.radarStage}>
        <div className={styles.radar}>
          <div className={styles.ring} data-ring="1" />
          <div className={styles.ring} data-ring="2" />
          <div className={styles.ring} data-ring="3" />
          <div className={styles.crosshair} />
          <div className={styles.sweep} />
          {scanBlips.map((blip, index) => (
            <span
              key={`scan-${index}`}
              className={styles.blip}
              data-kind="scan"
              style={{ left: blip.left, top: blip.top, animationDelay: blip.delay }}
            />
          ))}
          {passBlips.map((blip, index) => (
            <span
              key={`pass-${index}`}
              className={styles.blip}
              data-kind="pass"
              style={{ left: blip.left, top: blip.top, animationDelay: blip.delay }}
            />
          ))}
          <div className={styles.radarCore} />
        </div>
        <div className={styles.radarReadout}>
          <span>
            扫描 {counts.processed ?? 0} · 命中 {counts.pass ?? 0}
          </span>
          <span data-status>{running ? "SCANNING" : statusText || "STANDBY"}</span>
        </div>
      </div>

      <div className={styles.consolePanel}>
        <span className={styles.kicker}>R-A · TARGETED PROBE</span>
        <h2>定向探测</h2>
        <p className={styles.lead}>
          输入关键词或类目，雷达只扫 R-W 仓库里匹配的产品：DeepSeek 初筛 →
          1688 词搜找同款（图片比对确认，词搜无果才动用图搜额度）→ 利润硬门 →
          Rainforest 竞争 → GPT 终审。探测启动时自动巡库会让位，探测完自动恢复。
        </p>
        <form className={styles.form} onSubmit={onSubmit}>
          <div className={styles.inputRow}>
            <Search size={17} />
            <input
              id="ra-auto-query"
              maxLength={120}
              placeholder="例如：露营桌、办公收纳、庭院灯"
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
            />
            <button disabled={running || !query.trim()} type="submit">
              {running ? (
                <Loader2 className={styles.spinIcon} size={16} />
              ) : (
                <Search size={16} />
              )}
              <span>{running ? "探测进行中" : "启动探测"}</span>
            </button>
          </div>
        </form>
        {runError ? (
          <p className={styles.errorLine}>
            <AlertTriangle size={14} /> {runError}
          </p>
        ) : null}
        {error ? (
          <p className={styles.warnLine}>
            <AlertTriangle size={14} /> 状态接口暂时不可读（页面数据不会清空）：{error}
          </p>
        ) : null}
      </div>
    </section>
  );
}
