"use client";

import {
  ArrowRightCircle,
  Boxes,
  CheckCircle2,
  Eye,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  approveRaReport,
  getRaGroups,
  importRaProductsToK,
  rejectRaReport,
} from "@/modules/r/analysis/api";
import type { RaGroupItem, RaGroupsPayload } from "@/modules/r/analysis/types";

import { DetailModal } from "@/modules/r/analysis/DetailModal";

import styles from "./GroupsBoard.module.css";

type GroupKey = "amazon" | "dtc_ad" | "dtc_seo" | "review";

const GROUP_TABS: Array<{ key: GroupKey; label: string; hint: string }> = [
  { key: "amazon", label: "亚马逊可售", hint: "有现成搜索需求，利润扛得住 FBA" },
  { key: "dtc_ad", label: "独立站广告", hint: "3 秒钩子 + 高毛利养广告" },
  { key: "dtc_seo", label: "独立站 SEO", hint: "有人搜、Google 页一弱" },
  { key: "review", label: "待滑堆", hint: "GPT 拿不准，等你亲手滑" },
];

function channelToKChannel(group: GroupKey): "amazon" | "dtc" {
  return group === "amazon" ? "amazon" : "dtc";
}

export function GroupsBoard() {
  const [payload, setPayload] = useState<RaGroupsPayload | null>(null);
  const [active, setActive] = useState<GroupKey>("amazon");
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [detailReportId, setDetailReportId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const groups = await getRaGroups();
      setPayload(groups);
      setError(null);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "分组读取失败。",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const items = useMemo(
    () => payload?.groups?.[active] ?? [],
    [payload, active],
  );

  const handleImportToK = useCallback(
    async (item: RaGroupItem) => {
      if (!item.asin || busyId) {
        return;
      }
      setBusyId(item.report_id);
      setNotice(null);
      try {
        const result = await importRaProductsToK(
          [item.asin],
          channelToKChannel(active),
        );
        if (result.created.length > 0) {
          setNotice(
            `${item.asin} 已搬进 K 系列（${
              (result.created[0] as { keywords_from_ra?: boolean })
                .keywords_from_ra
                ? "关键词已自动填入"
                : "使用默认关键词"
            }）。`,
          );
        } else if (result.skipped.includes(item.asin)) {
          setNotice(`${item.asin} 之前已经搬进过 K 系列，跳过。`);
        } else if (result.errors.length > 0) {
          setError(`${item.asin} 搬运失败：${result.errors[0]?.reason ?? ""}`);
        }
      } catch (requestError) {
        setError(
          requestError instanceof Error
            ? requestError.message
            : "搬进 K 失败。",
        );
      } finally {
        setBusyId(null);
      }
    },
    [active, busyId],
  );

  const handleDecision = useCallback(
    async (item: RaGroupItem, action: "approve" | "reject") => {
      if (busyId) {
        return;
      }
      setBusyId(item.report_id);
      try {
        if (action === "approve") {
          await approveRaReport(item.report_id);
        } else {
          await rejectRaReport(item.report_id);
        }
        await refresh();
      } catch (requestError) {
        setError(
          requestError instanceof Error ? requestError.message : "操作失败。",
        );
      } finally {
        setBusyId(null);
      }
    },
    [busyId, refresh],
  );

  return (
    <div className={styles.board}>
      <div className={styles.tabRow}>
        {GROUP_TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            className={styles.tab}
            data-active={active === tab.key ? "true" : "false"}
            onClick={() => setActive(tab.key)}
          >
            <span className={styles.tabLabel}>{tab.label}</span>
            <span className={styles.tabCount}>
              {payload?.counts?.[tab.key] ?? 0}
            </span>
          </button>
        ))}
        <button
          type="button"
          className={styles.refreshButton}
          onClick={() => void refresh()}
          disabled={loading}
        >
          <RefreshCw size={15} data-spin={loading ? "true" : "false"} />
          刷新
        </button>
      </div>
      <p className={styles.tabHint}>
        {GROUP_TABS.find((tab) => tab.key === active)?.hint}
      </p>

      {notice ? <p className={styles.notice}>{notice}</p> : null}
      {error ? <p className={styles.errorNote}>{error}</p> : null}

      {loading && !payload ? (
        <p className={styles.empty}>读取分组中…</p>
      ) : items.length === 0 ? (
        <p className={styles.empty}>
          这个分组还没有产品——自动巡库跑起来后会持续入组。
        </p>
      ) : (
        <div className={styles.grid}>
          {items.map((item) => (
            <article key={item.report_id} className={styles.itemCard}>
              <div className={styles.itemHead}>
                {item.image_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={item.image_url} alt="" className={styles.itemImage} />
                ) : (
                  <div className={styles.itemImageFallback}>
                    <Boxes size={22} />
                  </div>
                )}
                <div className={styles.itemHeadText}>
                  <h4>{item.title ?? item.asin}</h4>
                  <p>
                    {item.asin}
                    {item.final_score !== null
                      ? ` · 终审 ${item.final_score} 分`
                      : ""}
                    {item.gross_margin !== null
                      ? ` · 毛利 ${(item.gross_margin * 100).toFixed(1)}%`
                      : ""}
                    {item.monthly_sales !== null
                      ? ` · 月销 ~${item.monthly_sales}`
                      : ""}
                  </p>
                </div>
                {item.fulfillment_only ? (
                  <span className={styles.statusBadge} data-kind="fulfillment">
                    ⚡ 仅自发货 · 勿备货
                  </span>
                ) : null}
                {item.status === "approved" ? (
                  <span className={styles.statusBadge} data-kind="approved">
                    <CheckCircle2 size={13} /> 已批准
                  </span>
                ) : null}
              </div>
              {item.primary_keyword ? (
                <div className={styles.keywordRow}>
                  <span className={styles.keywordChip} data-primary="true">
                    {item.primary_keyword}
                  </span>
                  {(item.keywords?.secondary ?? []).slice(0, 4).map((keyword) => (
                    <span key={keyword} className={styles.keywordChip}>
                      {keyword}
                    </span>
                  ))}
                </div>
              ) : null}
              {item.decision_reason ? (
                <p className={styles.itemReason}>{item.decision_reason}</p>
              ) : null}
              {item.ai_route_note ? (
                <p className={styles.aiRouteNote}>
                  🧠 终审 AI 渠道意见：{item.ai_route_note}
                </p>
              ) : null}
              {item.opus_review?.reason ? (
                <p className={styles.opusNote}>
                  Opus 复核（{item.opus_review.score ?? "—"} 分）：
                  {item.opus_review.reason}
                </p>
              ) : null}
              <div className={styles.itemActions}>
                <button
                  type="button"
                  className={styles.actionButton}
                  onClick={() => setDetailReportId(item.report_id)}
                >
                  <Eye size={15} /> 详情
                </button>
                {active === "review" ? (
                  <>
                    <button
                      type="button"
                      className={styles.actionButton}
                      data-kind="reject"
                      disabled={busyId !== null}
                      onClick={() => void handleDecision(item, "reject")}
                    >
                      <Trash2 size={15} /> 淘汰
                    </button>
                    <button
                      type="button"
                      className={styles.actionButton}
                      data-kind="approve"
                      disabled={busyId !== null}
                      onClick={() => void handleDecision(item, "approve")}
                    >
                      <CheckCircle2 size={15} /> 入组
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      className={styles.actionButton}
                      data-kind="reject"
                      disabled={busyId !== null}
                      onClick={() => void handleDecision(item, "reject")}
                    >
                      <Trash2 size={15} /> 移出
                    </button>
                    <button
                      type="button"
                      className={styles.actionButton}
                      data-kind="primary"
                      disabled={busyId !== null}
                      onClick={() => void handleImportToK(item)}
                    >
                      <ArrowRightCircle size={15} />
                      {busyId === item.report_id ? "搬运中…" : "搬进 K 系列"}
                    </button>
                  </>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
      {detailReportId ? (
        <DetailModal
          reportId={detailReportId}
          onClose={() => setDetailReportId(null)}
        />
      ) : null}
    </div>
  );
}
