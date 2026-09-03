"use client";

/**
 * 对外动作的二次确认。
 *
 * 为什么需要（2026-08-31 体检）：全站有九个「会真的对外产生后果」的按钮
 * ——客服「发送回复」（邮件发出即不可撤回）、GEO/SEO 发布（写 WordPress）、
 * H 跳转规则整表覆盖、W-S 运费同步到 Woo、B2B 重推产品页 —— 全部是
 * onClick 直连，没有任何确认、没有预览。
 *
 * 客服那条最凶：当时客服中心里 4 条消息有 2 条是 SEO 垃圾推销，误点回复
 * 等于向垃圾发送方确认 service@ 是活邮箱。
 *
 * 全站唯一做对的是 H 的「SMTP 体检」（WpBridgePanels.tsx），这个组件就是
 * 把那个做法抽出来复用。
 *
 * 刻意**不用** window.confirm：它是浏览器灰框，说不清「会影响什么」，
 * 阻塞主线程，而且某些浏览器设置下会被直接屏蔽 —— 那样操作会静默发生。
 */

import { Fragment, useEffect, useRef } from "react";

/**
 * 把 `**这样**` 渲染成粗体。
 *
 * 这些文案里最该被看见的就是「不可撤回」「整表覆盖」「直接写入线上」这几个词。
 * 而这套代码有个反复出现的毛病：文案里写了 markdown 记号，渲染时却按纯文本
 * 输出，界面上直接冒出字面星号（体检时数出七处）。所以这里给它一个真的渲染。
 */
function renderEmphasis(text: string) {
  return text.split(/\*\*(.+?)\*\*/g).map((part, index) =>
    index % 2 === 1 ? (
      <strong key={index}>{part}</strong>
    ) : (
      <Fragment key={index}>{part}</Fragment>
    ),
  );
}

export type OutboundConfirmProps = {
  /** 标题：一句话说清「要做什么」。 */
  title: string;
  /** 后果：说清「会影响什么」「能不能撤回」。这是这个弹层存在的理由。 */
  consequence: string;
  /** 影响范围的具体条目（发几篇、覆盖几条规则、发给谁）。有就列出来。 */
  details?: string[];
  confirmLabel?: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

export function OutboundConfirm({
  title,
  consequence,
  details,
  confirmLabel = "确认执行",
  busy = false,
  onConfirm,
  onCancel,
}: OutboundConfirmProps) {
  const cancelRef = useRef<HTMLButtonElement | null>(null);

  // 焦点落在「取消」上：对外动作的默认选择应该是「不做」。
  useEffect(() => {
    cancelRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) {
        onCancel();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onCancel]);

  return (
    <div className="outbound-confirm-backdrop" role="presentation">
      <div
        aria-labelledby="outbound-confirm-title"
        aria-modal="true"
        className="outbound-confirm-dialog"
        role="dialog"
      >
        <h3 id="outbound-confirm-title">{title}</h3>
        <p className="outbound-confirm-consequence">{renderEmphasis(consequence)}</p>
        {details && details.length > 0 ? (
          <ul className="outbound-confirm-details">
            {details.slice(0, 8).map((item) => (
              <li key={item}>{renderEmphasis(item)}</li>
            ))}
            {details.length > 8 ? <li>…共 {details.length} 项</li> : null}
          </ul>
        ) : null}
        <div className="outbound-confirm-actions">
          <button
            className="secondary-button"
            disabled={busy}
            onClick={onCancel}
            ref={cancelRef}
            type="button"
          >
            取消
          </button>
          <button
            className="primary-button"
            disabled={busy}
            onClick={onConfirm}
            type="button"
          >
            {busy ? "执行中…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
