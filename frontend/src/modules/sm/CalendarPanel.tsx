"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { OverlayModal } from "@/components/overlay-modal";

import styles from "./SmWorkspace.module.css";
import {
  type Calendar,
  type Job,
  type Pillar,
  type Platform,
  type Slot,
  PILLAR_LABEL,
  PLATFORM_LABEL,
  WEEKDAY_LABEL,
  codexPromptForGap,
  getCalendar,
  mediaUrl,
  swapSlot,
  writeSlot,
} from "./api";

const PLATFORMS: Platform[] = ["pinterest", "instagram", "facebook"];

function isoDay(offset: number): string {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return d.toISOString().slice(0, 10);
}

function SlotChip({ slot, onOpen }: { slot: Slot; onOpen: () => void }) {
  const thumb = slot.post?.media?.[0]?.thumbnail_url ?? slot.media_plan.thumbnail_urls[0] ?? null;
  const src = mediaUrl(thumb);
  return (
    <button className={styles.slot} data-status={slot.status} onClick={onOpen} type="button">
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img alt="" className={styles.thumb} src={src} />
      ) : (
        <span className={styles.thumbEmpty}>{slot.media_plan.text_card ? "字卡" : slot.gap ? "缺图" : "—"}</span>
      )}
      <span className={styles.slotBody}>
        <span className={styles.slotTitle}>{slot.post?.title || slot.label.split(" · ").slice(2).join(" · ") || slot.pillar_label}</span>
        <span className={styles.slotMeta}>
          <span className={styles.pillar} data-pillar={slot.pillar}>{slot.pillar_label}</span>
          <span className={styles.status} data-status={slot.post?.review_status === "approved" ? "approved" : slot.status}>
            {slot.post ? (slot.post.review_status === "approved" ? "已批" : slot.post.review_status === "rejected" ? "已驳回" : "待审") : slot.status}
          </span>
          {slot.gap ? <span className={styles.gapBadge}>{slot.gap.lane}</span> : null}
          {slot.window_pt ? <span>{slot.window_pt}</span> : null}
        </span>
      </span>
    </button>
  );
}

