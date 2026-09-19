"use client";

import { getRdIceConfig, pushRdSignal, withRdRetry } from "./api";
import { rdTrace, rdTraceError } from "./diagnostics";
import { parseInputEvent } from "./input-protocol";
import type { RdNativeBridge } from "./native";
import { toIceServers } from "./types";

/** RD 系列 · 被控端这一侧的 WebRTC。
 *
 * 分工和控制端相反:这边**只发画面不收画面**,收到 offer 才动作,答完就等着。键鼠从
 * 数据通道进来,逐条验形之后交给原生桥去注入——**没验过的一条都不往下递**,因为往下
 * 递的结果是在别人电脑上真的按下去。
 *
 * 屏幕不是这里要来的:`getDisplayMedia` 给不给,由主进程按「有没有一场已同意的会话」
 * 决定。这边拿不到就是拿不到,没有别的路。
 */

export type RdAgentHandlers = {
  onEnded: (reason: string) => void;
  onLive: () => void;
};

export class RdAgent {
  private pc: RTCPeerConnection | null = null;
  private stream: MediaStream | null = null;
  private readonly sessionId: string;
  private readonly bridge: RdNativeBridge;
  private readonly handlers: RdAgentHandlers;
  private closed = false;
  private pendingRemoteCandidates: RTCIceCandidateInit[] = [];
  private remoteDescriptionSet = false;
  private droppedInputs = 0;
  private offerTaken = false;

  constructor(
    sessionId: string,
    bridge: RdNativeBridge,
    handlers: RdAgentHandlers,
  ) {
    this.sessionId = sessionId;
    this.bridge = bridge;
    this.handlers = handlers;
  }

  private trace(step: string, detail: Record<string, unknown> = {}): void {
    rdTrace(`agt.${step}`, detail, this.sessionId);
  }

  /** 收到对方递来的信封。offer 到了才真正开始抓屏。 */
  async accept(kind: string, payload: string): Promise<void> {
    if (this.closed) {
      return;
    }
    if (kind === "offer") {
      // 一场只答一次。第二个 offer(流重开重放 / 对方重试)要是也答,就会再抓一次
      // 屏、再建一条连接,把正在用的那条挤掉
      if (this.offerTaken) {
        return;
      }
      this.offerTaken = true;
      this.trace("offer_received");
      try {
        await this.answer(JSON.parse(payload) as RTCSessionDescriptionInit);
      } catch (error) {
        rdTraceError("agt.answer_fail", error, {}, this.sessionId);
        // 抓屏被拒 / answer 送不出去:这场就算失败,收摊并把红条撤掉,
        // 不能让被控机顶着「正在被远程」一直挂着
        if (!this.closed) {
          this.handlers.onEnded("connection_lost");
        }
      }
      return;
    }
    if (kind === "ice") {
      const candidate = JSON.parse(payload) as RTCIceCandidateInit;
      if (!this.remoteDescriptionSet || !this.pc) {
        this.pendingRemoteCandidates.push(candidate);
        return;
      }
      await this.pc.addIceCandidate(candidate).catch(() => undefined);
    }
  }

  private async answer(offer: RTCSessionDescriptionInit): Promise<void> {
    const config = await withRdRetry(
      () => getRdIceConfig(this.sessionId),
      () => this.closed,
      { sessionId: this.sessionId, step: "agt.ice_config" },
    );
    const pc = new RTCPeerConnection({ iceServers: toIceServers(config) });
    this.pc = pc;
    this.trace("pc_created");
    pc.onicegatheringstatechange = () =>
      this.trace("gathering", { state: pc.iceGatheringState });
    pc.oniceconnectionstatechange = () =>
      this.trace("ice_state", { state: pc.iceConnectionState });

    pc.onicecandidate = (event) => {
      if (event.candidate && !this.closed) {
        this.trace("cand_local", {
          protocol: event.candidate.protocol,
          type: event.candidate.type,
        });
        const candidate = JSON.stringify(event.candidate.toJSON());
        void withRdRetry(
          () => pushRdSignal(this.sessionId, "ice", candidate),
          () => this.closed,
          { sessionId: this.sessionId, step: "agt.cand_post" },
        ).catch(() => undefined);
      }
    };

    pc.ondatachannel = (event) => {
      if (event.channel.label !== "input") {
        // 只认这一条通道,别的一律不理
        event.channel.close();
        return;
      }
      event.channel.onmessage = (message) => {
        const parsed = parseInputEvent(message.data);
        if (!parsed) {
          this.droppedInputs += 1;
          return;
        }
        void this.bridge.input(parsed).catch(() => undefined);
      };
    };

    pc.onconnectionstatechange = () => {
      if (this.closed) {
        return;
      }
      this.trace("conn_state", { state: pc.connectionState });
      if (pc.connectionState === "connected") {
        this.handlers.onLive();
      } else if (
        pc.connectionState === "failed" ||
        pc.connectionState === "disconnected"
      ) {
        this.handlers.onEnded("connection_lost");
      }
    };

    // 屏幕由主进程决定给不给,这里拿不到就直接收摊
    this.trace("capture_start");
    const stream = await navigator.mediaDevices.getDisplayMedia({
      audio: false,
      video: true,
    });
    this.trace("capture_ok", { tracks: stream.getTracks().length });
    this.stream = stream;
    for (const track of stream.getTracks()) {
      // 被控的人从系统里自己停掉共享,也要当成挂断
      track.addEventListener("ended", () => this.handlers.onEnded("agent_kicked"));
      pc.addTrack(track, stream);
    }

    await pc.setRemoteDescription(offer);
    this.remoteDescriptionSet = true;
    for (const candidate of this.pendingRemoteCandidates) {
      await pc.addIceCandidate(candidate).catch(() => undefined);
    }
    this.pendingRemoteCandidates = [];

    const description = await pc.createAnswer();
    await pc.setLocalDescription(description);
    this.trace("answer_created");
    const answer = JSON.stringify(description);
    await withRdRetry(
      () => pushRdSignal(this.sessionId, "answer", answer),
      () => this.closed,
      { sessionId: this.sessionId, step: "agt.answer_post" },
    );
  }

  /** 对方的 offer 到过没有。被控端的看门狗靠它判断「同意之后对方到底来没来」。 */
  get hasOffer(): boolean {
    return this.offerTaken;
  }

  get droppedInputCount(): number {
    return this.droppedInputs;
  }

  close(): void {
    if (this.closed) {
      return;
    }
    this.trace("close", { conn: this.pc?.connectionState ?? null });
    this.closed = true;
    for (const track of this.stream?.getTracks() ?? []) {
      try {
        track.stop();
      } catch {
        // 关闭时的异常一律吞掉
      }
    }
    try {
      this.pc?.close();
    } catch {
      // 同上
    }
    this.stream = null;
    this.pc = null;
  }
}
