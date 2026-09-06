"use client";

import { formatDateTime } from "../home-api";
import { HomeCardShell, HomeItemList } from "../HomeCardShell";
import type { HomeCardProps, HomeDrawerProps } from "../home-types";

type Heartbeat = {
  last_success_at: string | null;
  last_attempt_at: string | null;
  stale: boolean;
  silent_seconds: number | null;
  consecutive_failures: number;
  last_error: string | null;
  expected_interval_seconds: number | null;
};

type Recent = {
  id: string;
  action: string;
  action_label: string;
  result: string;
  result_label: string;
  target_type: string;
  target_id: string;
  error_code: string | null;
  created_at: string | null;
};

function heartbeat(card: HomeCardProps["card"]): Heartbeat {
  const value = card.extra.heartbeat as Partial<Heartbeat> | undefined;
  return {
    last_success_at: value?.last_success_at ?? null,
    last_attempt_at: value?.last_attempt_at ?? null,
    stale: value?.stale ?? true,
    silent_seconds: value?.silent_seconds ?? null,
    consecutive_failures: value?.consecutive_failures ?? 0,
    last_error: value?.last_error ?? null,
    expected_interval_seconds: value?.expected_interval_seconds ?? null,
  };
}

function today(card: HomeCardProps["card"]) {
  const value = (card.extra.today ?? {}) as Record<string, number>;
  return {
    success: value.success ?? 0,
    denied: value.denied ?? 0,
    rejected: value.rejected ?? 0,
    failure: value.failure ?? 0,
  };
}

function silentLabel(beat: Heartbeat) {
  if (beat.silent_seconds === null) return "从未成功";
  const minutes = Math.round(beat.silent_seconds / 60);
  return minutes < 60 ? `${minutes} 分钟前` : `${Math.round(minutes / 60)} 小时前`;
}

const RESULT_TONE: Record<string, string> = { success: "ok", denied: "warn", rejected: "warn", failure: "bad" };

export function NijingCard({ card, onOpen }: HomeCardProps) {
  const beat = heartbeat(card);
  const counts = today(card);
  return (
    <HomeCardShell card={card} onOpen={onOpen} tag="数字员工 · 库管员" title="霓旌">
      <div className="hs-inline">
        <span className={beat.stale ? "hs-pill hs-pill-bad" : "hs-pill hs-pill-ok"}>
          {beat.stale ? "失联" : "在岗"}
        </span>
        <span className="hs-muted">最近干成活 {silentLabel(beat)}</span>
      </div>
      <div className="hs-kpis hs-kpis-3">
        <div className="hs-kpi"><b>{counts.success}</b><span>今天办成</span></div>
        <div className="hs-kpi"><b>{counts.denied + counts.rejected}</b><span>被拦 / 拒绝</span></div>
        <div className="hs-kpi"><b>{counts.failure}</b><span>失败</span></div>
      </div>
      <HomeItemList card={card} empty="今天她还没办过事。在 C19 里跟她说「入库一千条桌腿」试试。" />
    </HomeCardShell>
  );
}

export function NijingDrawer({ card }: HomeDrawerProps) {
  const beat = heartbeat(card);
  const recent = Array.isArray(card.extra.recent) ? (card.extra.recent as Recent[]) : [];
  return (
    <div className="hs-drawer-body">
      <section className="hs-block">
        <div className="hs-block-head">
          <span>心跳</span>
          <span className={beat.stale ? "hs-pill hs-pill-bad" : "hs-pill hs-pill-ok"}>{beat.stale ? "失联" : "在岗"}</span>
        </div>
        <div className="hs-health">
          <div>最近成功<span className="hs-pill hs-pill-info">{formatDateTime(beat.last_success_at)}</span></div>
          <div>最近尝试<span className="hs-pill hs-pill-info">{formatDateTime(beat.last_attempt_at)}</span></div>
          <div>连续失败<span className={beat.consecutive_failures ? "hs-pill hs-pill-bad" : "hs-pill hs-pill-ok"}>{beat.consecutive_failures}</span></div>
          <div>正常间隔<span className="hs-pill hs-pill-info">{beat.expected_interval_seconds ?? "—"} s</span></div>
        </div>
        {beat.last_error ? <div className="hs-alert">{beat.last_error}</div> : null}
        <p className="hs-muted">「失联」= 超过三个正常间隔没有干成一件活，不是没有心跳。她卡住时只会在 C19 里说一次。</p>
      </section>
      <section className="hs-block">
        <div className="hs-block-head"><span>最近动作</span><span className="hs-muted">来自操作日志</span></div>
        {recent.length === 0 ? (
          <div className="hs-empty">还没有记录。</div>
        ) : (
          recent.map((row) => (
            <div className="hs-item" key={row.id}>
              <div className="hs-item-head">
                <span>
                  {row.action_label}{" "}
                  <span className={`hs-pill hs-pill-${RESULT_TONE[row.result] ?? "info"}`}>{row.result_label}</span>
                </span>
                <span className="hs-muted">{formatDateTime(row.created_at)}</span>
              </div>
              <p className="hs-item-sub">
                {row.target_type} {row.target_id}
                {row.error_code ? ` · ${row.error_code}` : ""}
              </p>
            </div>
          ))
        )}
      </section>
    </div>
  );
}
