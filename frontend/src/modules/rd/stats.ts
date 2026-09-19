"use client";

/** RD 系列 · 画面质量快照,写进黑匣子。
 *
 * 2026-09-19 真机:画面延迟高、指针一跳一跳,被控端早就打开了文件,控制端画面半天才
 * 显示。光凭「卡」看不出卡在哪:是绕了美国中转(往返延迟大)、带宽不够(码率低)、被控
 * 端 CPU 编不过来(qualityLimitationReason=cpu)、还是控制端缓冲太多(jitter buffer)。
 * 所以两端每 5 秒各记一笔,复测完直接查表。
 *
 * 只记数字和候选类型,**不记地址**。
 */

export const RD_STATS_INTERVAL_MS = 5_000;

type Counters = { at: number; bytes: number; frames: number };

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function round(value: number | null, digits = 0): number | null {
  if (value === null) {
    return null;
  }
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

/** 一次快照。`previous` 用来算这 5 秒内的实际码率。 */
export async function collectRdStats(
  pc: RTCPeerConnection,
  role: "controller" | "agent",
  previous: Counters | null,
): Promise<{ detail: Record<string, unknown>; counters: Counters | null }> {
  const report = await pc.getStats();
  const byId = new Map<string, Record<string, unknown>>();
  report.forEach((entry: Record<string, unknown>) => {
    byId.set(String(entry.id), entry);
  });

  // 实际在用的那条通路
  let pair: Record<string, unknown> | undefined;
  for (const entry of byId.values()) {
    if (entry.type === "transport" && typeof entry.selectedCandidatePairId === "string") {
      pair = byId.get(entry.selectedCandidatePairId);
    }
  }
  if (!pair) {
    for (const entry of byId.values()) {
      if (entry.type === "candidate-pair" && entry.nominated && entry.state === "succeeded") {
        pair = entry;
      }
    }
  }
  const local = pair ? byId.get(String(pair.localCandidateId)) : undefined;
  const remote = pair ? byId.get(String(pair.remoteCandidateId)) : undefined;

  const detail: Record<string, unknown> = {
    // host=局域网直连 srflx/prflx=打洞直连 relay=走中转
    path: local && remote ? `${local.candidateType}>${remote.candidateType}` : null,
    proto: local?.protocol ?? null,
    relay_proto: local?.relayProtocol ?? null,
    rtt_ms: round((num(pair?.currentRoundTripTime) ?? NaN) * 1000),
  };

  const rtpType = role === "controller" ? "inbound-rtp" : "outbound-rtp";
  let rtp: Record<string, unknown> | undefined;
  for (const entry of byId.values()) {
    if (entry.type === rtpType && entry.kind === "video") {
      rtp = entry;
    }
  }
  if (!rtp) {
    return { counters: previous, detail };
  }

  const now = num(rtp.timestamp) ?? Date.now();
  const bytes = num(role === "controller" ? rtp.bytesReceived : rtp.bytesSent) ?? 0;
  const frames = num(role === "controller" ? rtp.framesDecoded : rtp.framesEncoded) ?? 0;
  if (previous && now > previous.at) {
    const seconds = (now - previous.at) / 1000;
    detail.kbps = round(((bytes - previous.bytes) * 8) / 1000 / seconds);
    detail.fps = round((frames - previous.frames) / seconds, 1);
  }
  detail.size = `${num(rtp.frameWidth) ?? "?"}x${num(rtp.frameHeight) ?? "?"}`;

  if (role === "controller") {
    const delay = num(rtp.jitterBufferDelay);
    const emitted = num(rtp.jitterBufferEmittedCount);
    detail.jitter_buffer_ms =
      delay !== null && emitted ? round((delay / emitted) * 1000) : null;
    detail.lost = num(rtp.packetsLost);
    detail.freezes = num(rtp.freezeCount);
    detail.nack = num(rtp.nackCount);
    detail.pli = num(rtp.pliCount);
    detail.in_kbps_avail = round((num(pair?.availableIncomingBitrate) ?? NaN) / 1000);
  } else {
    // bandwidth=网不够 cpu=被控端编不过来 none=没受限
    detail.limited_by = rtp.qualityLimitationReason ?? null;
    detail.target_kbps = round((num(rtp.targetBitrate) ?? NaN) / 1000);
    detail.out_kbps_avail = round((num(pair?.availableOutgoingBitrate) ?? NaN) / 1000);
    const encodeTime = num(rtp.totalEncodeTime);
    detail.encode_ms =
      encodeTime !== null && frames ? round((encodeTime / frames) * 1000, 1) : null;
    detail.encoder = rtp.encoderImplementation ?? null;
    detail.nack = num(rtp.nackCount);
    detail.pli = num(rtp.pliCount);
  }

  return { counters: { at: now, bytes, frames }, detail };
}
