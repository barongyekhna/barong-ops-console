"use client";

import { useState, type FormEvent } from "react";

import styles from "./Office.module.css";
import { addGoal, controlOffice, decideCard, instructOffice, patchGoal, type OfficeCard, type OfficeGoal, type OfficeRead } from "./office-api";

/** 场景视图和列表视图共用的零件:审批卡、指挥控件、几个格式化小工具。 */

export type Runner = (label: string, action: () => Promise<unknown>) => Promise<boolean>;

// 彩蛋:连点她 5 下。纯前端、固定台词,不调 AI。口吻是女强人 + 温柔大姐姐,不撒娇不暧昧。
export const EASTER_LINES = [
  "今天的活我扛着，你去喝口水。",
  "别急，先把最要紧的一件做完，剩下的交给我。",
  "数据我盯着呢，有事我第一时间说。",
  "你定方向，细活我来跑。",
  "今天也辛苦了，早点休息，明天见。",
  "卡片我都排好序了，你挑最上面那张就行。",
];

export function pickEasterLine(): string {
  return EASTER_LINES[Math.floor(Math.random() * EASTER_LINES.length)];
}

export function minutesAgo(seconds: number | null): string {
  if (seconds == null) return "从没上过线";
  if (seconds < 60) return "刚刚";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} 分钟没动静`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours} 小时没动静` : `${Math.round(hours / 24)} 天没动静`;
}

export function timeText(iso: string | null): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("zh-CN", { hour: "2-digit", minute: "2-digit", month: "numeric", day: "numeric" });
  } catch {
    return iso;
  }
}

export function dossierIdOf(card: OfficeCard): number | null {
  if (card.kind !== "create_k_dossier") return null;
  const evidence = card.evidence as { dossier_id?: unknown } | null;
  const id = Number(evidence?.dossier_id);
  return Number.isFinite(id) && id > 0 ? id : null;
}

export function CardItem({
  card,
  canCommand,
  busy,
  run,
  onOpenDossier,
}: {
  card: OfficeCard;
  canCommand: boolean;
  busy: boolean;
  run: Runner;
  onOpenDossier?: (id: number) => void;
}) {
  const dossierId = dossierIdOf(card);
  const [expanded, setExpanded] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");

  return (
    <article className={styles.card}>
      <button className={styles.cardHead} onClick={() => setExpanded((value) => !value)} type="button">
        <span className={styles.cardRef}>#{card.ref}</span>
        <strong>{card.title}</strong>
      </button>
      <p>{card.conclusion}</p>
      {dossierId !== null && onOpenDossier ? (
        <button className={styles.linkButton} onClick={() => onOpenDossier(dossierId)} type="button">
          看档案 →
        </button>
      ) : null}
      {expanded ? (
        <dl className={styles.cardDetail}>
          {card.why ? (
            <>
              <dt>为什么</dt>
              <dd>{card.why}</dd>
            </>
          ) : null}
          {card.if_not ? (
            <>
              <dt>不做会怎样</dt>
              <dd>{card.if_not}</dd>
            </>
          ) : null}
          <dt>能不能撤回</dt>
          <dd>{card.reversible ? "能" : "不能"}</dd>
          <dt>把握</dt>
          <dd>{card.confidence === "high" ? "高" : card.confidence === "low" ? "低" : "中"}</dd>
          <dt>证据</dt>
          <dd>
            <pre>{JSON.stringify(card.evidence, null, 2)}</pre>
          </dd>
        </dl>
      ) : null}
      {canCommand ? (
        rejecting ? (
          <form
            className={styles.rejectForm}
            onSubmit={(event: FormEvent) => {
              event.preventDefault();
              if (!reason.trim()) return;
              void run("驳回失败", () => decideCard(card.ref, "reject", reason.trim())).then((ok) => {
                if (ok) {
                  setRejecting(false);
                  setReason("");
                }
              });
            }}
          >
            <textarea
              aria-label="驳回原因"
              onChange={(event) => setReason(event.target.value)}
              placeholder="驳回原因（必填，她会记住）"
              rows={2}
              value={reason}
            />
            <div className={styles.inlineActions}>
              <button disabled={busy || !reason.trim()} type="submit">
                确认驳回
              </button>
              <button onClick={() => setRejecting(false)} type="button">
                取消
              </button>
            </div>
          </form>
        ) : (
          <div className={styles.inlineActions}>
            <button className={styles.primary} disabled={busy} onClick={() => void run("批准失败", () => decideCard(card.ref, "approve"))} type="button">
              批
            </button>
            <button disabled={busy} onClick={() => setRejecting(true)} type="button">
              驳
            </button>
          </div>
        )
      ) : null}
    </article>
  );
}

