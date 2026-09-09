"use client";

import { Check, Copy } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { copyText } from "@/lib/clipboard";

import styles from "./C19Workspace.module.css";
import { type ParsedCategoryCard } from "./c19CategoryCard";

export { parseC19CategoryCard, type ParsedCategoryCard } from "./c19CategoryCard";

/**
 * 殷承岳的「类目卡」:英文类目名大字 + 一键复制,路径 / 中文 / 原因,备选各带复制按钮。
 * 文本本身就是可读的(见 c19CategoryCard.ts),这里只是把它渲染得更好用。
 */

function CopyChip({ value, title }: { value: string; title: string }) {
  const [state, setState] = useState<"idle" | "copied" | "manual">("idle");
  const timerRef = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    },
    [],
  );

  async function handleCopy() {
    const ok = await copyText(value);
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    if (!ok) {
      window.prompt(title, value);
      setState("manual");
      timerRef.current = window.setTimeout(() => setState("idle"), 2200);
      return;
    }
    setState("copied");
    timerRef.current = window.setTimeout(() => setState("idle"), 1400);
  }

  return (
    <button
      aria-label={`复制 ${value}`}
      className={styles.categoryCopyChip}
      data-copied={state === "copied" ? "true" : "false"}
      onClick={() => void handleCopy()}
      title={state === "copied" ? "已复制" : title}
      type="button"
    >
      {state === "copied" ? <Check aria-hidden="true" size={13} /> : <Copy aria-hidden="true" size={13} />}
      <span>{state === "copied" ? "已复制" : state === "manual" ? "手动复制" : "复制"}</span>
    </button>
  );
}

export function C19CategoryCard({ card }: { card: ParsedCategoryCard }) {
  return (
    <>
      {card.preface ? <p>{card.preface}</p> : null}
      <div className={styles.categoryCard}>
        <header className={styles.categoryCardHead}>
          <span className={styles.categoryCardKicker}>谷歌类目</span>
          {card.confidence ? (
            <span className={styles.categoryCardConfidence}>置信 {card.confidence}</span>
          ) : null}
        </header>
        <div className={styles.categoryCardLeafRow}>
          <strong className={styles.categoryCardLeaf} title={card.leafName}>
            {card.leafName}
          </strong>
          <CopyChip title="复制英文类目名" value={card.leafName} />
        </div>
        {card.path.length > 0 ? (
          <p className={styles.categoryCardPath} title={card.path.join(" > ")}>
            {card.path.join(" › ")}
          </p>
        ) : null}
        <dl className={styles.categoryCardMeta}>
          {card.nameZh ? (
            <>
              <dt>中文</dt>
              <dd>{card.nameZh}</dd>
            </>
          ) : null}
          {card.reason ? (
            <>
              <dt>原因</dt>
              <dd>{card.reason}</dd>
            </>
          ) : null}
        </dl>
        {card.alternates.length > 0 ? (
          <ul className={styles.categoryCardAlts}>
            {card.alternates.map((alt) => (
              <li key={alt.name}>
                <span className={styles.categoryCardAltName}>{alt.name}</span>
                <CopyChip title="复制备选类目名" value={alt.name} />
                {alt.reason ? <small>{alt.reason}</small> : null}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </>
  );
}
