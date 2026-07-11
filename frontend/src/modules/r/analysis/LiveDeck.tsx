"use client";

import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Boxes,
  History,
  Radio,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  approveRaReport,
  getRaGroups,
  getRaJobStatus,
  getRaQuota,
  getRaRunEvents,
  rejectRaReport,
} from "@/modules/r/analysis/api";
import type {
  RaGroupItem,
  RaQuotaPayload,
  RaRunEvent,
} from "@/modules/r/analysis/types";

import { DetailModal } from "@/modules/r/analysis/DetailModal";

import styles from "./LiveDeck.module.css";

const EVENT_POLL_MS = 4_000;
const CARD_LINGER_MS = 2_200;
const REPLAY_CARD_MS = 5_200;
const MAX_DONE = 40;

type CardLine = {
  key: string;
  text: string;
  tone: "info" | "pass" | "reject" | "warn";
};

type DeckCard = {
  asin: string;
  title: string | null;
  imageUrl: string | null;
  price: number | null;
  lines: CardLine[];
  outcome: "pending" | "pass" | "reject" | "review";
  outcomeReason: string | null;
  passChannels: string[];
  replay: boolean;
};

type DoneEntry = {
  asin: string;
  title: string | null;
  imageUrl: string | null;
  outcome: "pass" | "reject" | "review";
  channels: string[];
  reason: string | null;
};

const CHANNEL_LABELS: Record<string, string> = {
  amazon: "亚马逊",
  dtc_ad: "独立站广告",
  dtc_seo: "独立站 SEO",
};

