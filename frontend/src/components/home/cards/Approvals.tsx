"use client";

import { useState } from "react";

import { approveApproval, rejectApproval } from "@/lib/approval";
import { markNotificationRead } from "@/modules/notifications/api";

import { formatDateTime, type HomeCardItem } from "../home-api";
import { HomeCardShell, HomeItemList } from "../HomeCardShell";
import { withoutItem, type HomeCardProps, type HomeDrawerProps } from "../home-types";

function numbers(card: HomeCardProps["card"]) {
  const approvals = card.extra.approvals;
  return {
    approvals: typeof approvals === "number" ? approvals : null,
    unread: typeof card.extra.unread === "number" ? card.extra.unread : 0,
    degraded: card.extra.approvals_degraded === true,
    capped: card.extra.approvals_capped === true,
  };
}

export function ApprovalsCard({ card, onOpen }: HomeCardProps) {
  const { approvals, unread, degraded, capped } = numbers(card);
  const approvalsLabel = approvals === null ? (degraded ? "审批暂不可用" : "无审批权") : `待批 ${approvals}${capped ? "+" : ""}`;
  return (
    <HomeCardShell card={card} onOpen={onOpen} tag={`${approvalsLabel} · 未读 ${unread}`} title="审批与通知">
      <HomeItemList card={card} empty="没有等你点头的事。" />
    </HomeCardShell>
  );
}

function Row({
  item,
  canDecide,
  patchCard,
  refetchCard,
  notify,
}: { item: HomeCardItem; canDecide: boolean } & Pick<HomeDrawerProps, "patchCard" | "refetchCard" | "notify">) {
  const [busy, setBusy] = useState(false);
  const isApproval = item.title.startsWith("审批");

  const run = async (action: () => Promise<unknown>, done: string, failed: string) => {
    if (busy) return;
    setBusy(true);
    try {
      await action();
      patchCard((card) => withoutItem(card, item.id));
      notify(done);
    } catch {
      notify(failed);
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
        {isApproval && canDecide ? (
          <>
            <button
              className="hs-btn hs-btn-primary"
              disabled={busy}
              onClick={() => void run(() => approveApproval(item.id), "已通过", "通过失败，去审批模块看原因")}
              type="button"
            >
              通过
            </button>
            <button
              className="hs-btn"
              disabled={busy}
              onClick={() =>
                void run(() => rejectApproval(item.id, "主页浮窗驳回"), "已驳回", "驳回失败，去审批模块看原因")
              }
              type="button"
            >
              驳回
            </button>
          </>
        ) : null}
        {!isApproval ? (
          <button
            className="hs-btn"
            disabled={busy}
            onClick={() => void run(() => markNotificationRead(Number(item.id)), "已读", "标记失败")}
            type="button"
          >
            已读
          </button>
        ) : null}
        {isApproval && !canDecide ? <span className="hs-muted">这条要在审批模块里决定。</span> : null}
      </div>
    </div>
  );
}

export function ApprovalsDrawer({ card, patchCard, refetchCard, notify }: HomeDrawerProps) {
  const { approvals, unread, degraded } = numbers(card);
  const canDecide = card.actions.includes("approve");
  return (
    <div className="hs-drawer-body">
      <div className="hs-kpis hs-kpis-3">
        <div className="hs-kpi"><b>{approvals === null ? "—" : approvals}</b><span>待批审批</span></div>
        <div className="hs-kpi"><b>{unread}</b><span>未读通知</span></div>
        <div className="hs-kpi"><b>{degraded ? "!" : "✓"}</b><span>{degraded ? "审批列表超时，稍后再试" : "审批列表正常"}</span></div>
      </div>
      {card.items.length === 0 ? (
        <div className="hs-empty">没有等你点头的事。</div>
      ) : (
        card.items.map((item) => (
          <Row
            canDecide={canDecide}
            item={item}
            key={item.id}
            notify={notify}
            patchCard={patchCard}
            refetchCard={refetchCard}
          />
        ))
      )}
    </div>
  );
}
