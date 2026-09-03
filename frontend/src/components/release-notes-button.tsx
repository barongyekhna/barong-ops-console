"use client";

/**
 * 顶栏的版本号按钮 —— 点开是「版本更新」抽屉。
 *
 * 按钮上直接写着当前版本号，所以它同时是两件事：版本号随时看得见，
 * 以及「这一版改了什么」的入口。
 *
 * 复用通知铃和刷新按钮共用的 `secondary-button topbar-action` 类，
 * 深色壳层已经覆盖它 —— 零新增全局 CSS。
 * 浮层复用 `OverlayModal`（portal / 焦点陷阱 / 滚动锁 / Escape / 焦点恢复
 * 全都在里面），只是换成抽屉摆位。
 */

import { Sparkles } from "lucide-react";
import { useCallback, useState } from "react";

import { OverlayModal } from "./overlay-modal";
import { RELEASE_NOTES, ReleaseNotesView } from "./release-notes";

export function ReleaseNotesButton() {
  const [isOpen, setIsOpen] = useState(false);
  // 必须 useCallback：它进 OverlayModal 的 effect 依赖，每次 render 换新引用
  // 会重挂 effect，那时滚动条已锁上，宽度补偿会算错。
  const handleClose = useCallback(() => setIsOpen(false), []);

  const current = RELEASE_NOTES[0];
  if (!current) {
    return null;
  }

  return (
    <>
      <button
        aria-expanded={isOpen}
        aria-haspopup="dialog"
        aria-label={`版本更新，当前版本 ${current.version}`}
        className="secondary-button topbar-action"
        onClick={() => setIsOpen(true)}
        title="版本更新"
        type="button"
      >
        <Sparkles aria-hidden="true" size={16} />
        v{current.version}
      </button>
      {isOpen ? (
        <OverlayModal
          label="版本更新"
          onClose={handleClose}
          placement="drawer"
        >
          <ReleaseNotesView />
        </OverlayModal>
      ) : null}
    </>
  );
}
