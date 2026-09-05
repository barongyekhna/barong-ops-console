"use client";

import { useState } from "react";

import { patchDraft } from "@/modules/b2b/outreach/api";

import { formatDateTime, type HomeCardItem } from "../home-api";
import { HomeCardShell, HomeItemList } from "../HomeCardShell";
import { withoutItem, type HomeCardProps, type HomeDrawerProps } from "../home-types";

/**
 * 开发信浮窗只有「看」和「驳回」。发送永远不在主页发生——这里没有、也不会有
 * 任何发送控件；家规「系统永不自动发送」在浮窗里同样成立。
 */

function bounceLine(card: HomeCardProps["card"]) {
  const rate = card.extra.bounce_rate;
  const sent = typeof card.extra.sent === "number" ? card.extra.sent : 0;
  if (typeof rate !== "number") return { text: `退信率 — · 已发 ${sent} 封`, tone: "ok" as const };
  const pct = (rate * 100).toFixed(1);
  const tone = rate >= 0.03 ? ("bad" as const) : rate >= 0.025 ? ("warn" as const) : ("ok" as const);
  return { text: `退信率 ${pct}% · 红线 3%`, tone };
}

export function B2bDraftsCard({ card, onOpen }: HomeCardProps) {
  const bounce = bounceLine(card);
  return (
    <HomeCardShell card={card} onOpen={onOpen} tag="待人工审核" title="B2B 开发信待审">
      <HomeItemList card={card} empty="没有等审的草稿。" />
      <div className="hs-inline">
        <span className="hs-muted">{bounce.text}</span>
        <span className={`hs-pill hs-pill-${bounce.tone}`}>
          {bounce.tone === "ok" ? "安全" : bounce.tone === "warn" ? "逼近红线" : "越线"}
        </span>
      </div>
    </HomeCardShell>
  );
}

function DraftRow({
  item,
  patchCard,
  refetchCard,
  notify,
}: { item: HomeCardItem } & Pick<HomeDrawerProps, "patchCard" | "refetchCard" | "notify">) {
  const [busy, setBusy] = useState(false);
  const skip = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await patchDraft(item.id, { status: "skipped" });
      patchCard((card) => withoutItem(card, item.id));
      notify("已驳回，这封不会再出现");
    } catch {
      notify("驳回失败，去 B2B 模块处理");
      await refetchCard();
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="hs-item">
      <div className="hs-item-head">
        <span>{item.title}</span>
        <span className="hs-muted">{formatDateTime(item.at)}</span>
      </div>
      <p className="hs-item-sub">{item.subtitle}</p>
      <div className="hs-item-actions">
        <button className="hs-btn" disabled={busy} onClick={skip} type="button">
          驳回
        </button>
        <span className="hs-pill hs-pill-warn">发送永不在浮窗里</span>
      </div>
    </div>
  );
}

export function B2bDraftsDrawer({ card, patchCard, refetchCard, notify }: HomeDrawerProps) {
  const bounce = bounceLine(card);
  return (
    <div className="hs-drawer-body">
      <div className="hs-inline">
        <span>{bounce.text}</span>
        <span className={`hs-pill hs-pill-${bounce.tone}`}>
          {bounce.tone === "ok" ? "安全" : bounce.tone === "warn" ? "逼近红线" : "越线"}
        </span>
      </div>
      {card.items.length === 0 ? (
        <div className="hs-empty">没有等审的草稿。</div>
      ) : (
        card.items.map((item) => (
          <DraftRow item={item} key={item.id} notify={notify} patchCard={patchCard} refetchCard={refetchCard} />
        ))
      )}
    </div>
  );
}
