"use client";

import { useState } from "react";

import { sendCSReply, updateCSMessage } from "@/modules/cs/customer-service/api";

import { formatDateTime, type HomeCardItem } from "../home-api";
import { HomeCardShell, HomeItemList } from "../HomeCardShell";
import { withoutItem, type HomeCardProps, type HomeDrawerProps } from "../home-types";

export function CsInboxCard({ card, onOpen }: HomeCardProps) {
  const retail = typeof card.extra.retail === "number" ? card.extra.retail : 0;
  const wholesale = typeof card.extra.wholesale === "number" ? card.extra.wholesale : 0;
  return (
    <HomeCardShell card={card} onOpen={onOpen} tag={`零售 ${retail} · 批发 ${wholesale}`} title="客服新消息">
      <HomeItemList card={card} empty="没有待回复的消息。" />
    </HomeCardShell>
  );
}

function ReplyBox({
  item,
  patchCard,
  refetchCard,
  notify,
}: { item: HomeCardItem } & Pick<HomeDrawerProps, "patchCard" | "refetchCard" | "notify">) {
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);

  const reply = async () => {
    if (!body.trim() || busy) return;
    setBusy(true);
    try {
      await sendCSReply(item.id, body.trim());
      patchCard((card) => withoutItem(card, item.id));
      notify("已回复，客服卡 3 秒内刷新");
    } catch {
      notify("回复没发出去，去客服模块看原因");
      await refetchCard();
    } finally {
      setBusy(false);
    }
  };

  const resolve = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await updateCSMessage(item.id, { status: "resolved", internal_note: null });
      patchCard((card) => withoutItem(card, item.id));
      notify("已标为处理完");
    } catch {
      notify("标记失败，去客服模块处理");
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
      <textarea
        aria-label={`回复 ${item.title}`}
        className="hs-reply"
        onChange={(event) => setBody(event.target.value)}
        placeholder="直接在这里回…"
        value={body}
      />
      <div className="hs-item-actions">
        <button className="hs-btn hs-btn-primary" disabled={busy || !body.trim()} onClick={reply} type="button">
          回复
        </button>
        <button className="hs-btn" disabled={busy} onClick={resolve} type="button">
          标已处理
        </button>
      </div>
    </div>
  );
}

export function CsInboxDrawer({ card, patchCard, refetchCard, notify }: HomeDrawerProps) {
  if (card.items.length === 0) {
    return <div className="hs-empty">没有待回复的消息。</div>;
  }
  return (
    <div className="hs-drawer-body">
      {card.items.map((item) => (
        <ReplyBox item={item} key={item.id} notify={notify} patchCard={patchCard} refetchCard={refetchCard} />
      ))}
      {typeof card.count === "number" && card.count > card.items.length ? (
        <p className="hs-muted">还有 {card.count - card.items.length} 条，去客服模块看全部。</p>
      ) : null}
    </div>
  );
}
