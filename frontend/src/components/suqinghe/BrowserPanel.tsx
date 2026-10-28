"use client";

import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type KeyboardEvent as ReactKeyboardEvent, type WheelEvent as ReactWheelEvent } from "react";

import styles from "./Office.module.css";
import { BROWSER_STATUS_LABEL, LIVE_STATUSES, VIEWPORT, isClick, isPrintable, keyFor, toViewport } from "./browser-input";
import { browserClose, browserFrameUrl, browserLogin, getBrowser, officeErrorMessage, sendBrowserInput, type BrowserStatus } from "./office-api";

const POLL_MS = 700;
const MOVE_THROTTLE_MS = 60;
const TYPE_FLUSH_MS = 300;

/**
 * 她的登录浏览器(10-28):worker 里那个 Chromium 的实时画面。1688 要验证时老板在这儿过滑块、扫码登录;
 * 画面是 worker 每 0.7 秒截的图,老板的点击/拖动/打字写进库,worker 应用到页面上。只有老板能动,别人只能看。
 */
export function BrowserPanel({ canCommand, onClose }: { canCommand: boolean; onClose: () => void }) {
  const [status, setStatus] = useState<BrowserStatus | null>(null);
  const [frameSrc, setFrameSrc] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [zoom, setZoom] = useState(false); // 10-28 扫码扫不上:原尺寸显示(1366 宽,可滚动),二维码才够大
  const imgRef = useRef<HTMLImageElement | null>(null);
  const loadingRef = useRef(false);
  const pressRef = useRef<{ x: number; y: number; sentDown: boolean } | null>(null);
  const lastMoveRef = useRef(0);
  const typeBufferRef = useRef("");
  const typeTimerRef = useRef<number | null>(null);
  const live = Boolean(status && LIVE_STATUSES.includes(status.status));

  useEffect(() => {
    let stopped = false;
    const tick = async () => {
      if (stopped || document.hidden) return;
      try {
        const next = await getBrowser(true);
        if (stopped) return;
        setStatus(next);
        if (LIVE_STATUSES.includes(next.status) && next.frame_at && !loadingRef.current) {
          loadingRef.current = true;
          setFrameSrc(browserFrameUrl());
        }
      } catch (err) {
        if (!stopped) setError(officeErrorMessage(err, "读不到浏览器状态"));
      }
    };
    void tick();
    const timer = window.setInterval(() => void tick(), POLL_MS);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, []);

  const send = useCallback(
    async (kind: Parameters<typeof sendBrowserInput>[0], payload: Record<string, unknown> = {}) => {
      if (!canCommand) return;
      try {
        await sendBrowserInput(kind, payload);
      } catch (err) {
        setError(officeErrorMessage(err, "动作没发出去"));
      }
    },
    [canCommand],
  );

  const point = (event: { clientX: number; clientY: number }) => {
    const rect = imgRef.current?.getBoundingClientRect();
    return rect ? toViewport(event.clientX, event.clientY, rect) : null;
  };

  const onPointerDown = (event: ReactPointerEvent<HTMLImageElement>) => {
    if (!canCommand || !live) return;
    const p = point(event);
    if (!p) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    pressRef.current = { ...p, sentDown: false };
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLImageElement>) => {
    const press = pressRef.current;
    if (!press || !canCommand) return;
    const p = point(event);
    if (!p) return;
    if (!press.sentDown) {
      if (isClick(press, p)) return;
      press.sentDown = true;
      void send("down", { x: press.x, y: press.y });
    }
    const now = Date.now();
    if (now - lastMoveRef.current < MOVE_THROTTLE_MS) return;
    lastMoveRef.current = now;
    void send("move", p);
  };

  const onPointerUp = (event: ReactPointerEvent<HTMLImageElement>) => {
    const press = pressRef.current;
    pressRef.current = null;
    if (!press || !canCommand) return;
    const p = point(event) ?? { x: press.x, y: press.y };
    if (press.sentDown) void send("up", p);
    else void send("click", { x: press.x, y: press.y });
  };

  const onWheel = (event: ReactWheelEvent<HTMLImageElement>) => {
    if (!canCommand || !live) return;
    const p = point(event);
    if (!p) return;
    event.preventDefault();
    void send("wheel", { ...p, dy: Math.max(-3000, Math.min(3000, event.deltaY)) });
  };

  const flushType = useCallback(() => {
    const text = typeBufferRef.current;
    typeBufferRef.current = "";
    typeTimerRef.current = null;
    if (text) void send("type", { text });
  }, [send]);

  const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (!canCommand || !live) return;
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (isPrintable(event.key)) {
      event.preventDefault();
      typeBufferRef.current += event.key;
      if (typeTimerRef.current !== null) window.clearTimeout(typeTimerRef.current);
      typeTimerRef.current = window.setTimeout(flushType, TYPE_FLUSH_MS);
      return;
    }
    const key = keyFor(event.key);
    if (!key) return;
    event.preventDefault();
    if (typeTimerRef.current !== null) {
      window.clearTimeout(typeTimerRef.current);
      flushType();
    }
    void send("key", { key });
  };

  const act = async (label: string, action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(officeErrorMessage(err, label));
    } finally {
      setBusy(false);
    }
  };

  const label = status ? (BROWSER_STATUS_LABEL[status.status] ?? status.status) : "连接中…";
  return (
    <div aria-label="她的浏览器" className={styles.browserOverlay} role="dialog">
      <div className={styles.browserHead}>
        <div>
          <strong>🖥️ 她的浏览器</strong>
          <span className={styles.browserStatus} data-status={status?.status ?? "idle"}>
            {label}
          </span>
          {status?.title ? <span className={styles.muted}> · {status.title}</span> : null}
          {status?.logged_in_at ? <span className={styles.muted}> · 已登录 1688</span> : <span className={styles.muted}> · 还没登录 1688</span>}
        </div>
        <div className={styles.browserTools}>
          <button disabled={!live} onClick={() => setZoom((z) => !z)} type="button">
            {zoom ? "缩回窗口" : "原尺寸(扫码用)"}
          </button>
          {canCommand ? (
            <>
              <button disabled={busy} onClick={() => void act("登录 1688", browserLogin)} type="button">
                登录 1688
              </button>
              <button disabled={busy || !live} onClick={() => void act("存一份页面", () => sendBrowserInput("dump"))} type="button">
                存一份页面
              </button>
              <button disabled={busy || !status || status.status === "idle"} onClick={() => void act("关掉浏览器", browserClose)} type="button">
                关掉
              </button>
            </>
          ) : null}
          <button aria-label="收起浏览器面板" className={styles.close} onClick={onClose} type="button">
            ×
          </button>
        </div>
      </div>
      {status?.reason ? <p className={styles.muted}>{status.reason}</p> : null}
      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
      <div className={styles.browserStage} data-zoom={zoom ? "1" : undefined} onKeyDown={onKeyDown} tabIndex={0}>
        {live && frameSrc ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            alt="浏览器画面"
            className={styles.browserFrame}
            draggable={false}
            height={VIEWPORT.height}
            onError={() => {
              loadingRef.current = false;
            }}
            onLoad={() => {
              loadingRef.current = false;
            }}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onWheel={onWheel}
            ref={imgRef}
            src={frameSrc}
            width={VIEWPORT.width}
          />
        ) : (
          <p className={styles.browserHint}>
            {status?.status === "fetching" ? "她正在读页面,读完这里就空了。" : "现在没有画面。1688 要验证时她会把页面留在这儿;你也可以点「登录 1688」先把账号登上。"}
          </p>
        )}
      </div>
      {live ? (
        <p className={styles.browserHint}>
          {canCommand ? "直接在画面上点、拖滑块、打字(先点一下画面让它接键盘)。扫码前先点「原尺寸」把二维码放大。过了验证她会自己接着做。" : "只有老板能操作,你可以看。"}
        </p>
      ) : null}
    </div>
  );
}
