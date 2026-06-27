"use client";

import { Loader2, Search } from "lucide-react";
import { useState } from "react";

import { startKeywordResearch } from "./api";
import styles from "./ResearchTriggerPanel.module.css";
import type { ResearchRun, ResearchTriggerUiState } from "./types";

const statusFlow: ResearchTriggerUiState[] = [
  "idle",
  "pending",
  "running",
  "completed",
];

const defaultProductId = "k-series-product-knowledge-001";

export function ResearchTriggerPanel() {
  const [productId, setProductId] = useState(defaultProductId);
  const [uiState, setUiState] = useState<ResearchTriggerUiState>("idle");
  const [researchRun, setResearchRun] = useState<ResearchRun | null>(null);
  const [error, setError] = useState("");

  async function handleStartResearch() {
    const normalizedProductId = productId.trim();

    if (!normalizedProductId) {
      setError("启动关键词调研前需要填写产品ID。");
      return;
    }

    setError("");
    setResearchRun(null);
    setUiState("pending");

    try {
      setUiState("running");
      const run = await startKeywordResearch(normalizedProductId);
      setResearchRun(run);
      setUiState("completed");
    } catch (caught) {
      setUiState("idle");
      setError(
        caught instanceof Error
          ? caught.message
          : "关键词调研无法启动。",
      );
    }
  }

  return (
    <section className={styles.panel} aria-labelledby="research-trigger">
      <div className={styles.heading}>
        <div>
          <span className="section-index">调研</span>
          <h3 id="research-trigger">关键词调研触发</h3>
          <p>
            为产品记录启动关键词调研，并跟踪最新运行状态。
          </p>
        </div>
      </div>

      <div className={styles.form}>
        <label className={styles.field}>
          <span>产品ID</span>
          <input
            onChange={(event) => setProductId(event.target.value)}
            placeholder="产品 UUID 或产品键"
            type="text"
            value={productId}
          />
        </label>

        <button
          className="primary-button"
          disabled={uiState === "pending" || uiState === "running"}
          onClick={() => void handleStartResearch()}
          type="button"
        >
          {uiState === "pending" || uiState === "running" ? (
            <Loader2 aria-hidden="true" className="spin" size={16} />
          ) : (
            <Search aria-hidden="true" size={16} />
          )}
          启动关键词调研
        </button>
      </div>

      <ol className={styles.statusRail} aria-label="关键词调研状态流">
        {statusFlow.map((status) => (
          <li className={getStatusClass(status, uiState)} key={status}>
            {researchStatusLabel(status)}
          </li>
        ))}
      </ol>

      {researchRun ? <ResearchRunSummary researchRun={researchRun} /> : null}

      <p className={`${styles.message} ${error ? styles.error : ""}`}>
        {error || statusMessageFor(uiState)}
      </p>
    </section>
  );
}

function ResearchRunSummary({ researchRun }: { researchRun: ResearchRun }) {
  return (
    <dl className={styles.resultGrid}>
      <div>
        <dt>运行ID</dt>
        <dd>{researchRun.id}</dd>
      </div>
      <div>
        <dt>状态</dt>
        <dd>{researchStatusLabel(researchRun.status)}</dd>
      </div>
      <div>
        <dt>时间</dt>
        <dd>{formatTimestamp(researchRun.updated_at)}</dd>
      </div>
    </dl>
  );
}

function getStatusClass(
  status: ResearchTriggerUiState,
  currentStatus: ResearchTriggerUiState,
) {
  const statusIndex = statusFlow.indexOf(status);
  const currentIndex = statusFlow.indexOf(currentStatus);

  if (status === currentStatus) {
    return `${styles.statusStep} ${styles.statusStepActive}`;
  }

  if (statusIndex < currentIndex) {
    return `${styles.statusStep} ${styles.statusStepComplete}`;
  }

  return styles.statusStep;
}

function statusMessageFor(status: ResearchTriggerUiState) {
  if (status === "pending") {
    return "关键词调研启动请求等待中。";
  }

  if (status === "running") {
    return "关键词调研运行正在创建。";
  }

  if (status === "completed") {
    return "关键词调研已完成。";
  }

  return "空闲。尚未启动关键词调研。";
}

function researchStatusLabel(status: string) {
  const labels: Record<string, string> = {
    completed: "已完成",
    idle: "空闲",
    pending: "等待中",
    running: "运行中",
  };

  return labels[status] ?? "待处理";
}

function formatTimestamp(value: string) {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}
