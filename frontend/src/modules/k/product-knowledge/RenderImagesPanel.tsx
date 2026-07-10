"use client";

import { ImagePlay, LoaderCircle, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  getRenderJobs,
  mediaAssetThumbnailUrl,
  renderProductImages,
  retryRenderJobs,
  type RenderJob,
  type RenderJobsResult,
} from "./api";
import styles from "./ProductKnowledge.module.css";

type RenderImagesPanelProps = {
  productId: string;
  hasBrief: boolean;
};

const POLL_MS = 5000;

function isActive(result: RenderJobsResult | null) {
  if (!result) {
    return false;
  }
  return result.summary.pending > 0 || result.summary.running > 0;
}

function placementLabel(placement: string) {
  return placement === "description" ? "描述图" : "图库图";
}

function statusLabel(status: string) {
  switch (status) {
    case "pending":
      return "排队中";
    case "running":
      return "生成中…";
    case "completed":
      return "完成";
    case "failed":
      return "失败";
    default:
      return status;
  }
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

export function RenderImagesPanel({ productId, hasBrief }: RenderImagesPanelProps) {
  const [result, setResult] = useState<RenderJobsResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const mounted = useRef(true);
  const timer = useRef<number | null>(null);

  const clearTimer = useCallback(() => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
  }, []);

  const poll = useCallback(async () => {
    if (!mounted.current) {
      return;
    }
    try {
      const data = await getRenderJobs(productId);
      if (!mounted.current) {
        return;
      }
      setResult(data);
      if (isActive(data)) {
        clearTimer();
        timer.current = window.setTimeout(() => void poll(), POLL_MS);
      }
    } catch (pollError) {
      if (mounted.current) {
        setError(errorMessage(pollError, "查询作图进度失败。"));
      }
    }
  }, [productId, clearTimer]);

  useEffect(() => {
    mounted.current = true;
    void poll();
    return () => {
      mounted.current = false;
      clearTimer();
    };
  }, [poll, clearTimer]);

  const handleRenderAll = async () => {
    setBusy(true);
    setError(null);
    try {
      await renderProductImages(productId);
      await poll();
    } catch (renderError) {
      setError(errorMessage(renderError, "提交作图任务失败，请重试。"));
    } finally {
      if (mounted.current) {
        setBusy(false);
      }
    }
  };

  const handleRetry = async () => {
    if (!result?.batch_id) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await retryRenderJobs(productId, result.batch_id);
      await poll();
    } catch (retryError) {
      setError(errorMessage(retryError, "重试失败，请稍后再试。"));
    } finally {
      if (mounted.current) {
        setBusy(false);
      }
    }
  };

  const active = isActive(result);
  const summary = result?.summary;
  const hasJobs = (result?.jobs.length ?? 0) > 0;
  const finishedCount = (summary?.completed ?? 0) + (summary?.failed ?? 0);

  return (
    <section className={styles.sellingPointsSection} aria-labelledby="k-render">
      <div className={styles.sellingPointsHeading}>
        <div>
          <span className={styles.eyebrow}>成品图</span>
          <h4 id="k-render">一次性作图 · 按指令出全套成品图</h4>
        </div>
        <div className={styles.headingActions}>
          {summary && summary.failed > 0 && !active ? (
            <button
              className="secondary-button"
              disabled={busy}
              onClick={() => void handleRetry()}
              type="button"
            >
              <RotateCcw aria-hidden="true" size={16} />
              重试失败的 {summary.failed} 张
            </button>
          ) : null}
          <button
            className="secondary-button"
            disabled={busy || active || !hasBrief}
            onClick={() => void handleRenderAll()}
            title={hasBrief ? "按作图指令一次性生成全部成品图" : "请先生成作图指令"}
            type="button"
          >
            {busy || active ? (
              <LoaderCircle aria-hidden="true" className="spin" size={16} />
            ) : (
              <ImagePlay aria-hidden="true" size={16} />
            )}
            {active ? "作图中…" : hasJobs ? "重新一次性作图" : "一次性作图"}
          </button>
        </div>
      </div>

      {error ? <p className={styles.sellingPointsError}>{error}</p> : null}

      {active && summary ? (
        <p className={styles.copyReviewHint}>
          AI 正在按指令逐张作图（{finishedCount}/{summary.total} 张完成）——
          每张约 1–2 分钟，完成后自动存入产品图片库并标好位置和 SEO 信息。
        </p>
      ) : null}

      {!hasJobs && !active ? (
        <p className={styles.copyReviewHint}>
          有了作图指令后点「一次性作图」：AI 以产品原图为参考，把主图 / 副图 /
          描述图整套生成，每张自带放置位置（图库或描述内嵌）和
          title/alt/caption/description，上架时直接分流。
        </p>
      ) : null}

      {hasJobs ? (
        <ul className={styles.renderGrid}>
          {result?.jobs.map((job: RenderJob) => (
            <li
              className={`${styles.renderCard}${
                job.status === "failed" ? ` ${styles.renderCardFailed}` : ""
              }`}
              key={job.job_id}
            >
              <div className={styles.renderThumb}>
                {job.status === "completed" && job.asset_id ? (
                  <img
                    alt={`第 ${job.position} 张`}
                    decoding="async"
                    loading="lazy"
                    src={mediaAssetThumbnailUrl(job.asset_id)}
                  />
                ) : job.status === "running" || job.status === "pending" ? (
                  <LoaderCircle aria-hidden="true" className="spin" size={20} />
                ) : (
                  <span aria-hidden="true">✕</span>
                )}
              </div>
              <div className={styles.renderMeta}>
                <strong>
                  #{job.position} {job.role_label || placementLabel(job.placement)}
                </strong>
                <span>
                  {placementLabel(job.placement)}
                  {job.asset_role === "main" ? " · 主图" : ""} ·{" "}
                  {statusLabel(job.status)}
                </span>
                {job.status === "failed" && job.error ? (
                  <span className={styles.renderError} title={job.error}>
                    {job.error}
                  </span>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
