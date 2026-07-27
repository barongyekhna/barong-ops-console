"use client";

import { LoaderCircle, ShieldAlert, ShieldCheck, ShieldQuestion } from "lucide-react";
import type { CSSProperties } from "react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  getGenerationJobs,
  getProduct,
  ignoreBrandFinding,
  runBrandAudit,
} from "./api";
import styles from "./ProductKnowledge.module.css";

// 与后端 brand_guard.brand_finding_fingerprint 保持一致
function textFingerprint(surface?: string, term?: string): string {
  const s = (surface ?? "").trim().toLowerCase();
  const t = (term ?? "").trim().toLowerCase().split(/\s+/).join(" ");
  return `text::${s}::${t}`;
}
function imageFingerprint(position?: number, category?: string): string {
  const c = (category ?? "").trim().toLowerCase();
  return `image::${position}::${c}`;
}

const LINK_BTN_STYLE: CSSProperties = {
  marginLeft: 6,
  background: "none",
  border: "none",
  color: "#1a73e8",
  cursor: "pointer",
  padding: 0,
  font: "inherit",
  textDecoration: "underline",
};

type BrandAuditPanelProps = {
  productId: string;
};

type TextViolation = {
  surface?: string;
  term?: string;
  evidence?: string;
};

type ImageViolation = {
  asset_id?: string;
  position?: number;
  category?: string;
  finding?: string;
};

type BrandAudit = {
  clean?: boolean;
  audited_at?: string;
  attempt?: number;
  blacklist_terms?: string[];
  text_violations?: TextViolation[];
  image_violations?: ImageViolation[];
  ignored_findings?: string[];
  errors?: string[];
};

const POLL_MS = 6000;

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

