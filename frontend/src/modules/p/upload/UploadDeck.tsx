"use client";

import {
  AlertTriangle,
  ExternalLink,
  LoaderCircle,
  RefreshCw,
  Rocket,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  getUploadJobs,
  type UploadJob,
  type UploadJobsResult,
} from "./api";
import styles from "./UploadDeck.module.css";

const POLL_MS = 30000;

function statusLabel(status: string) {
  switch (status) {
    case "success":
      return "上架成功";
    case "failed":
      return "失败";
    case "dispatched":
      return "n8n 执行中";
    case "pending":
      return "待派单";
    default:
      return status;
  }
}

function formatTime(value: string | null) {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  return `${date.getMonth() + 1}/${date.getDate()} ${String(
    date.getHours(),
  ).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

export function UploadDeck() {
  const [result, setResult] = useState<UploadJobsResult | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const mounted = useRef(true);
  const timer = useRef<number | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) {
      setIsLoading(true);
    }
    try {
      const data = await getUploadJobs(80);
      if (mounted.current) {
        setResult(data);
        setError(null);
      }
    } catch (loadError) {
      if (mounted.current) {
        setError(
          loadError instanceof Error ? loadError.message : "台账加载失败。",
        );
      }
    } finally {
      if (mounted.current) {
        setIsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void load();
    timer.current = window.setInterval(() => void load(true), POLL_MS);
    return () => {
      mounted.current = false;
      if (timer.current !== null) {
        window.clearInterval(timer.current);
      }
    };
  }, [load]);

  const summary = result?.summary;
  const jobs = result?.jobs ?? [];

  return (
    <div className={styles.deck}>
      <div className={styles.statRow}>
        <div className={styles.statCard}>
          <span className={styles.statLabel}>总上架任务</span>
          <span className={styles.statValue}>{summary?.total ?? "—"}</span>
        </div>
        <div className={styles.statCard} data-tone="success">
          <span className={styles.statLabel}>成功</span>
          <span className={styles.statValue}>{summary?.success ?? "—"}</span>
        </div>
        <div className={styles.statCard} data-tone="flight">
          <span className={styles.statLabel}>执行中</span>
          <span className={styles.statValue}>{summary?.in_flight ?? "—"}</span>
        </div>
        <div className={styles.statCard} data-tone="failed">
          <span className={styles.statLabel}>失败</span>
          <span className={styles.statValue}>{summary?.failed ?? "—"}</span>
        </div>
      </div>

      <section className={styles.ledger} aria-label="上架台账">
        <div className={styles.ledgerHead}>
          <span className={styles.ledgerTitle}>
            <span className={styles.pulse} aria-hidden="true" />
            上架台账 · 控制台派单 → n8n 执行 → WooCommerce
          </span>
          <button
            className="secondary-button"
            disabled={isLoading}
            onClick={() => void load()}
            type="button"
          >
            {isLoading ? (
              <LoaderCircle aria-hidden="true" className="spin" size={15} />
            ) : (
              <RefreshCw aria-hidden="true" size={15} />
            )}
            刷新
          </button>
        </div>

        {error ? (
          <div className={styles.state} role="alert">
            <AlertTriangle aria-hidden="true" size={18} />
            <span>{error}</span>
          </div>
        ) : null}

        {!error && isLoading && jobs.length === 0 ? (
          <div className={styles.state}>
            <LoaderCircle aria-hidden="true" className="spin" size={18} />
            <span>正在读取台账…</span>
          </div>
        ) : null}

        {!error && !isLoading && jobs.length === 0 ? (
          <div className={styles.emptyHint}>
            <Rocket aria-hidden="true" size={22} />
            <p>
              还没有上架记录。去<strong>产品知识库</strong>
              名册，挑一个过了门禁（文案 / 成品图 / 类目 / 价格 / 品牌审查）
              的产品，点行内「上架」按钮 —— 任务会实时出现在这里。
            </p>
          </div>
        ) : null}

        {jobs.length > 0 ? (
          <div className={styles.tableScroll}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>时间</th>
                  <th>产品</th>
                  <th>渠道</th>
                  <th>状态</th>
                  <th>Woo ID</th>
                  <th>店铺页</th>
                  <th>错误</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job: UploadJob) => (
                  <tr key={job.job_id}>
                    <td className={styles.timeCell}>
                      {formatTime(job.created_at)}
                    </td>
                    <td className={styles.productCell}>
                      <strong>{job.product_name || "（产品已删除）"}</strong>
                      <span>{job.sku || job.product_id.slice(0, 8)}</span>
                    </td>
                    <td>{job.channel}</td>
                    <td>
                      <span
                        className={styles.statusBadge}
                        data-status={job.status}
                      >
                        {statusLabel(job.status)}
                      </span>
                    </td>
                    <td>{job.external_product_id || "—"}</td>
                    <td>
                      {job.external_url ? (
                        <a
                          className={styles.wooLink}
                          href={job.external_url}
                          rel="noreferrer"
                          target="_blank"
                        >
                          打开 <ExternalLink aria-hidden="true" size={11} />
                        </a>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>
                      {job.error ? (
                        <span className={styles.errorCell} title={job.error}>
                          {job.error}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    </div>
  );
}
