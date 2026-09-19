"use client";

import { sessionTokenHeaders } from "@/lib/api";
import { getFrontendRequestCacheStats } from "@/lib/request-cache";

/** RD 系列 · 建连黑匣子。
 *
 * 2026-09-18 真机首测:对方同意后,发起端再没有任何请求到达服务器,服务器侧无从知道
 * 它卡在哪一步。所以两端页面把建连的每一步**先记在本机**(localStorage),再补传到
 * `/rd/diagnostics`。网络断着就一直攒着,恢复了或下次打开页面时再传。
 *
 * 补传**故意不走 apiRequest**:那条路有全局 6 路并发排队,排队本身就是嫌疑对象之一。
 * 黑匣子得在「页面自己的请求层卡死」时也能把话传出去。
 *
 * 只记步骤、耗时、错误名和状态。**不记 SDP、不记候选地址。**
 */

const STORAGE_KEY = "barong.rd.trace.v1";
const MAX_LOCAL_ENTRIES = 600;
const MAX_BATCH = 200;
const FLUSH_INTERVAL_MS = 5_000;
const FLUSH_TIMEOUT_MS = 10_000;
const TICK_MS = 3_000;
const DIAGNOSTICS_URL = "/api/backend/rd/diagnostics";

type TraceEntry = {
  at: string;
  client_id: string;
  client_label: string;
  detail: string;
  seq: number;
  session_id: string | null;
  step: string;
};

function newClientId(): string {
  try {
    return crypto.randomUUID();
  } catch {
    const hex = () => Math.floor(Math.random() * 0x10000).toString(16).padStart(4, "0");
    return `${hex()}${hex()}-${hex()}-4${hex().slice(1)}-a${hex().slice(1)}-${hex()}${hex()}${hex()}`;
  }
}

function clientLabel(): string {
  if (typeof navigator === "undefined") {
    return "unknown";
  }
  const ua = navigator.userAgent;
  const app = /barong-ops-console-windows\/([0-9.]+)/.exec(ua);
  const chrome = /Chrome\/([0-9]+)/.exec(ua);
  const os = /Windows NT [0-9.]+|Mac OS X [0-9_]+|Android [0-9.]+|iPhone OS [0-9_]+|Linux/.exec(ua);
  return [
    app ? `client/${app[1]}` : "browser",
    chrome ? `chrome/${chrome[1]}` : null,
    os ? os[0] : null,
  ]
    .filter(Boolean)
    .join(" ")
    .slice(0, 120);
}

const CLIENT_ID = typeof window === "undefined" ? "server" : newClientId();
const CLIENT_LABEL = clientLabel();
let seq = 0;
let pending: TraceEntry[] | null = null;
let flushing = false;
let flushTimer: number | null = null;
let tickTimer: number | null = null;
let lastTickAt = 0;
let tickSessionId: string | null = null;
let installed = false;

function load(): TraceEntry[] {
  if (pending) {
    return pending;
  }
  pending = [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : [];
    if (Array.isArray(parsed)) {
      pending = parsed.filter(
        (item): item is TraceEntry =>
          typeof item === "object" &&
          item !== null &&
          typeof (item as TraceEntry).client_id === "string" &&
          typeof (item as TraceEntry).seq === "number" &&
          typeof (item as TraceEntry).step === "string",
      );
    }
  } catch {
    // 存储读不了就只在内存里攒,照样能传
  }
  return pending;
}

function persist(): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(pending ?? []));
  } catch {
    // 私密窗口 / 存储满了:内存里的还在
  }
}

function errorText(error: unknown): string {
  if (error instanceof Error) {
    return `${error.name}: ${error.message}`.slice(0, 300);
  }
  return String(error).slice(0, 300);
}

/** 记一步。detail 里放短小的键值,别放 SDP 和地址。 */
export function rdTrace(
  step: string,
  detail: Record<string, unknown> = {},
  sessionId: string | null = null,
): void {
  if (typeof window === "undefined") {
    return;
  }
  let text = "";
  try {
    text = JSON.stringify(detail).slice(0, 1000);
  } catch {
    text = "{}";
  }
  const list = load();
  seq += 1;
  list.push({
    at: new Date().toISOString(),
    client_id: CLIENT_ID,
    client_label: CLIENT_LABEL,
    detail: text,
    seq,
    session_id: sessionId,
    step: step.toLowerCase().replace(/[^a-z0-9_.:-]/g, "_").slice(0, 48),
  });
  if (list.length > MAX_LOCAL_ENTRIES) {
    list.splice(0, list.length - MAX_LOCAL_ENTRIES);
  }
  persist();
  scheduleFlush();
}