export function BrandAuditPanel({ productId }: BrandAuditPanelProps) {
  const [audit, setAudit] = useState<BrandAudit | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyFp, setBusyFp] = useState<string | null>(null);

  const mounted = useRef(true);
  const timer = useRef<number | null>(null);

  const handleIgnore = async (
    fingerprint: string,
    payload: Parameters<typeof ignoreBrandFinding>[1],
  ) => {
    setBusyFp(fingerprint);
    setError(null);
    try {
      const result = await ignoreBrandFinding(productId, payload);
      if (mounted.current) {
        setAudit(result.brand_audit_json as BrandAudit);
      }
    } catch (ignoreError) {
      if (mounted.current) {
        setError(errorMessage(ignoreError, "放行/撤销失败，请重试。"));
      }
    } finally {
      if (mounted.current) {
        setBusyFp(null);
      }
    }
  };

  const clearTimer = useCallback(() => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
  }, []);

  const loadAudit = useCallback(async () => {
    const product = await getProduct(productId);
    if (!mounted.current) {
      return;
    }
    setAudit(
      ((product as { brand_audit_json?: BrandAudit | null }).brand_audit_json ??
        null) as BrandAudit | null,
    );
  }, [productId]);

  const poll = useCallback(async () => {
    if (!mounted.current) {
      return;
    }
    try {
      const jobs = await getGenerationJobs(productId);
      const job = jobs.find((item) => item.job_type === "brand_audit");
      if (!mounted.current) {
        return;
      }
      if (job && (job.status === "pending" || job.status === "running")) {
        setRunning(true);
        clearTimer();
        timer.current = window.setTimeout(() => void poll(), POLL_MS);
        return;
      }
      setRunning(false);
      if (job && job.status === "failed") {
        setError(job.error || "品牌审查任务失败，请重试。");
      }
      await loadAudit();
    } catch (pollError) {
      if (mounted.current) {
        setRunning(false);
        setError(errorMessage(pollError, "查询品牌审查状态失败。"));
      }
    }
  }, [productId, loadAudit, clearTimer]);

  useEffect(() => {
    mounted.current = true;
    void poll();
    return () => {
      mounted.current = false;
      clearTimer();
    };
  }, [poll, clearTimer]);

  const handleRun = async () => {
    setError(null);
    setRunning(true);
    try {
      await runBrandAudit(productId);
      clearTimer();
      timer.current = window.setTimeout(() => void poll(), POLL_MS);
    } catch (runError) {
      setRunning(false);
      setError(errorMessage(runError, "提交品牌审查失败，请重试。"));
    }
  };

  const textViolations = audit?.text_violations ?? [];
  const imageViolations = audit?.image_violations ?? [];
  const auditErrors = audit?.errors ?? [];
  const ignoredSet = new Set(audit?.ignored_findings ?? []);
  const hasProblems =
    textViolations.length > 0 || imageViolations.length > 0 || auditErrors.length > 0;

  return (
    <section className={styles.sellingPointsSection} aria-labelledby="k-brand-audit">
      <div className={styles.sellingPointsHeading}>
        <div>
          <span className={styles.eyebrow}>品牌硬门</span>
          <h4 id="k-brand-audit">品牌审查 · 独立站零第三方品牌</h4>
        </div>
        <div className={styles.headingActions}>
          <button
            className="secondary-button"
            disabled={running}
            onClick={() => void handleRun()}
            title="AI 全面检查文字面和每张成品图：任何第三方品牌名/logo 都会拦下"
            type="button"
          >
            {running ? (
              <LoaderCircle aria-hidden="true" className="spin" size={16} />
            ) : (
              <ShieldQuestion aria-hidden="true" size={16} />
            )}
            {running ? "审查中…" : audit ? "重新审查" : "跑品牌审查"}
          </button>
        </div>
      </div>

      {error ? <p className={styles.sellingPointsError}>{error}</p> : null}

      {running ? (
        <p className={styles.copyReviewHint}>
          AI 正在逐面检查（标题 / 文案 / SEO / 每张图的文字与像素）…
          检出图像品牌标识会自动重渲染并再次审查。
        </p>
      ) : null}

      {!running && !audit ? (
        <p className={styles.copyReviewHint}>
          尚未审查。成品图渲染完成后会自动跑一次；也可手动触发。
          未通过审查的产品无法上架（硬门禁）。
        </p>
      ) : null}

      {!running && audit ? (
        <div className={styles.sellingPointsResult}>
          <p
            className={styles.copyReviewHint}
            style={{ display: "flex", alignItems: "center", gap: 6 }}
          >
            {audit.clean ? (
              <>
                <ShieldCheck aria-hidden="true" color="#0f9d58" size={17} />
                <strong>通过</strong> —— 未检出任何第三方品牌（
                {audit.audited_at?.slice(0, 19).replace("T", " ")}）
                {audit.blacklist_terms?.length
                  ? ` · 黑名单：${audit.blacklist_terms.join(", ")}`
                  : null}
              </>
            ) : (
              <>
                <ShieldAlert aria-hidden="true" color="#d93025" size={17} />
                <strong>未通过</strong> —— 上架已被拦截，处理下列问题后重新审查
              </>
            )}
          </p>
          {hasProblems ? (
            <ul className={styles.copyReviewHint} style={{ margin: 0, paddingLeft: 18 }}>
              {textViolations.map((violation, index) => {
                const fp = textFingerprint(violation.surface, violation.term);
                const ignored = ignoredSet.has(fp);
                return (
                  <li key={`t${index}`} style={ignored ? { opacity: 0.55 } : undefined}>
                    文字：<strong>{violation.term}</strong>（{violation.surface}）
                    {violation.evidence ? ` —— “…${violation.evidence}…”` : null}
                    {ignored ? <em> · 已放行</em> : null}{" "}
                    <button
                      type="button"
                      style={LINK_BTN_STYLE}
                      disabled={busyFp === fp}
                      onClick={() =>
                        void handleIgnore(fp, {
                          kind: "text",
                          ignored: !ignored,
                          surface: violation.surface,
                          term: violation.term,
                        })
                      }
                    >
                      {busyFp === fp ? "…" : ignored ? "撤销放行" : "忽略（放行）"}
                    </button>
                  </li>
                );
              })}
              {imageViolations.map((violation, index) => {
                const fp = imageFingerprint(violation.position, violation.category);
                const ignored = ignoredSet.has(fp);
                return (
                  <li key={`i${index}`} style={ignored ? { opacity: 0.55 } : undefined}>
                    图像：第 {violation.position} 张 —— {violation.finding}
                    {ignored ? <em> · 已放行</em> : null}{" "}
                    <button
                      type="button"
                      style={LINK_BTN_STYLE}
                      disabled={busyFp === fp}
                      onClick={() =>
                        void handleIgnore(fp, {
                          kind: "image",
                          ignored: !ignored,
                          position: violation.position,
                          category: violation.category,
                        })
                      }
                    >
                      {busyFp === fp ? "…" : ignored ? "撤销放行" : "忽略（放行）"}
                    </button>
                  </li>
                );
              })}
              {auditErrors.map((item, index) => (
                <li key={`e${index}`}>审查步骤失败（不可忽略，fail-closed）：{item}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
