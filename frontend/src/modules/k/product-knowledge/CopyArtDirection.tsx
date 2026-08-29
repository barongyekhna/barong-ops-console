"use client";

import {
  ArrowUpRight,
  ClipboardList,
  Copy,
  Image as ImageIcon,
  LoaderCircle,
  MonitorSmartphone,
  Sparkles,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  codexPromptForSku,
  generateProductCopy,
  generateProductImageBrief,
  getGenerationJobs,
  getProduct,
  type GenerationJob,
} from "./api";
import {
  getMyMcpAccess,
  resetMyMcpToken,
  type McpAccessMe,
  type McpTokenIssued,
} from "@/lib/profile-api";
import styles from "./ProductKnowledge.module.css";
import { BrandAuditPanel } from "./BrandAuditPanel";
import { FaqEditorPanel } from "./FaqEditorPanel";
import { ImageStudioModal } from "./ImageStudioModal";

type CopyArtDirectionProps = {
  productId: string;
  /** 「唤起 Codex 作图」要把 SKU 写进预填指令里。 */
  sku?: string | null;
  channel?: string | null;
  /** 作图保存成功后通知上层刷新（图片绑定板块等）。 */
  onAssetsSaved?: () => void;
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

export function CopyArtDirection({ productId, sku, channel, onAssetsSaved }: CopyArtDirectionProps) {
  const router = useRouter();

  // 外部精修通道(Codex 经 MCP):唤起 + 新电脑接入面板。
  const [codexStatus, setCodexStatus] = useState<string | null>(null);
  const [mcpAccess, setMcpAccess] = useState<McpAccessMe | null>(null);
  const [mcpIssued, setMcpIssued] = useState<McpTokenIssued | null>(null);
  const [mcpSetupOpen, setMcpSetupOpen] = useState(false);
  const [mcpSetupError, setMcpSetupError] = useState<string | null>(null);
  const [mcpBusy, setMcpBusy] = useState(false);
  const [mcpCopied, setMcpCopied] = useState<"mac" | "windows" | null>(null);
  const [mcpOs, setMcpOs] = useState<"mac" | "windows">("mac");
  useEffect(() => {
    if (typeof navigator !== "undefined" && /windows/i.test(navigator.userAgent)) {
      setMcpOs("windows");
    }
  }, []);

  async function handleInvokeCodex() {
    const prompt = codexPromptForSku((sku ?? "").trim() || productId);
    let copied = false;
    try {
      await navigator.clipboard.writeText(prompt);
      copied = true;
    } catch {
      copied = false;
    }
    // codex://new?prompt=… 会打开桌面版并把指令预填进输入框(不自动发送)。
    // 没装 Codex 的电脑点了没反应——指令已在剪贴板,提示用户自己粘贴。
    window.location.href = `codex://new?prompt=${encodeURIComponent(prompt)}`;
    setCodexStatus(
      copied
        ? "已唤起 Codex,指令同时复制到剪贴板;若没弹出 Codex,请打开它粘贴指令。"
        : "已尝试唤起 Codex;若没弹出,请打开 Codex 手动粘贴指令(剪贴板不可用)。",
    );
    window.setTimeout(() => setCodexStatus(null), 8000);
  }

  async function handleToggleMcpSetup() {
    if (mcpSetupOpen) {
      setMcpSetupOpen(false);
      return;
    }
    setMcpSetupOpen(true);
    if (mcpAccess) {
      return;
    }
    setMcpSetupError(null);
    try {
      setMcpAccess(await getMyMcpAccess());
    } catch (error) {
      setMcpSetupError(errorMessage(error, "取不到你的 MCP 钥匙状态。"));
    }
  }

  async function handleIssueMyToken() {
    if (
      mcpAccess?.summary.has_token &&
      !window.confirm("重置会让你现在所有电脑上的旧钥匙立刻失效,需要重新贴一次装机命令。继续?")
    ) {
      return;
    }
    setMcpBusy(true);
    setMcpSetupError(null);
    try {
      const issued = await resetMyMcpToken();
      setMcpIssued(issued);
      setMcpAccess((prev) => (prev ? { ...prev, summary: issued.summary } : prev));
    } catch (error) {
      setMcpSetupError(errorMessage(error, "生成钥匙失败。"));
    } finally {
      setMcpBusy(false);
    }
  }

  async function handleCopySetup(kind: "mac" | "windows") {
    const text =
      kind === "mac" ? mcpIssued?.setup_command_mac : mcpIssued?.setup_command_windows;
    if (!text) {
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      setMcpCopied(kind);
      window.setTimeout(() => setMcpCopied(null), 2500);
    } catch {
      setMcpSetupError("复制失败,请手动选中命令复制。");
    }
  }

  const [copy, setCopy] = useState<unknown>(null);
  // 文案生成完成后 +1，驱动 FAQ 面板重新拉取（否则显示旧的空状态）。
  const [faqRefreshKey, setFaqRefreshKey] = useState(0);
  const [copyZh, setCopyZh] = useState<string | null>(null);
  const [copyChannel, setCopyChannel] = useState<string | null>(channel ?? null);
  const [copyStatus, setCopyStatus] = useState<SectionStatus>("idle");
  const [copyError, setCopyError] = useState<string | null>(null);

  const [brief, setBrief] = useState<unknown>(null);
  const [studioOpen, setStudioOpen] = useState(false);
  // OverlayModal 的 onClose 必须是稳定引用，否则它每次 render 重挂 effect，
  // 那时滚动条已锁上、scrollbarWidth 会算成 0，padding 补偿就出错。
  const closeStudio = useCallback(() => setStudioOpen(false), []);
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
      setFaqRefreshKey((key) => key + 1);
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
              去工作台作图
            </button>
            <button
              className="secondary-button"
              disabled={!brief}
              onClick={() => void handleInvokeCodex()}
              title={
                brief
                  ? "打开本机 Codex,预填「去 K 取简报出图」的指令(有眼睛的画师,几何/物理更靠谱)"
                  : "请先生成作图指令"
              }
              type="button"
            >
              <Sparkles aria-hidden="true" size={16} />
              唤起 Codex 作图
            </button>
            <button
              className="secondary-button"
              onClick={() => void handleToggleMcpSetup()}
              title="换一台电脑用 Codex 作图?复制一行命令贴进终端即可接入"
              type="button"
            >
              <MonitorSmartphone aria-hidden="true" size={16} />
              新电脑接入 Codex
            </button>
          </div>
        </div>
        {codexStatus ? <p className={styles.copyReviewHint}>{codexStatus}</p> : null}
        {mcpSetupOpen ? (
          <div className={styles.mcpSetupPanel}>
            <p className={styles.copyReviewColLabel}>
              新电脑接入 Codex · 你的个人钥匙
              {mcpAccess?.summary.has_token
                ? ` · ${mcpAccess.summary.token_prefix}… · ${mcpAccess.summary.status === "disabled" ? "已被停用" : "正常"}`
                : " · 尚未生成"}
            </p>
            {mcpSetupError ? <p className={styles.sellingPointsError}>{mcpSetupError}</p> : null}
            {!mcpAccess && !mcpSetupError ? (
              <p className={styles.copyReviewHint}>读取中…</p>
            ) : null}
            {mcpAccess && !mcpAccess.eligible ? (
              <p className={styles.sellingPointsError}>机器人账号不发个人钥匙。</p>
            ) : null}
            {mcpAccess?.eligible && mcpAccess.summary.status === "disabled" ? (
              <p className={styles.sellingPointsError}>你的钥匙已被管理员停用,请联系管理员启用。</p>
            ) : null}
            {mcpAccess?.eligible && mcpAccess.summary.status !== "disabled" && !mcpIssued ? (
              <div className={styles.mcpSetupRow}>
                <span className={styles.mcpSetupOs}>钥匙</span>
                <span className={styles.copyReviewHint}>
                  {mcpAccess.summary.has_token
                    ? "钥匙明文只在生成那一刻显示一次。换电脑或忘了就重置一把新的(旧的立刻失效)。"
                    : "还没有钥匙。生成后会显示一行装机命令,贴进电脑终端即可接入。"}
                </span>
                <button
                  className="secondary-button"
                  disabled={mcpBusy}
                  onClick={() => void handleIssueMyToken()}
                  type="button"
                >
                  {mcpBusy ? <LoaderCircle aria-hidden="true" className="spin" size={14} /> : null}
                  {mcpAccess.summary.has_token ? "重置钥匙并显示命令" : "生成我的钥匙"}
                </button>
              </div>
            ) : null}
            {mcpIssued ? (
              <>
                <p className={styles.copyReviewHint}>
                  检测到你的电脑是 <strong>{mcpOs === "windows" ? "Windows" : "Mac"}</strong>,复制下面这一行贴进终端回车即可。
                  {" "}
                  <button
                    className="secondary-button"
                    onClick={() => setMcpOs(mcpOs === "windows" ? "mac" : "windows")}
                    type="button"
                  >
                    不对?切到 {mcpOs === "windows" ? "Mac" : "Windows"}
                  </button>
                </p>
                <div className={styles.mcpSetupRow}>
                  <span className={styles.mcpSetupOs}>{mcpOs === "windows" ? "Windows" : "Mac"}</span>
                  <code className={styles.mcpSetupCmd}>
                    {mcpOs === "windows" ? mcpIssued.setup_command_windows : mcpIssued.setup_command_mac}
                  </code>
                  <button
                    className="secondary-button"
                    onClick={() => void handleCopySetup(mcpOs)}
                    type="button"
                  >
                    <Copy aria-hidden="true" size={14} />
                    {mcpCopied === mcpOs ? "已复制" : "复制这一行"}
                  </button>
                </div>
                <p className={styles.copyReviewHint}>
                  {mcpIssued.verify_hint} 这行命令带着你的个人钥匙,只显示这一次;别贴给别人——交上去的图会记在你名下。
                </p>
              </>
            ) : null}
          </div>
        ) : null}
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

      {/* 作图整套流程（圈产品 / 工作原理 / 出图挑图）都在浮窗里走，
          详情页只留这一个入口 —— 2026-08-03 用户拍板：K 页面不许再变长。 */}
      <section className={styles.sellingPointsSection} aria-labelledby="k-studio-entry">
        <div className={styles.sellingPointsHeading}>
          <div>
            <span className={styles.eyebrow}>作图</span>
            <h4 id="k-studio-entry">一次性作图 · 工作台</h4>
          </div>
          <div className={styles.headingActions}>
            <button
              className="secondary-button"
              disabled={!brief}
              onClick={() => setStudioOpen(true)}
              title={brief ? undefined : "请先生成作图指令"}
              type="button"
            >
              <ImageIcon aria-hidden="true" size={16} />
              打开作图工作台
            </button>
          </div>
        </div>
        <p className={styles.copyReviewHint}>
          圈出产品 → 确认它怎么工作 → 出图挑图，都在工作台里完成。
          圈过产品的底图，AI 只会重画背景，产品像素原样保留。
        </p>
      </section>

      {studioOpen ? (
        <ImageStudioModal
          hasBrief={Boolean(brief)}
          onClose={closeStudio}
          onSaved={onAssetsSaved}
          productId={productId}
        />
      ) : null}

      <FaqEditorPanel productId={productId} refreshKey={faqRefreshKey} />

      <BrandAuditPanel productId={productId} />
    </>
  );
}
