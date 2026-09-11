"use client";

import { useCallback, useEffect, useRef } from "react";

import { normalizePointer } from "./input-protocol";
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

  const pointerFrom = useCallback(
    (event: { clientX: number; clientY: number }) => {
      const element = videoRef.current;
      if (!element) {
        return { x: 0, y: 0 };
      }
      return normalizePointer(event, element.getBoundingClientRect());
    },
    [],
  );

  const handlePointerMove = useCallback(
    (event: React.PointerEvent<HTMLVideoElement>) => {
      const { x, y } = pointerFrom(event);
      controller.send({ t: "m", x, y });
    },
    [controller, pointerFrom],
  );

  const handlePointerDown = useCallback(
    (event: React.PointerEvent<HTMLVideoElement>) => {
      event.preventDefault();
      const { x, y } = pointerFrom(event);
      controller.send({ b: event.button, t: "d", x, y });
    },
    [controller, pointerFrom],
  );

  const handlePointerUp = useCallback(
    (event: React.PointerEvent<HTMLVideoElement>) => {
      event.preventDefault();
      const { x, y } = pointerFrom(event);
      controller.send({ b: event.button, t: "u", x, y });
    },
    [controller, pointerFrom],
  );

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
