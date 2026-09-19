"use client";

import { getRdIceConfig, pushRdSignal, withRdRetry } from "./api";
import { rdTrace, rdTraceError, requestQueueSnapshot } from "./diagnostics";
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

/** 点完同意之后,多久画面还没通就认定这次失败、主动收场。
 *
 * 不设这个,对方的 answer 一直不来时 RTCPeerConnection 会永远停在 new,页面就
 * 永远挂着「连接中」。比后端的握手超时(90 秒)短,好让前端先把话说清楚。
 */
export const RD_HANDSHAKE_TIMEOUT_MS = 45_000;

/** 失败时告诉人卡在哪一步,别只有一句「连接失败」。 */
export type RdFailureStage = "local" | "signal" | "no_answer" | "ice";

export type RdControllerHandlers = {
  onStream: (stream: MediaStream) => void;
  onPhase: (phase: RdConnectionPhase, detail?: string) => void;
  onFailed: (stage: RdFailureStage) => void;
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
  private answered = false;
  private watchdog: number | null = null;

  constructor(sessionId: string, handlers: RdControllerHandlers) {
    this.sessionId = sessionId;
    this.handlers = handlers;
  }

  private trace(step: string, detail: Record<string, unknown> = {}): void {
    rdTrace(`ctl.${step}`, detail, this.sessionId);
  }

  async start(): Promise<void> {
    this.trace("start", requestQueueSnapshot());
    this.watchdog = window.setTimeout(() => {
      if (this.closed || this.pc?.connectionState === "connected") {
        return;
      }
      this.trace("watchdog", {
        answered: this.answered,
        conn: this.pc?.connectionState ?? null,
        ice: this.pc?.iceConnectionState ?? null,
        ...requestQueueSnapshot(),
      });
      this.fail(this.answered ? "ice" : "no_answer");
    }, RD_HANDSHAKE_TIMEOUT_MS);

    let config;
    try {
      config = await withRdRetry(
        () => getRdIceConfig(this.sessionId),
        () => this.closed,
        { sessionId: this.sessionId, step: "ctl.ice_config" },
      );
    } catch {
      this.fail("signal");
      return;
    }
    if (this.closed) {
      return;
    }
    const iceServers = toIceServers(config);
    this.trace("pc_create", {
      servers: iceServers.map((server) =>
        (Array.isArray(server.urls) ? server.urls : [server.urls])
          .map((url) => url.split(":")[0])
          .join(","),
      ),
    });
    let pc: RTCPeerConnection;
    try {
      pc = new RTCPeerConnection({ iceServers });
    } catch (error) {
      rdTraceError("ctl.pc_create_fail", error, {}, this.sessionId);
      this.fail("local");
      return;
    }
    this.pc = pc;
    this.trace("pc_created");

    pc.addTransceiver("video", { direction: "recvonly" });
    const input = pc.createDataChannel("input", { ordered: true });
    this.input = input;

    pc.ontrack = (event) => {
      const [stream] = event.streams;
      if (stream) {
        this.handlers.onStream(stream);
      }
    };

    pc.onicegatheringstatechange = () =>
      this.trace("gathering", { state: pc.iceGatheringState });
    pc.oniceconnectionstatechange = () =>
      this.trace("ice_state", { state: pc.iceConnectionState });
    pc.onicecandidate = (event) => {
      if (event.candidate && !this.closed) {
        // 只记类型和协议,不记地址
        this.trace("cand_local", {
          protocol: event.candidate.protocol,
          type: event.candidate.type,
        });
        const candidate = JSON.stringify(event.candidate.toJSON());
        void withRdRetry(
          () => pushRdSignal(this.sessionId, "ice", candidate),
          () => this.closed,
          { sessionId: this.sessionId, step: "ctl.cand_post" },
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
      this.trace("conn_state", { state });
      if (state === "connected") {
        this.clearWatchdog();
        this.handlers.onPhase("connected");
      } else if (state === "failed") {
        this.fail("ice");
      } else if (state === "disconnected" || state === "closed") {
        this.handlers.onPhase("closed");
      }
    };

    this.handlers.onPhase("negotiating");
    let offer: RTCSessionDescriptionInit;
    try {
      const startedAt = Date.now();
      offer = await pc.createOffer();
      this.trace("offer_created", { ms: Date.now() - startedAt });
      await pc.setLocalDescription(offer);
      this.trace("local_set", { ms: Date.now() - startedAt });
    } catch (error) {
      rdTraceError("ctl.offer_create_fail", error, {}, this.sessionId);
      this.fail("local");
      return;
    }
    if (this.closed) {
      return;
    }
    try {
      await withRdRetry(
        () => pushRdSignal(this.sessionId, "offer", JSON.stringify(offer)),
        () => this.closed,
        { sessionId: this.sessionId, step: "ctl.offer_post" },
      );
    } catch {
      this.fail("signal");
    }
  }

  private fail(stage: RdFailureStage): void {
    if (this.closed) {
      return;
    }
    this.clearWatchdog();
    this.trace("fail", { stage, ...requestQueueSnapshot() });
    this.handlers.onFailed(stage);
  }

  private clearWatchdog(): void {
    if (this.watchdog !== null) {
      window.clearTimeout(this.watchdog);
      this.watchdog = null;
    }
  }

  /** 收到对方递来的信封。SSE 那边收一条就喂一条进来。 */
  async accept(kind: string, payload: string): Promise<void> {
    const pc = this.pc;
    if (!pc || this.closed) {
      return;
    }
    if (kind === "answer") {
      // 同一场只认第一个 answer。重复的(流重开时重放、对方重试)再喂进去会把
      // 已经稳定的连接状态打乱
      if (this.answered) {
        return;
      }
      this.answered = true;
      this.trace("answer_received");
      const description = JSON.parse(payload) as RTCSessionDescriptionInit;
      try {
        await pc.setRemoteDescription(description);
      } catch (error) {
        rdTraceError("ctl.remote_set_fail", error, {}, this.sessionId);
        throw error;
      }
      this.trace("remote_set");
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
    this.trace("close", { conn: this.pc?.connectionState ?? null });
    this.closed = true;
    this.clearWatchdog();
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
