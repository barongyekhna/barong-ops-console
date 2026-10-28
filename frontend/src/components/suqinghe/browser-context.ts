"use client";

import { createContext, useContext } from "react";

/**
 * 「打开浏览器」从哪儿都能点(收件筐里的提醒卡、列表视图的按钮、将来场景里的电脑屏幕):
 * OfficeWindow 提供这个 context,面板当覆盖层画在办公室窗口里,两种视图都能开。
 */
export type BrowserPanelControls = { open: () => void; close: () => void; isOpen: boolean };

export const BrowserPanelContext = createContext<BrowserPanelControls | null>(null);

export function useBrowserPanel(): BrowserPanelControls | null {
  return useContext(BrowserPanelContext);
}
