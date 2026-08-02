"use client";

import styles from "./ContentDesk.module.css";
import type { Analysis } from "./types";

/**
 * DeepSeek 解读，**七项逐项显示，一项不藏**。
 *
 * SEO 面板现在只渲染 risks，把翻译 / 在 GEO 里的作用 / 为什么这么写 / 优点 /
 * 模型 全藏了——类型定义里明明都有。显示层自己挑字段就会这样。用户点名要
 * 「DeepSeek 检查审阅必须在浮窗里显示完整」，所以这里逐项列。
 *
 * 没解读时**不静默隐藏**，显示一个「跑解读」按钮：安静地少一块信息，
 * 人根本不会发现自己少看了什么。
 */
const TEXT_ROWS: { key: keyof Analysis; label: string }[] = [
  { key: "translation", label: "中文翻译" },
  { key: "geo_role", label: "在 AI 答案里可能起什么作用" },
  { key: "why_written_this_way", label: "为什么这么写" },
];

export function AnalysisPanel({
  analysis,
  busy,
  onAnalyze,
}: {
  analysis: Analysis | null;
  busy: boolean;
  onAnalyze: () => void;
}) {
  if (!analysis) {
    return (
      <div className={styles.panel}>
        <div className={styles.panelLabel}>AI 解读</div>
        <p className={styles.panelText}>
          这篇还没有解读。解读会读一遍全文，给出中文翻译、写法分析和逐条批评——
          「按批评重写」也要靠它。
        </p>
        <button
          className={`${styles.btn} ${styles.btnQuiet}`}
          disabled={busy}
          onClick={onAnalyze}
          style={{ marginTop: 10 }}
          type="button"
        >
          {busy ? "解读中…（约 30 秒）" : "跑一次解读"}
        </button>
      </div>
    );
  }

  const strengths = analysis.strengths ?? [];
  const risks = analysis.risks ?? [];

  return (
    <div className={styles.panel}>
      <div className={styles.panelLabel}>
        AI 解读
        {analysis.model ? ` · ${analysis.model}` : ""}
        {analysis.skill_version ? ` · ${analysis.skill_version}` : ""}
      </div>

      {TEXT_ROWS.map(({ key, label }) => (
        <div className={styles.panelRow} key={key}>
          <div className={styles.panelLabel}>{label}</div>
          <p className={styles.panelText}>
            {(analysis[key] as string | null) || "（这一项模型没给）"}
          </p>
        </div>
      ))}

      <div className={styles.panelRow}>
        <div className={`${styles.panelLabel} ${styles.good}`}>优点</div>
        {strengths.length ? (
          <ul className={styles.panelList}>
            {strengths.map((item, index) => (
              <li key={`${index}-${item.slice(0, 24)}`}>{item}</li>
            ))}
          </ul>
        ) : (
          <p className={styles.panelText}>（这一项模型没给）</p>
        )}
      </div>

      <div className={styles.panelRow}>
        <div className={`${styles.panelLabel} ${styles.risk}`}>
          批评 / 风险
        </div>
        {risks.length ? (
          <ul className={styles.panelList}>
            {risks.map((item, index) => (
              // key 用 index 前缀：两条一模一样的批评并不罕见，
              // 纯文本当 key 会让 React 报重复键。
              <li key={`${index}-${item.slice(0, 24)}`}>{item}</li>
            ))}
          </ul>
        ) : (
          <p className={styles.panelText}>
            解读没提出问题——这篇不需要重写。
          </p>
        )}
      </div>
    </div>
  );
}
