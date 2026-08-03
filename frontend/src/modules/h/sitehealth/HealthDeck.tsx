"use client";

import { AlertTriangle, LoaderCircle } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  getHealthFindings,
  getHealthRuns,
  triggerHealthRun,
  updateHealthFinding,
  type HealthFinding,
  type HealthFindingAction,
  type HealthFindingType,
  type HealthRun,
  type HealthRunStatus,
  type HealthRunTrigger,
} from "./api";
import styles from "./HealthDeck.module.css";
import { isInternalUrl, toRedirectPath } from "./redirect-hint";
import type { RedirectHandoff } from "./SiteHealthWorkspace";

const RUN_POLL_MS = 5000;

type ActiveTab = "open" | "acknowledged" | "runs";

/**
 * 这条死链能不能用「设跳转」修。
 *
 * 跳转表由站上的 barong-redirects 插件执行，**只在本站 404 时生效**，所以：
 * - 站外死链给不了跳转（要么改内容要么删链接）
 * - 慢页/首页异常/sitemap 异常也不是跳转能解决的
 *
 * 注意这里**不排除任何状态码**：一条死链无论是 404 还是连不上，
 * 只要是本站地址，设个跳转都是合理的处置。
 */
function canRedirect(finding: HealthFinding): boolean {
  return (
    finding.finding_type === "broken_link" &&
    isInternalUrl(finding.url) &&
    toRedirectPath(finding.url) !== null
  );
}

function findingTypeLabel(findingType: HealthFindingType) {
  switch (findingType) {
    case "broken_link":
      return "死链";
    case "slow_page":
      return "慢页";
    case "sitemap_error":
      return "站点地图异常";
    case "homepage_error":
      return "首页异常";
  }
}

function triggerLabel(trigger: HealthRunTrigger) {
  return trigger === "scheduled" ? "定时" : "手动";
}

function runStatusLabel(status: HealthRunStatus) {
  switch (status) {
    case "running":
      return "巡检中";
    case "completed":
      return "完成";
    case "failed":
      return "失败";
  }
}

function runStatusTone(status: HealthRunStatus) {
  return status === "completed" ? "success" : status;
}

function statTone(status: HealthRunStatus | undefined) {
  if (status === "completed") return "success";
  if (status === "running") return "flight";
  if (status === "failed") return "failed";
  return undefined;
}

function formatTime(value: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "—";
}

