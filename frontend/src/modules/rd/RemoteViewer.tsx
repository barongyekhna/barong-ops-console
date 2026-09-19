"use client";

import { useCallback, useEffect, useRef } from "react";

import { rdTrace } from "./diagnostics";
import { normalizePointer, videoContentRect } from "./input-protocol";
import type { RdController } from "./webrtc";

/** RD 系列 · 画面窗口 + 键鼠捕获。
 *
 * 这个组件只做两件事:把远端画面放出来,把这块区域里的键鼠动作转成归一化事件发出
 * 去。它不碰会话状态,也不碰网络——断开、重连、台账都在上层。
 *
 * 键盘监听挂在 window 上而不是元素上:要接住 Tab、方向键这些会被浏览器抢走的键,
 * 只能在捕获阶段拦。但**只在鼠标进到画面里之后才拦**,否则用户想用 Tab 切控制台
 * 自己的表单都切不动了。
 */

type Props = {
  controller: RdController;
  deviceName: string;
  onEnd: () => void;
};

export function RemoteViewer({ controller, deviceName, onEnd }: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const engagedRef = useRef(false);
  // 鼠标移动按屏幕刷新合并:一帧只发最后一个位置。高回报率鼠标一秒能报几百次,
  // 全发出去只会在对面排队,指针越拖越远
  const pendingMoveRef = useRef<{ x: number; y: number } | null>(null);
  const frameRef = useRef<number | null>(null);

  const pointerFrom = useCallback(
    (event: { clientX: number; clientY: number }) => {
      const element = videoRef.current;
      if (!element) {
        return { x: 0, y: 0 };
      }
      // 按画面本身(去掉黑边)换算,不按整个 <video> 框
      const rect = videoContentRect(
        element.getBoundingClientRect(),
        element.videoWidth,
        element.videoHeight,
      );
      return normalizePointer(event, rect);
    },
    [],
  );

  const flushMove = useCallback(() => {
    frameRef.current = null;
    const move = pendingMoveRef.current;
    pendingMoveRef.current = null;
    if (move) {
      controller.send({ t: "m", x: move.x, y: move.y });
    }
  }, [controller]);

  const handlePointerMove = useCallback(
    (event: React.PointerEvent<HTMLVideoElement>) => {
      pendingMoveRef.current = pointerFrom(event);
      if (frameRef.current === null) {
        frameRef.current = window.requestAnimationFrame(flushMove);
      }
    },
    [flushMove, pointerFrom],
  );

  /** 按键/松键前先把还没发的移动发掉,保证点击落在最新位置之后 */
  const dropPendingMove = useCallback(() => {
    if (frameRef.current !== null) {
      window.cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    }
    pendingMoveRef.current = null;
  }, []);

  const handlePointerDown = useCallback(
    (event: React.PointerEvent<HTMLVideoElement>) => {
      event.preventDefault();
      dropPendingMove();
      const { x, y } = pointerFrom(event);
      controller.send({ b: event.button, t: "d", x, y });
    },
    [controller, dropPendingMove, pointerFrom],
  );

  const handlePointerUp = useCallback(
    (event: React.PointerEvent<HTMLVideoElement>) => {
      event.preventDefault();
      dropPendingMove();
      const { x, y } = pointerFrom(event);
      controller.send({ b: event.button, t: "u", x, y });
    },
    [controller, dropPendingMove, pointerFrom],
  );

  useEffect(
    () => () => {
      if (frameRef.current !== null) {
        window.cancelAnimationFrame(frameRef.current);
      }
    },
    [],
  );

  // 画面尺寸一出来记一笔:下次复测能从黑匣子里看出框和画面比例差多少
  const handleLoadedMetadata = useCallback(() => {
    const element = videoRef.current;
    if (!element) {
      return;
    }
    const box = element.getBoundingClientRect();
    const rect = videoContentRect(box, element.videoWidth, element.videoHeight);
    rdTrace("viewer_geometry", {
      box: [Math.round(box.width), Math.round(box.height)],
      picture: [Math.round(rect.width), Math.round(rect.height)],
      remote: [element.videoWidth, element.videoHeight],
    });
  }, []);

  const handleWheel = useCallback(
    (event: React.WheelEvent<HTMLVideoElement>) => {
      controller.send({ dx: event.deltaX, dy: event.deltaY, t: "w" });
    },
    [controller],
  );

  const handleContextMenu = useCallback(
    (event: React.MouseEvent<HTMLVideoElement>) => {
      // 右键要发到对面去,不该弹出浏览器自己的菜单
      event.preventDefault();
    },
    [],
  );

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (!engagedRef.current) {
        return;
      }
      // Esc 是本地逃生键:任何时候按都能松开控制,不发给对面
      if (event.key === "Escape") {
        engagedRef.current = false;
        return;
      }
      event.preventDefault();
      const code = event.code.replace(/[^A-Za-z0-9]/g, "");
      if (code.length === 0) {
        return;
      }
      controller.send({ c: code, d: event.type === "keydown", t: "k" });
    }
    window.addEventListener("keydown", onKey, true);
    window.addEventListener("keyup", onKey, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      window.removeEventListener("keyup", onKey, true);
    };
  }, [controller]);

  return (
    <div className="cc-rd-viewer">
      <div className="cc-rd-viewer-bar">
        <span className="cc-rd-viewer-name">{deviceName}</span>
        <span className="cc-rd-viewer-hint">
          鼠标移进画面即可操作，按 Esc 松开键盘
        </span>
        <button className="cc-rd-danger" onClick={onEnd} type="button">
          断开
        </button>
      </div>
      <video
        autoPlay
        className="cc-rd-video"
        muted
        onContextMenu={handleContextMenu}
        onLoadedMetadata={handleLoadedMetadata}
        onPointerDown={handlePointerDown}
        onPointerEnter={() => {
          engagedRef.current = true;
        }}
        onPointerLeave={() => {
          engagedRef.current = false;
        }}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onWheel={handleWheel}
        playsInline
        ref={videoRef}
      />
    </div>
  );
}
