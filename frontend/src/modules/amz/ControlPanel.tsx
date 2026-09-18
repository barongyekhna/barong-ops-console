"use client";

import { useCallback, useEffect, useState } from "react";

import styles from "./AmzWorkspace.module.css";
import { getControl, getStores, lowerLadder, saveGuardrails, setKillSwitch, type AmzControl, type AmzStore } from "./api";

const STATUS_LABEL: Record<string, string> = {
  countdown: "倒计时中",
  queued: "排队",
  blocked: "护栏拦下",
  waiting_api: "等广告 API",
  executed: "已执行",
  failed: "失败",
  cancelled: "已取消",
};
const LEVEL_HINT: Record<string, string> = { L0: "只出建议", L1: "人批了才做", L2: "先通报 24 小时后做", L3: "过护栏直接做" };
const GUARD_FIELDS: { key: string; label: string; unit: string }[] = [
  { key: "daily_budget_cap", label: "每天总预算上限", unit: "$(空 = 不设)" },
  { key: "bid_max_change_pct", label: "单次出价调幅", unit: "±%" },
  { key: "budget_max_change_pct", label: "单次预算调幅", unit: "±%" },
  { key: "actions_per_day", label: "每天自动动作上限", unit: "条" },
  { key: "cpc_max", label: "单次出价上限", unit: "$(空 = 不设)" },
  { key: "breaker_ratio", label: "超支熔断线", unit: "倍(当天花费 ÷ 前 7 天日均)" },
];

/**
 * A3 管控面:每店一个总闸(手机上也能一下按到)、五道护栏、每个动作的梯子级别、执行台账。
 * 拉闸谁都能拉,开闸 / 改护栏只有老板;梯子这里只能降,升级走系统的「升级提议」建议。
 */