export function HealthDeck({
  onCreateRedirect,
}: {
  /** 点「设跳转」时把这条死链交给「跳转管理」面板 */
  onCreateRedirect?: (handoff: RedirectHandoff) => void;
} = {}) {
  const [activeTab, setActiveTab] = useState<ActiveTab>("open");
  const [runs, setRuns] = useState<HealthRun[]>([]);
  const [openFindings, setOpenFindings] = useState<HealthFinding[]>([]);
  const [openBrokenLinks, setOpenBrokenLinks] = useState(0);
  const [acknowledgedFindings, setAcknowledgedFindings] = useState<
    HealthFinding[]
  >([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pollingRunId, setPollingRunId] = useState<string | null>(null);
  const mounted = useRef(true);

  const refreshData = useCallback(async () => {
    try {
      const [runData, openData, acknowledgedData, openBrokenLinkData] =
        await Promise.all([
          getHealthRuns(30),
          getHealthFindings({ status: "open", limit: 500 }),
          getHealthFindings({ status: "acknowledged", limit: 500 }),
          getHealthFindings({
            status: "open",
            findingType: "broken_link",
            limit: 1,
          }),
        ]);
      if (mounted.current) {
        setRuns(runData.runs);
        setOpenFindings(openData.items);
        setOpenBrokenLinks(openBrokenLinkData.total);
        setAcknowledgedFindings(acknowledgedData.items);
        setError(null);
      }
      return runData.runs;
    } catch (refreshError) {
      if (mounted.current) setError(errorMessage(refreshError));
      return null;
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void refreshData();
    return () => {
      mounted.current = false;
    };
  }, [refreshData]);

  useEffect(() => {
    if (!pollingRunId) return;
    const poll = async () => {
      const nextRuns = await refreshData();
      const currentRun = nextRuns?.find((run) => run.id === pollingRunId);
      if (currentRun && currentRun.status !== "running" && mounted.current) {
        setPollingRunId(null);
      }
    };
    const timer = window.setInterval(() => void poll(), RUN_POLL_MS);
    return () => window.clearInterval(timer);
  }, [pollingRunId, refreshData]);

  const handleTrigger = useCallback(async () => {
    setBusy("trigger");
    setError(null);
    setNotice(null);
    try {
      const run = await triggerHealthRun();
      if (!mounted.current) return;
      setRuns((current) => [
        run,
        ...current.filter((item) => item.id !== run.id),
      ]);
      setNotice("巡检已发起，n8n 执行中——完成后台账自动更新");
      if (run.status === "running") setPollingRunId(run.id);
      await refreshData();
    } catch (triggerError) {
      if (mounted.current) setError(errorMessage(triggerError));
    } finally {
      if (mounted.current) setBusy(null);
    }
  }, [refreshData]);

  const handleFindingAction = useCallback(
    async (finding: HealthFinding, action: HealthFindingAction) => {
      setBusy(finding.id);
      setError(null);
      try {
        await updateHealthFinding(finding.id, action);
        await refreshData();
      } catch (actionError) {
        if (mounted.current) setError(errorMessage(actionError));
      } finally {
        if (mounted.current) setBusy(null);
      }
    },
    [refreshData],
  );

  const latestRun = runs[0];
  const activeFindings =
    activeTab === "open" ? openFindings : acknowledgedFindings;

  return (
    <div className={styles.deck}>
      <div className={styles.statRow}>
        <div
          className={styles.statCard}
          data-tone={statTone(latestRun?.status)}
        >
          <span className={styles.statLabel}>最近巡检</span>
          <span className={styles.statValue}>
            {loading || !latestRun ? "—" : runStatusLabel(latestRun.status)}
          </span>
        </div>
        <div className={styles.statCard} data-tone="failed">
          <span className={styles.statLabel}>死链</span>
          <span className={styles.statValue}>
            {loading ? "—" : openBrokenLinks}
          </span>
        </div>
        <div className={styles.statCard} data-tone="flight">
          <span className={styles.statLabel}>慢页</span>
          <span className={styles.statValue}>
            {loading || !latestRun ? "—" : latestRun.urls_slow}
          </span>
        </div>
        <div className={styles.statCard} data-tone="success">
          <span className={styles.statLabel}>巡检 URL 数</span>
          <span className={styles.statValue}>
            {loading || !latestRun ? "—" : latestRun.urls_total}
          </span>
        </div>
      </div>

      <div className={styles.headActions}>
        <button
          className="primary-button"
          disabled={busy !== null}
          onClick={() => void handleTrigger()}
          type="button"
        >
          {busy === "trigger" ? (
            <LoaderCircle aria-hidden="true" className="spin" size={16} />
          ) : null}
          立即巡检
        </button>
      </div>

      {error ? (
        <div className={styles.state} role="alert">
          <AlertTriangle aria-hidden="true" size={16} />
          <span>{error}</span>
        </div>
      ) : null}
      {notice ? <p className={styles.notice}>{notice}</p> : null}

      <div className={styles.tabs} role="tablist">
        <button
          className={`${styles.tab} ${activeTab === "open" ? styles.tabOn : ""}`}
          onClick={() => setActiveTab("open")}
          role="tab"
          type="button"
        >
          待处理 <span className={styles.tabCount}>{openFindings.length}</span>
        </button>
        <button
          className={`${styles.tab} ${activeTab === "acknowledged" ? styles.tabOn : ""}`}
          onClick={() => setActiveTab("acknowledged")}
          role="tab"
          type="button"
        >
          已忽略{" "}
          <span className={styles.tabCount}>{acknowledgedFindings.length}</span>
        </button>
        <button
          className={`${styles.tab} ${activeTab === "runs" ? styles.tabOn : ""}`}
          onClick={() => setActiveTab("runs")}
          role="tab"
          type="button"
        >
          运行台账 <span className={styles.tabCount}>{runs.length}</span>
        </button>
      </div>

      {activeTab === "open" || activeTab === "acknowledged" ? (
        <section
          className={styles.panel}
          aria-label={activeTab === "open" ? "待处理" : "已忽略"}
        >
          {loading ? (
            <div className={styles.state}>
              <LoaderCircle aria-hidden="true" className="spin" size={16} />
            </div>
          ) : activeFindings.length === 0 ? (
            <div className={styles.emptyHint}>
              {activeTab === "open" ? "没有待处理的异常——站点健康" : "—"}
            </div>
          ) : (
            <div className={styles.tableScroll}>
              <table
                className={styles.table}
                aria-label={activeTab === "open" ? "待处理" : "已忽略"}
              >
                <tbody>
                  {activeFindings.map((finding) => (
                    <tr key={finding.id}>
                      <td>
                        <span
                          className={styles.statusBadge}
                          data-status={
                            finding.finding_type === "slow_page"
                              ? "running"
                              : "failed"
                          }
                        >
                          {findingTypeLabel(finding.finding_type)}
                        </span>
                      </td>
                      <td className={styles.productCell}>
                        <a
                          className={styles.linkButton}
                          href={finding.url}
                          rel="noreferrer"
                          target="_blank"
                          title={finding.detail ?? undefined}
                        >
                          {finding.url}
                        </a>
                      </td>
                      <td>{finding.status_code ?? "—"}</td>
                      <td>
                        {finding.response_ms === null
                          ? "—"
                          : `${finding.response_ms}ms`}
                      </td>
                      <td>
                        <div className={styles.actionRow}>
                          {onCreateRedirect && canRedirect(finding) ? (
                            <button
                              className="secondary-button"
                              disabled={busy !== null}
                              onClick={() => {
                                const path = toRedirectPath(finding.url);
                                if (!path) return;
                                onCreateRedirect({
                                  path,
                                  findingId: finding.id,
                                  url: finding.url,
                                });
                              }}
                              title="到「跳转管理」为这个地址建一条 301，访客和谷歌就不会再撞 404"
                              type="button"
                            >
                              设跳转
                            </button>
                          ) : null}
                          {activeTab === "open" ? (
                            <button
                              className="secondary-button"
                              disabled={busy !== null}
                              onClick={() =>
                                void handleFindingAction(finding, "acknowledge")
                              }
                              title="知道了，但不打算修——挪到「已忽略」，不再占着待办"
                              type="button"
                            >
                              忽略
                            </button>
                          ) : null}
                          {activeTab === "acknowledged" ? (
                            <button
                              className="secondary-button"
                              disabled={busy !== null}
                              onClick={() =>
                                void handleFindingAction(finding, "reopen")
                              }
                              title="挪回「待处理」，重新当成要办的事"
                              type="button"
                            >
                              放回待办
                            </button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ) : (
        <section className={styles.panel} aria-label="运行台账">
          {loading ? (
            <div className={styles.state}>
              <LoaderCircle aria-hidden="true" className="spin" size={16} />
            </div>
          ) : runs.length === 0 ? (
            <div className={styles.emptyHint}>
              还没有巡检记录。点「立即巡检」跑第一轮，或等每日定时任务。
            </div>
          ) : (
            <div className={styles.tableScroll}>
              <table className={styles.table} aria-label="运行台账">
                <tbody>
                  {runs.map((run) => (
                    <tr key={run.id}>
                      <td className={styles.timeCell}>
                        {formatTime(run.started_at ?? run.created_at)}
                      </td>
                      <td>
                        <span
                          className={styles.statusBadge}
                          data-status={
                            run.trigger === "manual" ? "running" : "queued"
                          }
                        >
                          {triggerLabel(run.trigger)}
                        </span>
                      </td>
                      <td>
                        <span
                          className={styles.statusBadge}
                          data-status={runStatusTone(run.status)}
                        >
                          {runStatusLabel(run.status)}
                        </span>
                      </td>
                      <td title={run.error ?? undefined}>
                        {run.urls_ok}/{run.urls_total} 可用 · 死链{" "}
                        {run.urls_broken} · 慢页 {run.urls_slow} · P95{" "}
                        {run.p95_response_ms ?? "—"}ms
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
