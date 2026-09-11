"use client";

import { getRdIceConfig, pushRdSignal } from "./api";
import { encodeInputEvent, type RdInputEvent } from "./input-protocol";
import { toIceServers } from "./types";

/** RD 系列 · 控制端(浏览器)这一侧的 WebRTC。
 *
 * 分工:**控制端发 offer,被控端回 answer**。控制端只收画面不发画面,所以视频收发
 * 器是 `recvonly`;键鼠反过来由控制端经数据通道发出去。这样被控端不用主动发起,
 * 它只要坐着等就行——一台没人守的车间机器正该是这个姿势。
 *
 * ICE 是 trickle 的:candidate 一个个随到随发,不等收集完。跨太平洋那条线收集完
 * 可能要好几秒,等齐了再发就是白白多等。
 */

export type RdConnectionPhase =
  | "idle"
  | "negotiating"
  | "connected"
  | "failed"
  | "closed";

export type RdControllerHandlers = {
  onStream: (stream: MediaStream) => void;
  onPhase: (phase: RdConnectionPhase, detail?: string) => void;
};

export class RdController {
  private pc: RTCPeerConnection | null = null;
  private input: RTCDataChannel | null = null;
  private readonly sessionId: string;
  private readonly handlers: RdControllerHandlers;
  private closed = false;
  /** 对方的 answer 还没来之前收到的 candidate 先存着,不能直接喂进去。 */
  private pendingRemoteCandidates: RTCIceCandidateInit[] = [];
  private remoteDescriptionSet = false;

  constructor(sessionId: string, handlers: RdControllerHandlers) {
    this.sessionId = sessionId;
    this.handlers = handlers;
  }

  async start(): Promise<void> {
    const config = await getRdIceConfig(this.sessionId);
    const pc = new RTCPeerConnection({ iceServers: toIceServers(config) });
    this.pc = pc;

    pc.addTransceiver("video", { direction: "recvonly" });
    const input = pc.createDataChannel("input", { ordered: true });
    this.input = input;

    pc.ontrack = (event) => {
      const [stream] = event.streams;
      if (stream) {
        this.handlers.onStream(stream);
      }
    };

    pc.onicecandidate = (event) => {
      if (event.candidate && !this.closed) {
        void pushRdSignal(
          this.sessionId,
          "ice",
          JSON.stringify(event.candidate.toJSON()),
        ).catch(() => {
          // 单条 candidate 发失败不该弄垮整条连接,ICE 本来就是尽力而为
        });
      }
    };

    pc.onconnectionstatechange = () => {
      if (this.closed) {
        return;
      }
      const state = pc.connectionState;
      if (state === "connected") {
        this.handlers.onPhase("connected");
      } else if (state === "failed") {
        this.handlers.onPhase("failed", "通路没打通。");
      } else if (state === "disconnected" || state === "closed") {
        this.handlers.onPhase("closed");
      }
    };

    this.handlers.onPhase("negotiating");
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    await pushRdSignal(this.sessionId, "offer", JSON.stringify(offer));
  }

  /** 收到对方递来的信封。SSE 那边收一条就喂一条进来。 */
  async accept(kind: string, payload: string): Promise<void> {
    const pc = this.pc;
    if (!pc || this.closed) {
      return;
    }
    if (kind === "answer") {
      const description = JSON.parse(payload) as RTCSessionDescriptionInit;
      await pc.setRemoteDescription(description);
      this.remoteDescriptionSet = true;
      // answer 到了才能把之前攒着的 candidate 喂进去
      for (const candidate of this.pendingRemoteCandidates) {
        await pc.addIceCandidate(candidate).catch(() => undefined);
      }
      this.pendingRemoteCandidates = [];
      return;
    }
    if (kind === "ice") {
      const candidate = JSON.parse(payload) as RTCIceCandidateInit;
      if (!this.remoteDescriptionSet) {
        this.pendingRemoteCandidates.push(candidate);
        return;
      }
      await pc.addIceCandidate(candidate).catch(() => undefined);
    }
  }

  send(event: RdInputEvent): void {
    const channel = this.input;
    if (!channel || channel.readyState !== "open" || this.closed) {
      return;
    }
    try {
      channel.send(encodeInputEvent(event));
    } catch {
      // 通道正在关就算了,别把异常抛给 UI
    }
  }

  get inputReady(): boolean {
    return this.input?.readyState === "open";
  }

  close(): void {
    if (this.closed) {
      return;
    }
    this.closed = true;
    try {
      this.input?.close();
    } catch {
      // 关闭时的异常一律吞掉
    }
    try {
      this.pc?.close();
    } catch {
      // 同上
    }
    this.input = null;
    this.pc = null;
  }
}
