"use client";

import { ArrowUpRight, ClipboardList, LoaderCircle, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import {
  generateProductCopy,
  generateProductImageBrief,
  type ProductCopyGenerationResult,
  type ProductImageBriefResult,
} from "./api";
import styles from "./ProductKnowledge.module.css";

type CopyArtDirectionProps = {
  productId: string;
  channel?: string | null;
  initialCopy?: unknown;
  initialImageBrief?: unknown;
};

function channelLabel(channel?: string | null) {
  return channel === "amazon" ? "亚马逊" : "独立站";
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

export function CopyArtDirection({
  productId,
  channel,
  initialCopy,
  initialImageBrief,
}: CopyArtDirectionProps) {
  const [copy, setCopy] = useState<unknown>(initialCopy ?? null);
  const [copyChannel, setCopyChannel] = useState<string | null>(channel ?? null);
  const [copyBusy, setCopyBusy] = useState(false);
  const [copyError, setCopyError] = useState<string | null>(null);

  const [brief, setBrief] = useState<unknown>(initialImageBrief ?? null);
  const [briefBusy, setBriefBusy] = useState(false);
  const [briefError, setBriefError] = useState<string | null>(null);

  const router = useRouter();

  const handleGenerateCopy = async () => {
    setCopyBusy(true);
    setCopyError(null);
    try {
      const result: ProductCopyGenerationResult = await generateProductCopy(productId);
      setCopy(result.marketing_copy ?? null);
      setCopyChannel(result.channel);
    } catch (error) {
      setCopyError(errorMessage(error, "生成文案失败，请重试。"));
    } finally {
      setCopyBusy(false);
    }
  };

  const handleGenerateBrief = async () => {
    setBriefBusy(true);
    setBriefError(null);
    try {
      const result: ProductImageBriefResult = await generateProductImageBrief(productId);
      setBrief(result.image_instruction ?? null);
    } catch (error) {
      setBriefError(errorMessage(error, "生成作图指令失败（需先生成文案）。"));
    } finally {
      setBriefBusy(false);
    }
  };

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
              {copy ? "重新生成" : "生成文案"}
            </button>
          </div>
        </div>
        {copyError ? <p className={styles.sellingPointsError}>{copyError}</p> : null}
        {copy ? (
          <div className={styles.sellingPointsResult}>
            <p className={styles.copyReviewHint}>
              AI 已写好草稿 —— 机器干活，你把关。审核无误后再进入 P。
            </p>
            <pre className={styles.copyReviewPanel}>{JSON.stringify(copy, null, 2)}</pre>
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
              {brief ? "重新生成" : "生成作图指令"}
            </button>
            <button
              className="secondary-button"
              disabled={!brief}
              onClick={() =>
                router.push(`/image-system?product_id=${productId}`)
              }
              title={brief ? "带作图指令去 I 作图" : "请先生成作图指令"}
              type="button"
            >
              <ArrowUpRight aria-hidden="true" size={16} />
              去 I 作图
            </button>
          </div>
        </div>
        {briefError ? <p className={styles.sellingPointsError}>{briefError}</p> : null}
        {brief ? (
          <div className={styles.sellingPointsResult}>
            <p className={styles.copyReviewHint}>
              AI 出的整套作图要求 —— 之后一键「去 I 作图」带过去，你只需上传产品原图。
            </p>
            <pre className={styles.copyReviewPanel}>{JSON.stringify(brief, null, 2)}</pre>
          </div>
        ) : (
          <p className={styles.copyReviewHint}>
            先生成文案，再点这里 —— AI 读文案，写出每张图的风格 / 构图 / prompt。
          </p>
        )}
      </section>
    </>
  );
}
