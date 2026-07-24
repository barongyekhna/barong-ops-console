"use client";

import { useCallback, useEffect, useState } from "react";

import { getCruiseState, toggleCruise, type RaCruiseState } from "./api";
import styles from "./CruiseSwitch.module.css";

export function CruiseSwitch() {
  const [state, setState] = useState<RaCruiseState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setState(await getCruiseState());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "读取巡航状态失败");
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 30000);
    return () => window.clearInterval(timer);
  }, [load]);

  const onToggle = async () => {
    if (!state) return;
    setBusy(true);
    setError(null);
    try {
      setState(await toggleCruise(!state.paused));
    } catch (e) {
      setError(e instanceof Error ? e.message : "切换失败");
    } finally {
      setBusy(false);
    }
  };

  if (!state) {
    return (
      <div className={styles.bar}>
        <span className={styles.loading}>读取自动巡航状态…</span>
      </div>
    );
  }

  const paused = state.paused;
  const usage = state.today;
  const providerText = usage.providers
    .map((p) => `${p.label} ${p.used}`)
    .join(" · ");

  return (
    <div
      className={styles.bar}
      data-paused={paused ? "true" : "false"}
    >
      <div className={styles.left}>
        <span className={styles.dot} data-paused={paused ? "true" : "false"} />
        <div className={styles.status}>
          <strong>{paused ? "自动巡航已暂停" : "自动巡航中"}</strong>
          <span className={styles.hint}>
            {paused
              ? "24 小时自动选品已停止，不再自动消耗 DeepSeek / 4sapi。手动选品照常可用。"
              : "系统正在 24 小时自动选品，按次消耗 DeepSeek / 4sapi。"}
          </span>
        </div>
      </div>

      <div className={styles.right}>
        <div className={styles.usage}>
          <span>今日已消耗</span>
          <strong>AI 评估 {usage.ai_evaluations} 次</strong>
          {providerText ? <em>{providerText}</em> : null}
        </div>
        <button
          className={paused ? styles.resume : styles.pause}
          disabled={busy}
          onClick={() => void onToggle()}
          type="button"
        >
          {busy ? "切换中…" : paused ? "▶ 恢复巡航" : "⏸ 暂停巡航"}
        </button>
      </div>

      {error ? <span className={styles.err}>{error}</span> : null}
    </div>
  );
}