export function CalendarPanel({ jobs, onChanged, refreshTick }: { jobs: Job[]; onChanged: () => void; refreshTick: number }) {
  const [calendar, setCalendar] = useState<Calendar | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Slot | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [swapPillar, setSwapPillar] = useState<Pillar>("P2");
  const from = useMemo(() => isoDay(0), []);
  const to = useMemo(() => isoDay(27), []);

  useEffect(() => {
    let cancelled = false;
    getCalendar(from, to)
      .then((data) => {
        if (!cancelled) {
          setCalendar(data);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [from, to, refreshTick]);

  const days = useMemo(() => Array.from({ length: 28 }, (_, i) => isoDay(i)), []);
  const byCell = useMemo(() => {
    const map = new Map<string, Slot[]>();
    for (const slot of calendar?.slots ?? []) {
      const key = `${slot.day}|${slot.platform}`;
      map.set(key, [...(map.get(key) ?? []), slot]);
    }
    return map;
  }, [calendar]);

  const jobForSlot = (slotId: string) => jobs.find((j) => j.slot_id === slotId && (j.status === "pending" || j.status === "running"));

  const closeDrawer = useCallback(() => setSelected(null), []);

  const handleWrite = async (slot: Slot) => {
    setBusy("write");
    try {
      await writeSlot(slot.id);
      setSelected(null);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  const handleSwap = async (slot: Slot) => {
    setBusy("swap");
    try {
      await swapSlot(slot.id, { pillar: swapPillar, reason: `手动换成${PILLAR_LABEL[swapPillar]}` });
      setSelected(null);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  const handleCodex = async (slot: Slot) => {
    const prompt = codexPromptForGap(slot.seed_product_sku ?? slot.seed_product_id ?? "", slot.gap?.k_position ?? null);
    try {
      await navigator.clipboard.writeText(prompt);
    } catch {
      // 剪贴板不可用也没关系，deep link 会预填
    }
    window.location.href = `codex://new?prompt=${encodeURIComponent(prompt)}`;
  };

  return (
    <section className={styles.panel}>
      <div className={styles.panelHead}>
        <h2 className={styles.panelTitle}>未来四周 · 按平台分列</h2>
        <span className={styles.muted}>
          {calendar ? `${calendar.slots.length} 格 · ${calendar.slots.filter((s) => s.status === "blocked").length} 格没源头` : "加载中…"}
        </span>
      </div>
      {error ? <div className={styles.error}>{error}</div> : null}
      {calendar && calendar.slots.length === 0 ? (
        <p className={styles.muted}>还没有日历。登记渠道后点右上角「重排未来 28 天」。</p>
      ) : null}
      <div className={styles.calendarWrap}>
        <div className={styles.calendar}>
          <div className={styles.calHead}>日期</div>
          {PLATFORMS.map((p) => (
            <div className={styles.calHead} key={p}>{PLATFORM_LABEL[p]}</div>
          ))}
          {days.map((day) => {
            const weekday = (new Date(`${day}T00:00:00`).getDay() + 6) % 7;
            return (
              <div key={day} style={{ display: "contents" }}>
                <div className={styles.calDay} data-weekend={weekday >= 5}>
                  <b>{day.slice(5)}</b>
                  <span>周{WEEKDAY_LABEL[weekday]}</span>
                </div>
                {PLATFORMS.map((p) => (
                  <div className={styles.calCell} key={`${day}-${p}`}>
                    {(byCell.get(`${day}|${p}`) ?? []).map((slot) => (
                      <SlotChip key={slot.id} onOpen={() => setSelected(slot)} slot={slot} />
                    ))}
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      </div>

      {selected ? (
        <OverlayModal label="日历格" onClose={closeDrawer} placement="drawer" width="min(560px, 100%)">
          <div className={styles.drawer}>
            <h3 className={styles.drawerTitle}>{selected.label}</h3>
            <dl className={styles.kv}>
              <dt>平台 / 支柱</dt>
              <dd>{PLATFORM_LABEL[selected.platform]} · {selected.pillar_label} · {selected.post_kind ?? ""}</dd>
              <dt>状态</dt>
              <dd>
                <span className={styles.status} data-status={selected.status}>{selected.status}</span>
                {selected.swap_reason ? <span className={styles.muted}> · {selected.swap_reason}</span> : null}
                {jobForSlot(selected.id) ? <span className={styles.muted}> · 写手任务在飞</span> : null}
              </dd>
              <dt>源头</dt>
              <dd>{selected.source_type}{selected.seed_product_sku ? ` · ${selected.seed_product_sku}` : ""}</dd>
              <dt>图片计划</dt>
              <dd>
                {selected.media_plan.asset_ids.length} 张
                {selected.media_plan.needs_layout ? " · 需版式渲染" : ""}
                {selected.media_plan.text_card ? " · 纯字卡" : ""}
                {selected.media_plan.mirror_of_slot ? " · 镜像 Instagram" : ""}
              </dd>
              {selected.gap ? (
                <>
                  <dt>缺口</dt>
                  <dd>
                    <span className={styles.gapBadge}>{selected.gap.lane}</span> {selected.gap.brief_text}
                    {selected.gap.k_position ? <div className={styles.muted}>K 简报社媒位 {selected.gap.k_position}</div> : null}
                  </dd>
                </>
              ) : null}
            </dl>
            {selected.media_plan.thumbnail_urls.length ? (
              <div className={styles.mediaRow}>
                {selected.media_plan.thumbnail_urls.map((t, i) =>
                  mediaUrl(t) ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img alt="" className={styles.thumb} key={`${t}-${i}`} src={mediaUrl(t) ?? ""} style={{ width: 72, height: 72 }} />
                  ) : null,
                )}
              </div>
            ) : null}
            {selected.post ? (
              <div className={styles.caption}>
                <b>{selected.post.title}</b>
                {selected.post.first_line ? <div>{selected.post.first_line}</div> : null}
                <div className={styles.muted}>
                  审核 {selected.post.review_status} · 审计 {selected.post.audit_clean === null ? "未跑" : selected.post.audit_clean ? "干净" : `${selected.post.audit_unresolved ?? "?"} 处待处理`}
                </div>
              </div>
            ) : null}
            <div className={styles.actions}>
              {selected.status === "planned" || selected.status === "swapped" ? (
                <button className={styles.btnPrimary} disabled={busy !== null || Boolean(jobForSlot(selected.id))} onClick={() => handleWrite(selected)} type="button">
                  {jobForSlot(selected.id) ? "已在队列" : "写这一格"}
                </button>
              ) : null}
              {selected.post ? (
                <a className={styles.btn} href={`/sm?tab=posts&post=${selected.post.id}`}>看帖子</a>
              ) : null}
              {selected.post ? (
                <a className={styles.btn} href="/content-desk">去内容台审</a>
              ) : null}
              {selected.gap?.lane === "mcp" ? (
                <button className={styles.btn} onClick={() => handleCodex(selected)} type="button">唤起 Codex 作图</button>
              ) : null}
            </div>
            {!selected.post && selected.status !== "posted" ? (
              <div className={styles.actions}>
                <select className={styles.select} onChange={(e) => setSwapPillar(e.target.value as Pillar)} style={{ maxWidth: 160 }} value={swapPillar}>
                  {(Object.keys(PILLAR_LABEL) as Pillar[]).map((p) => (
                    <option key={p} value={p}>{PILLAR_LABEL[p]}</option>
                  ))}
                </select>
                <button className={styles.btn} disabled={busy !== null} onClick={() => handleSwap(selected)} type="button">换支柱</button>
                <span className={styles.muted}>换柱由排期器重新挑源头和图</span>
              </div>
            ) : null}
          </div>
        </OverlayModal>
      ) : null}
    </section>
  );
}
