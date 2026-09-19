"use client";

/** RD 系列 · 键鼠事件在数据通道上的编码。
 *
 * **坐标一律归一化成 0~1**,不发像素。控制端的窗口多大、被控端屏幕多少分辨率,
 * 两边根本不需要知道对方的数字——被控端拿到 0.5/0.5 就往自己屏幕正中间点。用像
 * 素的话,换个显示器或者缩放比例一改就全错位,而且错得很隐蔽。
 *
 * 字段名压到一个字母:鼠标移动每秒能发几十条,这条通道上省下来的都是延迟。
 */

export type RdInputEvent =
  | { t: "m"; x: number; y: number }
  | { t: "d"; b: number; x: number; y: number }
  | { t: "u"; b: number; x: number; y: number }
  | { t: "w"; dx: number; dy: number }
  | { t: "k"; c: string; d: boolean }
  | { t: "s"; s: string };

function clamp01(value: number): number {
  if (!Number.isFinite(value)) {
    return 0;
  }
  if (value < 0) {
    return 0;
  }
  if (value > 1) {
    return 1;
  }
  return value;
}

/** 把浏览器里 <video> 上的一次指针事件翻成归一化坐标。 */
export function normalizePointer(
  event: { clientX: number; clientY: number },
  rect: { left: number; top: number; width: number; height: number },
): { x: number; y: number } {
  if (rect.width <= 0 || rect.height <= 0) {
    return { x: 0, y: 0 };
  }
  return {
    x: clamp01((event.clientX - rect.left) / rect.width),
    y: clamp01((event.clientY - rect.top) / rect.height),
  };
}

/** 画面在 <video> 框里真正占的那一块(去掉黑边)。
 *
 * <video> 默认 object-fit: contain:框的比例和对面屏幕不一样时,画面居中、两侧或上下
 * 留黑边。坐标要按画面本身算,按整个框算的话越靠边偏得越多——2026-09-19 真机:
 * 「我鼠标放哪,对面鼠标并不在哪」。还没拿到画面尺寸时退回整个框。
 */
export function videoContentRect(
  box: { left: number; top: number; width: number; height: number },
  videoWidth: number,
  videoHeight: number,
): { left: number; top: number; width: number; height: number } {
  if (
    !(videoWidth > 0) ||
    !(videoHeight > 0) ||
    !(box.width > 0) ||
    !(box.height > 0)
  ) {
    return box;
  }
  const scale = Math.min(box.width / videoWidth, box.height / videoHeight);
  const width = videoWidth * scale;
  const height = videoHeight * scale;
  return {
    height,
    left: box.left + (box.width - width) / 2,
    top: box.top + (box.height - height) / 2,
    width,
  };
}

/** 收到的事件必须逐个验形。被控端照着它注入键鼠,信错一条就是乱点别人电脑。 */
export function parseInputEvent(raw: unknown): RdInputEvent | null {
  if (typeof raw !== "string") {
    return null;
  }
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null) {
    return null;
  }
  const event = value as Record<string, unknown>;
  const kind = event.t;
  if (kind === "m") {
    if (typeof event.x !== "number" || typeof event.y !== "number") {
      return null;
    }
    return { t: "m", x: clamp01(event.x), y: clamp01(event.y) };
  }
  if (kind === "d" || kind === "u") {
    if (
      typeof event.b !== "number" ||
      typeof event.x !== "number" ||
      typeof event.y !== "number" ||
      event.b < 0 ||
      event.b > 2
    ) {
      return null;
    }
    return {
      b: Math.trunc(event.b),
      t: kind,
      x: clamp01(event.x),
      y: clamp01(event.y),
    };
  }
  if (kind === "w") {
    if (typeof event.dx !== "number" || typeof event.dy !== "number") {
      return null;
    }
    return { dx: event.dx, dy: event.dy, t: "w" };
  }
  if (kind === "k") {
    if (typeof event.c !== "string" || typeof event.d !== "boolean") {
      return null;
    }
    // 键名只认字母数字,挡掉拿这个字段往下游命令里塞东西的路
    if (!/^[A-Za-z0-9]{1,32}$/.test(event.c)) {
      return null;
    }
    return { c: event.c, d: event.d, t: "k" };
  }
  if (kind === "s") {
    if (typeof event.s !== "string" || event.s.length === 0 || event.s.length > 1024) {
      return null;
    }
    return { s: event.s, t: "s" };
  }
  return null;
}

export function encodeInputEvent(event: RdInputEvent): string {
  return JSON.stringify(event);
}
