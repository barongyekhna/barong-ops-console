"use client";

import { ArrowUpRight, ClipboardList, LoaderCircle, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  generateProductCopy,
  generateProductImageBrief,
  getGenerationJobs,
  getProduct,
  type GenerationJob,
} from "./api";
import styles from "./ProductKnowledge.module.css";
import { BrandAuditPanel } from "./BrandAuditPanel";
import { FaqEditorPanel } from "./FaqEditorPanel";
import { RenderImagesPanel } from "./RenderImagesPanel";

type CopyArtDirectionProps = {
  productId: string;
  channel?: string | null;
};

type SectionStatus = "idle" | "generating" | "done" | "failed";

const POLL_MS = 4000;

function channelLabel(channel?: string | null) {
  return channel === "amazon" ? "亚马逊" : "独立站";
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

function latestJob(jobs: GenerationJob[], jobType: string): GenerationJob | undefined {
  // backend returns newest-first
  return jobs.find((job) => job.job_type === jobType);
}

export function CopyArtDirection({ productId, channel }: CopyArtDirectionProps) {
  const router = useRouter();

  const [copy, setCopy] = useState<unknown>(null);
  const [copyZh, setCopyZh] = useState<string | null>(null);
  const [copyChannel, setCopyChannel] = useState<string | null>(channel ?? null);
  const [copyStatus, setCopyStatus] = useState<SectionStatus>("idle");
  const [copyError, setCopyError] = useState<string | null>(null);

  const [brief, setBrief] = useState<unknown>(null);
  const [briefZh, setBriefZh] = useState<string | null>(null);
  const [briefStatus, setBriefStatus] = useState<SectionStatus>("idle");
  const [briefError, setBriefError] = useState<string | null>(null);

  const timers = useRef<number[]>([]);
  const mounted = useRef(true);

  const clearTimers = useCallback(() => {
    for (const id of timers.current) {
      window.clearTimeout(id);
    }
    timers.current = [];
  }, []);

  const loadResult = useCallback(async (jobType: "marketing_copy" | "image_brief") => {
    const product = await getProduct(productId);
    if (!mounted.current) {
      return;
    }
    if (jobType === "marketing_copy") {
      setCopy((product as { marketing_copy_json?: unknown }).marketing_copy_json ?? null);
      setCopyZh((product as { marketing_copy_zh?: string | null }).marketing_copy_zh ?? null);
      setCopyChannel((product as { channel?: string | null }).channel ?? channel ?? null);
      setCopyStatus("done");
    } else {
      setBrief((product as { image_instruction_json?: unknown }).image_instruction_json ?? null);
      setBriefZh((product as { image_instruction_zh?: string | null }).image_instruction_zh ?? null);
      setBriefStatus("done");
    }
  }, [productId, channel]);

  const poll = useCallback(
    async (jobType: "marketing_copy" | "image_brief") => {
      if (!mounted.current) {
        return;
      }
      try {
        const jobs = await getGenerationJobs(productId);
        const job = latestJob(jobs, jobType);
        if (!mounted.current) {
          return;
        }
        if (job && job.status === "completed") {
          await loadResult(jobType);
          return;
        }
        if (job && job.status === "failed") {
          if (jobType === "marketing_copy") {
            setCopyStatus("failed");
            setCopyError(job.error || "生成失败，请重试。");
          } else {
            setBriefStatus("failed");
            setBriefError(job.error || "生成失败（需先有文案）。");
          }
          return;
        }
        // pending / running / not-yet-visible -> keep polling
        const id = window.setTimeout(() => void poll(jobType), POLL_MS);
        timers.current.push(id);
      } catch (error) {
        if (!mounted.current) {
          return;
        }
        if (jobType === "marketing_copy") {
          setCopyStatus("failed");
          setCopyError(errorMessage(error, "查询生成状态失败。"));
        } else {
          setBriefStatus("failed");
          setBriefError(errorMessage(error, "查询生成状态失败。"));
        }
      }
    },
    [productId, loadResult],
  );

  // On mount: show any existing content + resume polling for in-flight jobs.
  useEffect(() => {
    mounted.current = true;
    void (async () => {
      try {
        const product = await getProduct(productId);
        if (!mounted.current) {
          return;
        }
        const existingCopy = (product as { marketing_copy_json?: unknown }).marketing_copy_json;
        const existingBrief = (product as { image_instruction_json?: unknown }).image_instruction_json;
        if (existingCopy) {
          setCopy(existingCopy);
          setCopyZh((product as { marketing_copy_zh?: string | null }).marketing_copy_zh ?? null);
          setCopyStatus("done");
        }
        if (existingBrief) {
          setBrief(existingBrief);
          setBriefZh((product as { image_instruction_zh?: string | null }).image_instruction_zh ?? null);
          setBriefStatus("done");
        }
        setCopyChannel((product as { channel?: string | null }).channel ?? channel ?? null);
        const jobs = await getGenerationJobs(productId);
        if (!mounted.current) {
          return;
        }
        const copyJob = latestJob(jobs, "marketing_copy");
        if (copyJob && (copyJob.status === "pending" || copyJob.status === "running")) {
          setCopyStatus("generating");
          void poll("marketing_copy");
        }
        const briefJob = latestJob(jobs, "image_brief");
        if (briefJob && (briefJob.status === "pending" || briefJob.status === "running")) {
          setBriefStatus("generating");
          void poll("image_brief");
        }
      } catch {
        // best-effort hydrate; leave sections idle on error
      }
    })();
    return () => {
      mounted.current = false;
      clearTimers();
    };
  }, [productId, channel, poll, clearTimers]);

  const handleGenerateCopy = async () => {
    setCopyStatus("generating");
    setCopyError(null);
    try {
      await generateProductCopy(productId);
      void poll("marketing_copy");
    } catch (error) {
      setCopyStatus("failed");
      setCopyError(errorMessage(error, "提交生成任务失败，请重试。"));
    }
  };

  const handleGenerateBrief = async () => {
    setBriefStatus("generating");
    setBriefError(null);
    try {
      await generateProductImageBrief(productId);
      void poll("image_brief");
    } catch (error) {
      setBriefStatus("failed");
      setBriefError(errorMessage(error, "提交生成任务失败（需先有文案）。"));
    }
  };

  const copyBusy = copyStatus === "generating";
  const briefBusy = briefStatus === "generating";

  return (
    <>
      <section className={styles.sellingPointsSection} aria-labelledby="k-copy">
        <div className={styles.sellingPointsHeading}>
          <div>
            <span className={styles.eyebrow}>文案</span>
            <h4 id="k-copy">产品文案 · {channelLabel(copyChannel ?? channel)}</h4>
          </div>
          <div className={styles.headingActions}>
            <button
              className="secondary-button"
              disabled={copyBusy}
              onClick={() => void handleGenerateCopy()}
              type="button"
            >
              {copyBusy ? (
                <LoaderCircle aria-hidden="true" className="spin" size={16} />
              ) : (
                <Sparkles aria-hidden="true" size={16} />
              )}
              {copyBusy ? "后台生成中…" : copy ? "重新生成" : "生成文案"}
            </button>
          </div>
        </div>
        {copyError ? <p className={styles.sellingPointsError}>{copyError}</p> : null}
        {copyBusy ? (
          <p className={styles.copyReviewHint}>
            AI 正在后台生成完整文案（约 1–2 分钟）—— 你可以先去忙别的，完成后这里会自动显示。
          </p>
        ) : copy ? (
          <div className={styles.sellingPointsResult}>
            <p className={styles.copyReviewHint}>
              左侧原文（发送给 P / I 的唯一版本），右侧 DeepSeek 翻的人话中文，仅供你审核。
            </p>
            <div className={styles.copyReviewSplit}>
              <div className={styles.copyReviewCol}>
                <p className={styles.copyReviewColLabel}>原文 · 原始版本</p>
                <pre className={styles.copyReviewPanel}>{JSON.stringify(copy, null, 2)}</pre>
              </div>
              <div className={styles.copyReviewCol}>
                <p className={styles.copyReviewColLabel}>人话中文 · 仅供审核</p>
                <div
                  className={`${styles.copyReviewZh}${copyZh ? "" : ` ${styles.copyReviewZhPending}`}`}
                >
                  {copyZh ?? "中文翻译暂未生成（不影响原文，可点「重新生成」补上）。"}
                </div>
              </div>
            </div>
          </div>
        ) : (
          <p className={styles.copyReviewHint}>
            点击「生成文案」，AI 按对应渠道 skill 写好标题 / 卖点 / 描述，供你审核。
          </p>
        )}
      </section>

      <section className={styles.sellingPointsSection} aria-labelledby="k-brief">
        <div className={styles.sellingPointsHeading}>
          <div>
            <span className={styles.eyebrow}>作图指令</span>
            <h4 id="k-brief">作图指令 · Art Direction</h4>
          </div>
          <div className={styles.headingActions}>
            <button
              className="secondary-button"
              disabled={briefBusy || !copy}
              onClick={() => void handleGenerateBrief()}
              title={copy ? undefined : "请先生成文案"}
              type="button"
            >
              {briefBusy ? (
                <LoaderCircle aria-hidden="true" className="spin" size={16} />
              ) : (
                <ClipboardList aria-hidden="true" size={16} />
              )}
              {briefBusy ? "后台生成中…" : brief ? "重新生成" : "生成作图指令"}
            </button>
            <button
              className="secondary-button"
              disabled={!brief}
              onClick={() => router.push(`/image-system?product_id=${productId}`)}
              title={brief ? "带作图指令去 I 作图" : "请先生成作图指令"}
              type="button"
            >
              <ArrowUpRight aria-hidden="true" size={16} />
              去 I 作图
            </button>
          </div>
        </div>
        {briefError ? <p className={styles.sellingPointsError}>{briefError}</p> : null}
        {briefBusy ? (
          <p className={styles.copyReviewHint}>AI 正在后台生成整套作图指令（约 1–2 分钟）…</p>
        ) : brief ? (
          <div className={styles.sellingPointsResult}>
            <p className={styles.copyReviewHint}>
              左侧原文（一键「去 I 作图」带过去的唯一版本），右侧人话中文仅供你审核。
            </p>
            <div className={styles.copyReviewSplit}>
              <div className={styles.copyReviewCol}>
                <p className={styles.copyReviewColLabel}>原文 · 原始版本</p>
                <pre className={styles.copyReviewPanel}>{JSON.stringify(brief, null, 2)}</pre>
              </div>
              <div className={styles.copyReviewCol}>
                <p className={styles.copyReviewColLabel}>人话中文 · 仅供审核</p>
                <div
                  className={`${styles.copyReviewZh}${briefZh ? "" : ` ${styles.copyReviewZhPending}`}`}
                >
                  {briefZh ?? "中文翻译暂未生成（不影响原文，可点「重新生成」补上）。"}
                </div>
              </div>
            </div>
          </div>
        ) : (
          <p className={styles.copyReviewHint}>
            先生成文案，再点这里 —— AI 读文案，写出每张图的风格 / 构图 / prompt。
          </p>
        )}
      </section>

      <RenderImagesPanel hasBrief={Boolean(brief)} productId={productId} />

      <FaqEditorPanel productId={productId} />

      <BrandAuditPanel productId={productId} />
    </>
  );
}