function channelLabel(value: string) {
  return CHANNEL_LABELS[value] ?? value;
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function str(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function lineForEvent(event: RaRunEvent): CardLine | null {
  const d = event.detail ?? {};
  const verdict = event.verdict ?? "";
  switch (event.stage) {
    case "selected": {
      const price = num(d.price);
      return {
        key: `${event.seq}`,
        text: `▸ 进入流水线${price !== null ? ` · $${price.toFixed(2)}` : ""}${
          num(d.prescreen_score) !== null ? ` · 初筛分 ${num(d.prescreen_score)}` : ""
        }`,
        tone: "info",
      };
    }
    case "prescreen": {
      const score = num(d.score);
      const cached = d.cached ? "（缓存）" : "";
      if (verdict === "cut") {
        return {
          key: `${event.seq}`,
          text: `▸ DeepSeek 初筛 ${score ?? "—"} 分 · 淘汰${cached}`,
          tone: "reject",
        };
      }
      return {
        key: `${event.seq}`,
        text: `▸ DeepSeek 初筛 ${score ?? "—"} 分 · 放行${cached}`,
        tone: "pass",
      };
    }
    case "supplier_search":
      return {
        key: `${event.seq}`,
        text: `▸ 1688 图搜 ${num(d.candidate_offers) ?? 0} 家供应商 · 可定价 ${
          num(d.priced_offers) ?? 0
        }`,
        tone: "info",
      };
    case "profit_gate": {
      if (verdict === "deferred") {
        return {
          key: `${event.seq}`,
          text: "▸ 词搜未确认同款 · 图搜额度已尽，顺延明天重试",
          tone: "warn",
        };
      }
      const margin = num(d.gross_margin);
      const marginText = margin !== null ? ` · 毛利 ${(margin * 100).toFixed(1)}%` : "";
      if (verdict === "pass") {
        return {
          key: `${event.seq}`,
          text: `▸ 利润硬门 通过${marginText}`,
          tone: "pass",
        };
      }
      return {
        key: `${event.seq}`,
        text: `▸ 利润硬门 ${verdict === "quantity_pending" ? "待确认数量" : "未过"}${marginText}`,
        tone: verdict === "quantity_pending" ? "warn" : "reject",
      };
    }
    case "competition":
      return {
        key: `${event.seq}`,
        text: `▸ Rainforest 页一 · 评论墙 ${num(d.review_wall_max) ?? "—"}${
          d.cache_hit ? "（缓存 0 成本）" : ""
        }`,
        tone: "info",
      };
    case "channel_signals":
      return {
        key: `${event.seq}`,
        text: `▸ 三渠道信号 → 主路由 ${channelLabel(verdict || "—")}`,
        tone: "info",
      };
    case "deep_enrichment": {
      const trend = str(d.bsr_trend_12m);
      const trendText =
        trend === "improving"
          ? "BSR 上升"
          : trend === "declining"
            ? "BSR 下滑"
            : trend === "stable"
              ? "BSR 平稳"
              : "趋势待定";
      return {
        key: `${event.seq}`,
        text: `▸ 深挖 Keepa 12月 + 差评 ${num(d.critical_reviews) ?? 0} 条 · ${trendText}${
          verdict === "cached" ? "（缓存）" : ""
        }`,
        tone: "info",
      };
    }
    case "gpt_review":
      return {
        key: `${event.seq}`,
        text: `▸ GPT 终审 ${num(d.score) ?? "—"} 分 · ${
          verdict === "pass" ? "通过" : verdict === "reject" ? "拒绝" : "待人工"
        }`,
        tone: verdict === "pass" ? "pass" : verdict === "reject" ? "reject" : "warn",
      };
    case "opus_review":
      return {
        key: `${event.seq}`,
        text: `▸ Opus 复核 ${num(d.score) ?? "—"} 分 · ${verdict}`,
        tone: verdict === "pass" ? "pass" : "warn",
      };
    case "group_assign": {
      const channels = Array.isArray(d.pass_channels)
        ? (d.pass_channels as string[])
        : [];
      if (verdict === "pass") {
        return {
          key: `${event.seq}`,
          text: `▸ 入组 → ${channels.map(channelLabel).join(" + ") || "选品池"}`,
          tone: "pass",
        };
      }
      if (verdict === "review") {
        return { key: `${event.seq}`, text: "▸ 进入待滑堆（等你亲手滑）", tone: "warn" };
      }
      return {
        key: `${event.seq}`,
        text: `▸ 终审淘汰${str(d.reason) ? ` · ${str(d.reason)}` : ""}`,
        tone: "reject",
      };
    }
    default:
      return null;
  }
}

function isTerminalEvent(event: RaRunEvent): DeckCard["outcome"] | null {
  if (event.stage === "prescreen" && event.verdict === "cut") {
    return "reject";
  }
  if (
    event.stage === "profit_gate" &&
    event.verdict &&
    ["reject", "blocked", "deferred"].includes(event.verdict)
  ) {
    return "reject";
  }
  if (event.stage === "group_assign") {
    if (event.verdict === "pass") return "pass";
    if (event.verdict === "review") return "review";
    return "reject";
  }
  return null;
}

export function LiveDeck() {
  const [card, setCard] = useState<DeckCard | null>(null);
  const [swipe, setSwipe] = useState<"" | "left" | "right" | "down">("");
  const [done, setDone] = useState<DoneEntry[]>([]);
  const [reviewPile, setReviewPile] = useState<RaGroupItem[]>([]);
  const [quota, setQuota] = useState<RaQuotaPayload | null>(null);
  const [mode, setMode] = useState<"live" | "replay" | "idle" | "reconnecting">(
    "idle",
  );
  const pollHealthyRef = useRef(true);
  const [reviewBusy, setReviewBusy] = useState<string | null>(null);
  const [reviewSwipe, setReviewSwipe] = useState<"" | "left" | "right">("");
  const [error, setError] = useState<string | null>(null);
  const [detailReportId, setDetailReportId] = useState<string | null>(null);

  const bundlesRef = useRef<Map<string, RaRunEvent[]>>(new Map());
  const queueRef = useRef<string[]>([]);
  const activeAsinRef = useRef<string | null>(null);
  const lastSeqRef = useRef(0);
  const lastEventAtRef = useRef(0);
  const replayIndexRef = useRef(0);
  const busyRef = useRef(false);

  const buildCard = useCallback((asin: string, replay: boolean): DeckCard => {
    const events = bundlesRef.current.get(asin) ?? [];
    const selected = events.find((event) => event.stage === "selected");
    const detail = selected?.detail ?? {};
    let outcome: DeckCard["outcome"] = "pending";
    let outcomeReason: string | null = null;
    let passChannels: string[] = [];
    const lines: CardLine[] = [];
    for (const event of events) {
      const line = lineForEvent(event);
      if (line) {
        lines.push(line);
      }
      const terminal = isTerminalEvent(event);
      if (terminal) {
        outcome = terminal;
        outcomeReason =
          str(event.detail?.reason) ?? (terminal === "reject" ? event.verdict : null);
        if (Array.isArray(event.detail?.pass_channels)) {
          passChannels = event.detail.pass_channels as string[];
        }
      }
    }
    return {
      asin,
      title: str(detail.title_zh) ?? str(detail.title),
      imageUrl: str(detail.image_url),
      price: num(detail.price),
      lines,
      outcome,
      outcomeReason,
      passChannels,
      replay,
    };
  }, []);

  const finishCard = useCallback((finished: DeckCard) => {
    // 托盘 = 合格产品的收纳盘：只收真正入组(pass)的，淘汰的左滑出局即止。
    if (finished.outcome !== "pass") {
      return;
    }
    setDone((previous) => {
      const entry: DoneEntry = {
        asin: finished.asin,
        title: finished.title,
        imageUrl: finished.imageUrl,
        outcome: "pass",
        channels: finished.passChannels,
        reason: finished.outcomeReason,
      };
      const without = previous.filter((item) => item.asin !== finished.asin);
      return [entry, ...without].slice(0, MAX_DONE);
    });
  }, []);

  // 主循环：出卡、滑卡。
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (busyRef.current) {
        return;
      }
      const active = activeAsinRef.current;
      if (active) {
        const current = buildCard(active, mode === "replay");
        setCard(current);
        if (current.outcome !== "pending") {
          busyRef.current = true;
          window.setTimeout(() => {
            setSwipe(
              current.outcome === "pass"
                ? "right"
                : current.outcome === "review"
                  ? "down"
                  : "left",
            );
            window.setTimeout(() => {
              finishCard(current);
              activeAsinRef.current = null;
              setCard(null);
              setSwipe("");
              busyRef.current = false;
            }, 650);
          }, CARD_LINGER_MS);
        }
        return;
      }
      // 出下一张卡：优先直播队列，队列空且久无事件时进入回放。
      const nextLive = queueRef.current.shift();
      if (nextLive) {
        activeAsinRef.current = nextLive;
        setMode("live");
        setCard(buildCard(nextLive, false));
        return;
      }
      // 事件流取不到时绝不放回放误导用户——显示"重连中"。
      if (!pollHealthyRef.current) {
        setMode("reconnecting");
        return;
      }
      const idleMs = Date.now() - lastEventAtRef.current;
      const finishedAsins = [...bundlesRef.current.keys()].filter((asin) => {
        const events = bundlesRef.current.get(asin) ?? [];
        return events.some((event) => isTerminalEvent(event) !== null);
      });
      if (idleMs > 30_000 && finishedAsins.length > 0) {
        setMode("replay");
        const asin =
          finishedAsins[replayIndexRef.current % finishedAsins.length];
        replayIndexRef.current += 1;
        activeAsinRef.current = asin;
        const replayCard = buildCard(asin, true);
        setCard(replayCard);
        busyRef.current = true;
        window.setTimeout(() => {
          setSwipe(
            replayCard.outcome === "pass"
              ? "right"
              : replayCard.outcome === "review"
                ? "down"
                : "left",
          );
          window.setTimeout(() => {
            activeAsinRef.current = null;
            setCard(null);
            setSwipe("");
            busyRef.current = false;
          }, 650);
        }, REPLAY_CARD_MS);
      } else if (finishedAsins.length === 0) {
        setMode((previous) => (previous === "live" ? previous : "idle"));
      }
    }, 900);
    return () => window.clearInterval(timer);
  }, [buildCard, finishCard, mode]);

  // 事件轮询。
  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const payload = await getRaRunEvents("latest", lastSeqRef.current, 300);
        if (cancelled) {
          return;
        }
        pollHealthyRef.current = true;
        setError(null);
        if (payload.items.length > 0) {
          lastEventAtRef.current = Date.now();
        }
        for (const event of payload.items) {
          lastSeqRef.current = Math.max(lastSeqRef.current, event.seq);
          const asin = event.asin ?? "";
          if (!asin) {
            continue;
          }
          const bundle = bundlesRef.current.get(asin) ?? [];
          bundle.push(event);
          bundlesRef.current.set(asin, bundle);
          if (event.stage === "selected") {
            if (
              activeAsinRef.current !== asin &&
              !queueRef.current.includes(asin)
            ) {
              queueRef.current.push(asin);
            }
          }
          const terminal = isTerminalEvent(event);
          if (terminal && activeAsinRef.current !== asin) {
            // 已经完结但没被展示过的卡也进入队列，保证不漏。
            if (!queueRef.current.includes(asin)) {
              queueRef.current.push(asin);
            }
          }
        }
      } catch (requestError) {
        if (!cancelled) {
          pollHealthyRef.current = false;
          setError(
            requestError instanceof Error
              ? requestError.message
              : "事件流读取失败。",
          );
        }
      }
    };
    void poll();
    const timer = window.setInterval(() => {
      void poll();
    }, EVENT_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  // 待滑堆 + 额度 + 已入组，低频刷新。
  const refreshSide = useCallback(async () => {
    try {
      const [groupsPayload, quotaPayload] = await Promise.all([
        getRaGroups(),
        getRaQuota().catch(() => null),
      ]);
      setReviewPile(groupsPayload.groups?.review ?? []);
      if (quotaPayload) {
        setQuota(quotaPayload);
      }
      const passItems = [
        ...(groupsPayload.groups?.amazon ?? []),
        ...(groupsPayload.groups?.dtc_ad ?? []),
        ...(groupsPayload.groups?.dtc_seo ?? []),
      ];
      setDone((previous) => {
        if (previous.length > 0) {
          return previous;
        }
        const byAsin = new Map<string, DoneEntry>();
        for (const item of passItems) {
          const asin = item.asin ?? "";
          if (!asin || byAsin.has(asin)) {
            continue;
          }
          byAsin.set(asin, {
            asin,
            title: item.title,
            imageUrl: item.image_url,
            outcome: "pass",
            channels: item.pass_channels,
            reason: null,
          });
        }
        return [...byAsin.values()].slice(0, MAX_DONE);
      });
    } catch {
      // 侧栏失败不打断直播。
    }
  }, []);

  useEffect(() => {
    void refreshSide();
    const timer = window.setInterval(() => {
      void refreshSide();
    }, 60_000);
    return () => window.clearInterval(timer);
  }, [refreshSide]);

  const [runStatus, setRunStatus] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const status = await getRaJobStatus("latest");
        if (!cancelled) {
          setRunStatus(status.status);
        }
      } catch {
        if (!cancelled) {
          setRunStatus(null);
        }
      }
    };
    void poll();
    const timer = window.setInterval(() => {
      void poll();
    }, 15_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const handleManualSwipe = useCallback(
    async (item: RaGroupItem, action: "approve" | "reject") => {
      if (!item.report_id || reviewBusy) {
        return;
      }
      setReviewBusy(item.report_id);
      setReviewSwipe(action === "approve" ? "right" : "left");
      try {
        if (action === "approve") {
          await approveRaReport(item.report_id);
        } else {
          await rejectRaReport(item.report_id);
        }
        window.setTimeout(() => {
          setReviewPile((previous) =>
            previous.filter((entry) => entry.report_id !== item.report_id),
          );
          setReviewSwipe("");
          setReviewBusy(null);
          if (action === "approve") {
            setDone((previous) =>
              [
                {
                  asin: item.asin ?? "",
                  title: item.title,
                  imageUrl: item.image_url,
                  outcome: "pass" as const,
                  channels:
                    item.pass_channels.length > 0
                      ? item.pass_channels
                      : item.primary_channel
                        ? [item.primary_channel]
                        : [],
                  reason: "人工右滑入组",
                },
                ...previous,
              ].slice(0, MAX_DONE),
            );
          }
        }, 600);
      } catch (requestError) {
        setReviewSwipe("");
        setReviewBusy(null);
        setError(
          requestError instanceof Error ? requestError.message : "操作失败。",
        );
      }
    },
    [reviewBusy],
  );

  const reviewHead = reviewPile[0] ?? null;
  const quotaEntries = useMemo(
    () => Object.values(quota?.providers ?? {}),
    [quota],
  );

  return (
    <div className={styles.deckLayout}>
      <div className={styles.mainColumn}>
        <div className={styles.statusStrip}>
          <span
            className={styles.modePill}
            data-mode={mode}
          >
            {mode === "live" ? (
              <>
                <Radio size={14} /> 直播 · 流水线运行中
              </>
            ) : mode === "replay" ? (
              <>
                <History size={14} /> 回放 · 最近判定重演
              </>
            ) : mode === "reconnecting" ? (
              <>
                <AlertTriangle size={14} /> 信号中断 · 重连中（后台照常运行）
              </>
            ) : (
              <>
                <Activity size={14} /> 待机 · 等待新产品进入
              </>
            )}
          </span>
          {runStatus ? (
            <span className={styles.runStatus}>任务状态：{runStatus}</span>
          ) : null}
          <div className={styles.quotaChips}>
            {quotaEntries.map((entry) => (
              <span key={entry.label} className={styles.quotaChip}>
                {entry.label} {entry.used}
                {entry.unlimited ? "" : `/${entry.budget}`}
              </span>
            ))}
          </div>
        </div>
        {error ? <p className={styles.errorNote}>{error}</p> : null}

        <div className={styles.stage}>
          {card ? (
            <article
              key={card.asin + (card.replay ? "-replay" : "")}
              className={styles.card}
              data-swipe={swipe}
              data-replay={card.replay ? "true" : "false"}
            >
              {card.replay ? <span className={styles.replayBadge}>回放</span> : null}
              <div className={styles.cardHead}>
                {card.imageUrl ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={card.imageUrl} alt="" className={styles.cardImage} />
                ) : (
                  <div className={styles.cardImageFallback}>
                    <Boxes size={28} />
                  </div>
                )}
                <div>
                  <h3 className={styles.cardTitle}>
                    {card.title ?? card.asin}
                  </h3>
                  <p className={styles.cardMeta}>
                    {card.asin}
                    {card.price !== null ? ` · $${card.price.toFixed(2)}` : ""}
                  </p>
                </div>
              </div>
              <div className={styles.terminal}>
                {card.lines.map((line, index) => (
                  <p
                    key={line.key}
                    className={styles.terminalLine}
                    data-tone={line.tone}
                    style={{ animationDelay: `${Math.min(index * 140, 1400)}ms` }}
                  >
                    {line.text}
                  </p>
                ))}
                {card.outcome === "pending" ? (
                  <p className={styles.terminalCursor}>▊</p>
                ) : null}
              </div>
            </article>
          ) : (
            <div className={styles.emptyStage}>
              <Boxes size={34} />
              <p>
                {mode === "idle"
                  ? "流水线待机中——自动巡库会在有预算和新品时继续产卡。"
                  : "下一张产品卡准备中…"}
              </p>
            </div>
          )}
        </div>

        <section className={styles.reviewSection}>
          <header className={styles.sectionHead}>
            <h3>待滑堆 · GPT 拿不准的，你说了算</h3>
            <span>{reviewPile.length} 个待定</span>
          </header>
          {reviewHead ? (
            <div className={styles.reviewRow}>
              <button
                type="button"
                className={styles.swipeButton}
                data-direction="left"
                disabled={reviewBusy !== null}
                onClick={() => void handleManualSwipe(reviewHead, "reject")}
              >
                <ArrowLeft size={18} />
                淘汰
              </button>
              <article
                className={styles.reviewCard}
                data-swipe={reviewSwipe}
              >
                {reviewHead.image_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={reviewHead.image_url}
                    alt=""
                    className={styles.reviewImage}
                  />
                ) : (
                  <div className={styles.cardImageFallback}>
                    <Boxes size={22} />
                  </div>
                )}
                <div className={styles.reviewBody}>
                  <h4>{reviewHead.title ?? reviewHead.asin}</h4>
                  <p className={styles.reviewReason}>
                    {reviewHead.decision_reason ?? reviewHead.summary ?? ""}
                  </p>
                  <button
                    type="button"
                    className={styles.detailLink}
                    onClick={() => setDetailReportId(reviewHead.report_id)}
                  >
                    查看完整数据 / Opus 建议 →
                  </button>
                  <p className={styles.reviewMeta}>
                    {reviewHead.final_score !== null
                      ? `终审 ${reviewHead.final_score} 分 · `
                      : ""}
                    {reviewHead.gross_margin !== null
                      ? `毛利 ${(reviewHead.gross_margin * 100).toFixed(1)}% · `
                      : ""}
                    建议渠道 {channelLabel(reviewHead.primary_channel ?? "—")}
                  </p>
                </div>
              </article>
              <button
                type="button"
                className={styles.swipeButton}
                data-direction="right"
                disabled={reviewBusy !== null}
                onClick={() => void handleManualSwipe(reviewHead, "approve")}
              >
                入组
                <ArrowRight size={18} />
              </button>
            </div>
          ) : (
            <p className={styles.reviewEmpty}>待滑堆是空的——机器现在没什么拿不准的。</p>
          )}
        </section>
      </div>

      <aside className={styles.tray}>
        <header className={styles.sectionHead}>
          <h3>已入组托盘</h3>
          <span>{done.length} 个</span>
        </header>
        <div className={styles.trayList}>
          {done.length === 0 ? (
            <p className={styles.reviewEmpty}>
              还没有产品入组——终审通过的产品会自动落到这里。
            </p>
          ) : (
            done.map((entry) => (
              <div
                key={entry.asin + entry.outcome}
                className={styles.trayItem}
                data-outcome={entry.outcome}
              >
                {entry.imageUrl ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={entry.imageUrl} alt="" className={styles.trayImage} />
                ) : (
                  <div className={styles.trayImageFallback} />
                )}
                <div className={styles.trayBody}>
                  <p className={styles.trayTitle}>{entry.title ?? entry.asin}</p>
                  <p className={styles.trayMeta}>
                    {entry.outcome === "pass"
                      ? entry.channels.map(channelLabel).join(" + ") || "已入组"
                      : entry.outcome === "review"
                        ? "待滑堆"
                        : entry.reason ?? "淘汰"}
                  </p>
                </div>
              </div>
            ))
          )}
        </div>
      </aside>
      {detailReportId ? (
        <DetailModal
          reportId={detailReportId}
          onClose={() => setDetailReportId(null)}
        />
      ) : null}
    </div>
  );
}