export function PauseButton({ office, busy, run }: { office: OfficeRead; busy: boolean; run: Runner }) {
  return (
    <button
      disabled={busy}
      onClick={() => void run(office.paused ? "恢复失败" : "暂停失败", () => controlOffice(office.paused ? "resume" : "pause"))}
      type="button"
    >
      {office.paused ? "让她接着干" : "先停一停"}
    </button>
  );
}

export function InstructForm({ busy, run }: { busy: boolean; run: Runner }) {
  const [instruction, setInstruction] = useState("");
  return (
    <form
      className={styles.row}
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        const text = instruction.trim();
        if (!text) return;
        void run("交代失败", () => instructOffice(text)).then((ok) => ok && setInstruction(""));
      }}
    >
      <input aria-label="交代一句" onChange={(event) => setInstruction(event.target.value)} placeholder="交代一句…" value={instruction} />
      <button disabled={busy || !instruction.trim()} type="submit">
        交代
      </button>
    </form>
  );
}

export function GoalForm({ busy, run }: { busy: boolean; run: Runner }) {
  const [goalText, setGoalText] = useState("");
  const [metric, setMetric] = useState("");
  const [target, setTarget] = useState("");
  return (
    <form
      className={styles.row}
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        const text = goalText.trim();
        if (text.length < 2) return;
        const numericTarget = target.trim() ? Number(target) : undefined;
        void run("加目标失败", () =>
          addGoal(text, metric.trim() || undefined, Number.isFinite(numericTarget) ? numericTarget : undefined),
        ).then((ok) => {
          if (ok) {
            setGoalText("");
            setMetric("");
            setTarget("");
          }
        });
      }}
    >
      <input aria-label="新目标" onChange={(event) => setGoalText(event.target.value)} placeholder="新目标，如：店里做到 30 个品" value={goalText} />
      <input aria-label="指标（可选）" className={styles.narrow} onChange={(event) => setMetric(event.target.value)} placeholder="指标" value={metric} />
      <input aria-label="目标值（可选）" className={styles.narrow} inputMode="decimal" onChange={(event) => setTarget(event.target.value)} placeholder="数值" value={target} />
      <button disabled={busy || goalText.trim().length < 2} type="submit">
        加目标
      </button>
    </form>
  );
}

export function OwnerControls({ office, busy, run }: { office: OfficeRead; busy: boolean; run: Runner }) {
  return (
    <section className={`${styles.section} ${styles.owner}`}>
      <div className={styles.inlineActions}>
        <PauseButton busy={busy} office={office} run={run} />
      </div>
      <InstructForm busy={busy} run={run} />
      <GoalForm busy={busy} run={run} />
    </section>
  );
}

export function GoalList({ goals, canCommand, busy, run }: { goals: OfficeGoal[]; canCommand: boolean; busy: boolean; run: Runner }) {
  return (
    <>
      {goals.length === 0 ? <p className={styles.muted}>还没有目标。</p> : null}
      <ul className={styles.list}>
        {goals.map((goal) => (
          <li key={goal.id}>
            <span>
              {goal.text}
              {goal.status === "paused" ? <em className={styles.tag}>暂停</em> : null}
            </span>
            {canCommand ? (
              <span className={styles.inlineActions}>
                <button
                  disabled={busy}
                  onClick={() => void run("调整目标失败", () => patchGoal(goal.id, { status: goal.status === "paused" ? "active" : "paused" }))}
                  type="button"
                >
                  {goal.status === "paused" ? "恢复" : "暂停"}
                </button>
                <button disabled={busy} onClick={() => void run("调整目标失败", () => patchGoal(goal.id, { status: "done" }))} type="button">
                  完成
                </button>
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </>
  );
}
