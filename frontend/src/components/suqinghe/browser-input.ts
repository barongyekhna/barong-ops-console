/**
 * 「浏览器」面板的纯函数(10-28):把老板在缩略画面上的动作换算成 worker 那边 1366×900 视口的坐标、
 * 判一下按下抬起是点还是拖、键盘事件映射成后端认的键名。node 测试直接验。
 */

export const VIEWPORT = { width: 1366, height: 900 } as const;

export type BrowserInputKind = "click" | "down" | "move" | "up" | "type" | "key" | "wheel" | "navigate" | "dump";

export type BrowserStatusKind = "idle" | "fetching" | "needs_human" | "interactive" | "asking_seller" | string;

export const BROWSER_STATUS_LABEL: Record<string, string> = {
  idle: "空着",
  fetching: "她在读 1688 页面",
  needs_human: "1688 要验证,等你过一下",
  interactive: "等你扫码登录 1688",
  asking_seller: "她在问卖家",
};

/** 这些状态下 worker 才截图:面板也只在这时候拉画面。 */
export const LIVE_STATUSES: readonly string[] = ["needs_human", "interactive", "asking_seller"];

export type Rect = { left: number; top: number; width: number; height: number };

/** 画面是等比缩放显示的;超出画面(或画面还没量到尺寸)就不发。 */
export function toViewport(clientX: number, clientY: number, rect: Rect): { x: number; y: number } | null {
  if (rect.width <= 0 || rect.height <= 0) return null;
  const x = ((clientX - rect.left) / rect.width) * VIEWPORT.width;
  const y = ((clientY - rect.top) / rect.height) * VIEWPORT.height;
  if (x < 0 || y < 0 || x > VIEWPORT.width || y > VIEWPORT.height) return null;
  return { x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10 };
}

/** 按下和抬起离得很近 = 一下点击;远了 = 拖(滑块)。 */
export function isClick(down: { x: number; y: number }, up: { x: number; y: number }, threshold = 3): boolean {
  return Math.hypot(up.x - down.x, up.y - down.y) < threshold;
}

const KEY_MAP: Record<string, string> = {
  Enter: "Enter",
  Backspace: "Backspace",
  Tab: "Tab",
  Escape: "Escape",
  Delete: "Delete",
  ArrowLeft: "ArrowLeft",
  ArrowRight: "ArrowRight",
  ArrowUp: "ArrowUp",
  ArrowDown: "ArrowDown",
  Home: "Home",
  End: "End",
};

/** KeyboardEvent.key → 后端白名单里的键名;可打印字符走 type,这里返回 null。 */
export function keyFor(key: string): string | null {
  if (key === " ") return "Space";
  return KEY_MAP[key] ?? null;
}

export function isPrintable(key: string): boolean {
  return key.length === 1 && key !== " ";
}
