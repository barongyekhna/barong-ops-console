"use client";

import type { ReactNode } from "react";

import { formatClock, type HomeCardRead } from "./home-api";

type HomeCardShellProps = {
  card: HomeCardRead;
  title: string;
  tag?: string;
  /** 外部数据卡：右上角标「外部数据」而不是角标数字。 */
  external?: boolean;
  /** 「数据截至」后面的说明，比如「站点时区 UTC-5」。 */
  freshnessNote?: string;
  onOpen: () => void;
  children: ReactNode;
};

/** 每张卡共用的壳：标题、角标、severity 边、数据截至、点开浮窗。 */
export function HomeCardShell({
  card,
  title,
  tag,
  external = false,
  freshnessNote,
  onOpen,
  children,
}: HomeCardShellProps) {
  const count = card.count;
  const countClass =
    count === null ? "hs-count hs-count-degraded" : count === 0 ? "hs-count hs-count-zero" : "hs-count";
  return (
    <article
      aria-label={title}
      className={`hs-card hs-sev-${card.severity}`}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen();
        }
      }}
      role="button"
      tabIndex={0}
    >
      <header className="hs-card-head">
        <div className="hs-card-title">
          <strong>{title}</strong>
          {tag ? <span className="hs-tag">{tag}</span> : null}
        </div>
        {external ? (
          <span className="hs-pill hs-pill-info">外部数据</span>
        ) : (
          <span className={countClass}>{count === null ? "—" : count}</span>
        )}
      </header>
      <div className="hs-card-body">{children}</div>
      <footer className="hs-card-foot">
        <span>
          数据截至 {formatClock(card.freshness)}
          {freshnessNote ? ` · ${freshnessNote}` : ""}
        </span>
        <span className="hs-open">点开处理 ›</span>
      </footer>
    </article>
  );
}

export function HomeItemList({ card, empty }: { card: HomeCardRead; empty: string }) {
  if (card.items.length === 0) {
    return <div className="hs-empty">{empty}</div>;
  }
  return (
    <ul className="hs-list">
      {card.items.slice(0, 3).map((item) => (
        <li key={item.id}>
          <span className="hs-list-main">
            <span className="hs-list-title">{item.title}</span>
            {item.subtitle ? <span className="hs-list-sub">{item.subtitle}</span> : null}
          </span>
          <span className="hs-list-at">{formatClock(item.at)}</span>
        </li>
      ))}
    </ul>
  );
}