export function ControlPanel() {
  const [stores, setStores] = useState<AmzStore[]>([]);
  const [store, setStore] = useState<string | null>(null);
  const [data, setData] = useState<AmzControl | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getStores()
      .then((r) => {
        setStores(r.items);
        setStore((prev) => prev ?? r.items[0]?.store_code ?? null);
      })
      .catch((err) => setStatus(err instanceof Error ? err.message : String(err)));
  }, []);

  const load = useCallback(async () => {
    if (!store) return;
    try {
      const row = await getControl(store);
      setData(row);
      setDraft(Object.fromEntries(GUARD_FIELDS.map((f) => [f.key, (row.guardrails as Record<string, unknown>)[f.key] == null ? "" : String((row.guardrails as Record<string, unknown>)[f.key])])));
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    }
  }, [store]);

  useEffect(() => {
    void load();
  }, [load]);

  async function act(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await fn();
      setStatus(ok);
      await load();
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const killed = data?.guardrails.kill_switch ?? false;

  return (
    <div className={styles.workspace}>
      <div className={styles.sheetActions}>
        {stores.map((s) => (
          <button className={s.store_code === store ? styles.button : styles.linkButton} key={s.store_code} onClick={() => setStore(s.store_code)} type="button">
            {s.store_code}
          </button>
        ))}
      </div>
      {status ? <div className={styles.muted}>{status}</div> : null}
      {data ? (
        <>
          <section className={styles.panel} aria-label="总闸">
            <div className={styles.panelHead}>
              <h2>
                {data.store_code} 总闸 · {killed ? <span className={styles.bad}>已拉下</span> : <span className={styles.good}>开着</span>}
              </h2>
              <span className={styles.muted}>
                {data.shadow ? `影子期到 ${data.shadow_until}:所有动作都是 L0,只出建议` : "影子期已结束"} · 今天已执行 {data.executed_today} 条 · 最近一天花费是前 7 天日均的{" "}
                {data.spend_ratio.ratio ?? "—"} 倍(熔断线 {data.guardrails.breaker_ratio})
              </span>
            </div>
            <div className={styles.sheetActions}>
              {killed ? (
                data.can_release ? (
                  <button className={styles.button} disabled={busy} onClick={() => void act(() => setKillSwitch(data.store_code, false), "总闸已打开")} type="button">
                    打开总闸(只有老板)
                  </button>
                ) : (
                  <span className={styles.muted}>总闸拉下了,只有老板能打开</span>
                )
              ) : (
                <button
                  className={styles.button}
                  disabled={busy}
                  onClick={() => {
                    const reason = window.prompt(`拉下 ${data.store_code} 的总闸?这家店所有自动动作立刻停,倒计时中的全部取消。写一句原因:`, "");
                    if (reason !== null) void act(() => setKillSwitch(data.store_code, true, reason), "总闸已拉下");
                  }}
                  style={{ fontSize: 16, padding: "12px 20px" }}
                  type="button"
                >
                  ⛔ 拉下总闸
                </button>
              )}
            </div>
          </section>

          <section className={styles.panel} aria-label="梯子">
            <div className={styles.panelHead}>
              <h2>自动化梯子 · 按动作</h2>
              <span className={styles.muted}>升级要系统先提议、有授权的人放行;这里只能降 · 不在表里的动作(改价 / 标题 / 主图 / 建删活动 / 排产 / 图片)永远人做</span>
            </div>
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>动作</th>
                    <th>级别</th>
                    <th>封顶</th>
                    <th>现在生效</th>
                    <th>离升级还差</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.ladder.map((row) => (
                    <tr key={row.action_type}>
                      <td>{row.label}</td>
                      <td>
                        {row.level} <span className={styles.muted}>{LEVEL_HINT[row.level]}</span>
                      </td>
                      <td>{row.max_level}</td>
                      <td className={row.effective === "L0" ? styles.muted : styles.good}>{row.effective}</td>
                      <td className={styles.muted}>{row.upgrade_ready ? "够了,等系统提议" : row.missing.join(";") || "已封顶"}</td>
                      <td>
                        {row.level !== "L0" ? (
                          <button className={styles.linkButton} disabled={busy} onClick={() => void act(() => lowerLadder(data.store_code, row.action_type, "L0"), `${row.label} 已降到 L0`)} type="button">
                            降到 L0
                          </button>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className={styles.panel} aria-label="护栏">
            <div className={styles.panelHead}>
              <h2>五道护栏 + 熔断</h2>
              <span className={styles.muted}>任何级别都绕不过;只有老板能改,每项有上下限</span>
            </div>
            <div className={styles.sheetRow}>
              {GUARD_FIELDS.map((f) => (
                <label key={f.key}>
                  {f.label}({f.unit})
                  <input disabled={!data.can_release} inputMode="decimal" onChange={(e) => setDraft((prev) => ({ ...prev, [f.key]: e.target.value }))} value={draft[f.key] ?? ""} />
                </label>
              ))}
            </div>
            {data.can_release ? (
              <div className={styles.sheetActions}>
                <button
                  className={styles.button}
                  disabled={busy}
                  onClick={() => void act(() => saveGuardrails(data.store_code, Object.fromEntries(GUARD_FIELDS.map((f) => [f.key, draft[f.key]?.trim() ? Number(draft[f.key]) : null]))), "护栏已保存")}
                  type="button"
                >
                  保存护栏
                </button>
              </div>
            ) : null}
          </section>

          <section className={styles.panel} aria-label="执行台账">
            <div className={styles.panelHead}>
              <h2>执行台账</h2>
              <span className={styles.muted}>每条:做了什么、为什么、谁批的、护栏、回读、7/14/28 天回看</span>
            </div>
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>时间</th>
                    <th>动作</th>
                    <th>级别</th>
                    <th>状态</th>
                    <th>回读</th>
                    <th>回看</th>
                  </tr>
                </thead>
                <tbody>
                  {data.ledger.map((row) => (
                    <tr key={row.id}>
                      <td className={styles.muted}>{(row.executed_at ?? row.created_at ?? "").slice(0, 16).replace("T", " ")}</td>
                      <td>
                        {row.label}
                        <div className={styles.muted}>{String(row.op.term ?? row.op.target ?? row.op.asin ?? "")}</div>
                      </td>
                      <td>{row.level}</td>
                      <td className={row.status === "blocked" || row.status === "failed" ? styles.bad : row.status === "executed" ? styles.good : undefined}>
                        {STATUS_LABEL[row.status] ?? row.status}
                        {row.countdown_until ? <div className={styles.muted}>到 {row.countdown_until.slice(0, 16).replace("T", " ")}</div> : null}
                        {row.blocked_reason ? <div className={styles.muted}>{row.blocked_reason}</div> : null}
                      </td>
                      <td>{row.readback_ok == null ? "—" : row.readback_ok ? "对得上" : <span className={styles.bad}>对不上</span>}</td>
                      <td>{row.outcome ?? "—"}</td>
                    </tr>
                  ))}
                  {data.ledger.length === 0 ? (
                    <tr>
                      <td className={styles.muted} colSpan={6}>
                        还没有动作。影子期结束、梯子升到 L1 以后,你放行的建议才会进这里
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}