export function rdTraceError(
  step: string,
  error: unknown,
  extra: Record<string, unknown> = {},
  sessionId: string | null = null,
): void {
  rdTrace(step, { ...extra, error: errorText(error) }, sessionId);
}

/** 请求层现在排着几条——「页面自己的请求卡死」时这里会看出来。 */
export function requestQueueSnapshot(): Record<string, unknown> {
  try {
    const stats = getFrontendRequestCacheStats();
    return { active: stats.active, queued: stats.queued };
  } catch {
    return {};
  }
}

function scheduleFlush(delay = 300): void {
  if (flushTimer !== null) {
    return;
  }
  flushTimer = window.setTimeout(() => {
    flushTimer = null;
    void flushRdTraces();
  }, delay);
}

export async function flushRdTraces(keepalive = false): Promise<void> {
  if (typeof window === "undefined" || flushing) {
    return;
  }
  const list = load();
  if (list.length === 0) {
    return;
  }
  flushing = true;
  const batch = list.slice(0, MAX_BATCH);
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), FLUSH_TIMEOUT_MS);
  let retryLater = true;
  try {
    const response = await fetch(DIAGNOSTICS_URL, {
      body: JSON.stringify({ entries: batch }),
      cache: "no-store",
      credentials: "include",
      headers: { "Content-Type": "application/json", ...sessionTokenHeaders() },
      keepalive,
      method: "POST",
      signal: controller.signal,
    });
    if (response.ok) {
      const ack = (await response.json().catch(() => null)) as { stored?: unknown } | null;
      const stored = typeof ack?.stored === "number" ? ack.stored : 0;
      if (stored > 0) {
        const sent = new Set(batch.slice(0, stored).map((item) => `${item.client_id}:${item.seq}`));
        pending = load().filter((item) => !sent.has(`${item.client_id}:${item.seq}`));
        persist();
        retryLater = (pending?.length ?? 0) > 0;
      }
    } else if (response.status === 422 || response.status === 400) {
      // 这一批里有后端不认的条目:丢掉,别让一条坏数据把后面的全堵住
      const bad = new Set(batch.map((item) => `${item.client_id}:${item.seq}`));
      pending = load().filter((item) => !bad.has(`${item.client_id}:${item.seq}`));
      persist();
    }
  } catch {
    // 网络不通就攒着,下一轮再试
  } finally {
    window.clearTimeout(timer);
    flushing = false;
  }
  if (retryLater && (pending?.length ?? 0) > 0) {
    scheduleFlush(FLUSH_INTERVAL_MS);
  }
}

/** 建连期间每 3 秒记一拍。拍与拍之间的间隔明显变长 = 页面主线程卡住过。 */
export function startRdTicks(sessionId: string): void {
  tickSessionId = sessionId;
  if (tickTimer !== null) {
    return;
  }
  lastTickAt = Date.now();
  tickTimer = window.setInterval(() => {
    const now = Date.now();
    rdTrace(
      "tick",
      {
        gap_ms: now - lastTickAt,
        online: navigator.onLine,
        visible: document.visibilityState,
        ...requestQueueSnapshot(),
      },
      tickSessionId,
    );
    lastTickAt = now;
  }, TICK_MS);
}

export function stopRdTicks(): void {
  if (tickTimer !== null) {
    window.clearInterval(tickTimer);
    tickTimer = null;
  }
  tickSessionId = null;
}

/** 页面打开时装一次:上次没传完的先补传,网络恢复/页面离开时再推一把。 */
export function installRdDiagnostics(): () => void {
  if (typeof window === "undefined" || installed) {
    return () => undefined;
  }
  installed = true;
  const onOnline = () => {
    rdTrace("net_online", requestQueueSnapshot());
    void flushRdTraces();
  };
  const onOffline = () => rdTrace("net_offline", requestQueueSnapshot());
  const onHide = () => void flushRdTraces(true);
  const onError = (event: ErrorEvent) =>
    rdTrace("page_error", { error: String(event.message).slice(0, 300) });
  const onRejection = (event: PromiseRejectionEvent) =>
    rdTraceError("page_rejection", event.reason);
  window.addEventListener("online", onOnline);
  window.addEventListener("offline", onOffline);
  window.addEventListener("pagehide", onHide);
  window.addEventListener("error", onError);
  window.addEventListener("unhandledrejection", onRejection);
  rdTrace("page_open", { online: navigator.onLine, ...requestQueueSnapshot() });
  void flushRdTraces();
  return () => {
    installed = false;
    window.removeEventListener("online", onOnline);
    window.removeEventListener("offline", onOffline);
    window.removeEventListener("pagehide", onHide);
    window.removeEventListener("error", onError);
    window.removeEventListener("unhandledrejection", onRejection);
    stopRdTicks();
    void flushRdTraces(true);
  };
}
