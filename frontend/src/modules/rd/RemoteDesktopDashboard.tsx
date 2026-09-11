"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { DashboardScene } from "@/components/dashboard-scene";
import { useAuth } from "@/components/auth-provider";
import { c19SseReconnectDelay } from "@/modules/c19/C19EventStreamRecovery";

import { RdAgent } from "./agent";
import {
  RD_STREAM_PATH,
  activateRdSession,
  endRdSession,
  heartbeatRdDevice,
  listRdDevices,
  listRdSessions,
  registerRdDevice,
  requestRdSession,
  respondRdSession,
  setRdUnattended,
} from "./api";
import { getRdNativeBridge, type RdNativeBridge } from "./native";
import { RemoteViewer } from "./RemoteViewer";
import {
  deviceStatusLabel,
  normalizeRdSession,
  platformLabel,
  type RdDevice,
  type RdSession,
} from "./types";
import { RdController, type RdConnectionPhase } from "./webrtc";

/** RD 系列 · 远程桌面主面板。一个页面同时扮演两个角色。
 *
 * **控制端**:任何浏览器都能当。发起请求、收画面、把键鼠发过去。
 *
 * **被控端**:只有装了控制台客户端的机器才能当,因为抓屏和注入键鼠要本机权限。这
 * 一侧几乎不做决定——同意框是原生的、由主进程弹并由主进程直接回报给控制台;屏幕
 * 给不给也是主进程说了算。网页在这条路上只负责搬运 WebRTC 的信封。
 *
 * 所以这个页面里**没有任何一个「同意」按钮**,而且不该有。网页上的同意按钮能被脚本
 * 点掉,那样「人必须在机器跟前」这条保证就作废了。人不在机器跟前又想长期放行,正确
 * 做法是把那台机器标成公用机。
 */

const DEVICE_POLL_MS = 15_000;
const HEARTBEAT_MS = 30_000;

export function RemoteDesktopDashboard() {
  const { user } = useAuth();

  const [devices, setDevices] = useState<RdDevice[]>([]);
  const [ledger, setLedger] = useState<RdSession[]>([]);
  const [incoming, setIncoming] = useState<RdSession[]>([]);
  const [session, setSession] = useState<RdSession | null>(null);
  const [phase, setPhase] = useState<RdConnectionPhase>("idle");
  const [notice, setNotice] = useState<string | null>(null);
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [selfDevice, setSelfDevice] = useState<RdDevice | null>(null);
  const [nativeReason, setNativeReason] = useState<string | null>(null);

  const controllerRef = useRef<RdController | null>(null);
  const agentRef = useRef<RdAgent | null>(null);
  const bridgeRef = useRef<RdNativeBridge | null>(null);
  const selfDeviceIdRef = useRef<string | null>(null);
  const sessionRef = useRef<RdSession | null>(null);
  sessionRef.current = session;

  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const [nextDevices, nextLedger] = await Promise.all([
        listRdDevices(signal),
        listRdSessions(signal),
      ]);
      setDevices(nextDevices);
      setLedger(nextLedger);
      const selfId = selfDeviceIdRef.current;
      if (selfId) {
        setSelfDevice(nextDevices.find((item) => item.id === selfId) ?? null);
      }
    } catch {
      // 刷新失败保留上一份数据,不要把列表清空成一片白
    }
  }, []);

  // ---- 这台机器自己登记上来(只有客户端里跑才有这一步) ----
  useEffect(() => {
    const bridge = getRdNativeBridge();
    bridgeRef.current = bridge;
    if (!bridge) {
      return undefined;
    }
    let timer: number | null = null;
    let stopped = false;

    void (async () => {
      try {
        const status = await bridge.status();
        if (!status.available) {
          setNativeReason(
            `这台机器暂时不能被远程操控：${status.reason ?? "键鼠组件未能加载"}。`,
          );
          return;
        }
        const registered = await registerRdDevice({
          agent_version: "0.4.0",
          device_uuid: status.device_uuid,
          name: status.device_name,
          platform: status.platform,
        });
        if (stopped) {
          return;
        }
        selfDeviceIdRef.current = registered.id;
        setSelfDevice(registered);
        const beat = () => {
          void heartbeatRdDevice(registered.id, "0.4.0").catch(() => undefined);
        };
        beat();
        timer = window.setInterval(beat, HEARTBEAT_MS);
      } catch {
        setNativeReason("这台机器没能登记到远程桌面，刷新页面再试一次。");
      }
    })();

    return () => {
      stopped = true;
      if (timer !== null) {
        window.clearInterval(timer);
      }
    };
  }, []);

  useEffect(() => {
    const abort = new AbortController();
    void refresh(abort.signal);
    const timer = window.setInterval(() => void refresh(), DEVICE_POLL_MS);
    return () => {
      abort.abort();
      window.clearInterval(timer);
    };
  }, [refresh]);

  const teardown = useCallback(() => {
    controllerRef.current?.close();
    controllerRef.current = null;
    agentRef.current?.close();
    agentRef.current = null;
    setStream(null);
    setPhase("idle");
    setSession(null);
  }, []);

  const hangUp = useCallback(
    async (reason: "controller_left" | "connection_lost") => {
      const current = sessionRef.current;
      teardown();
      if (current) {
        try {
          await endRdSession(current.id, reason);
        } catch {
          // 台账那边收不收得到都不该拦着本地断开
        }
      }
      void refresh();
    },
    [refresh, teardown],
  );

  const beginMedia = useCallback(
    async (target: RdSession) => {
      const controller = new RdController(target.id, {
        onPhase: (next, detail) => {
          setPhase(next);
          if (detail) {
            setNotice(detail);
          }
          if (next === "connected") {
            void activateRdSession(target.id).catch(() => undefined);
            void refresh();
          }
          if (next === "failed") {
            void hangUp("connection_lost");
          }
        },
        onStream: (incomingStream) => setStream(incomingStream),
      });
      controllerRef.current = controller;
      try {
        await controller.start();
      } catch {
        setNotice("建立连接失败。");
        void hangUp("connection_lost");
      }
    },
    [hangUp, refresh],
  );

  /** 被控端:开始交出屏幕。主进程已经批准(或已自行核实)过了才会走到这。 */
  const beginAgent = useCallback(
    (sessionId: string) => {
      const bridge = bridgeRef.current;
      if (!bridge || agentRef.current) {
        return;
      }
      agentRef.current = new RdAgent(sessionId, bridge, {
        onEnded: () => {
          agentRef.current?.close();
          agentRef.current = null;
          void bridge.stop().catch(() => undefined);
          void refresh();
        },
        onLive: () => {
          void activateRdSession(sessionId).catch(() => undefined);
          void refresh();
        },
      });
    },
    [refresh],
  );

  // ---- SSE:有人要连我 / 会话状态变了 / 对方递来信令 ----
  useEffect(() => {
    let source: EventSource | null = null;
    let failures = 0;
    let retry: number | null = null;
    let stopped = false;

    const open = () => {
      if (stopped) {
        return;
      }
      source = new EventSource(RD_STREAM_PATH, { withCredentials: true });
      source.onopen = () => {
        failures = 0;
      };

      source.addEventListener("request", (event) => {
        const parsed = normalizeRdSession(
          JSON.parse((event as MessageEvent<string>).data),
        );
        if (!parsed) {
          return;
        }
        const bridge = bridgeRef.current;
        if (bridge && parsed.device_id === selfDeviceIdRef.current) {
          // 弹的是主进程的原生框。同意与否由主进程直接回报给控制台，网页
          // 不经手，也无从声称。
          void bridge
            .consent({
              requesterName:
                parsed.controller_name ?? `用户 ${parsed.controller_user_id}`,
              sessionId: parsed.id,
            })
            .then((result) => {
              if (result.approved) {
                beginAgent(parsed.id);
              }
              void refresh();
            })
            .catch(() => undefined);
          return;
        }
        // 不在被控机上：只能看见和拒绝
        setIncoming((prev) =>
          prev.some((item) => item.id === parsed.id) ? prev : [...prev, parsed],
        );
      });

      source.addEventListener("session", (event) => {
        const parsed = normalizeRdSession(
          JSON.parse((event as MessageEvent<string>).data),
        );
        if (!parsed) {
          return;
        }
        setIncoming((prev) =>
          parsed.state === "requested"
            ? prev
            : prev.filter((item) => item.id !== parsed.id),
        );

        // 被控端：免同意的会话主进程没亲手批准过，让它自己去后端核实一次
        const bridge = bridgeRef.current;
        if (
          bridge &&
          parsed.device_id === selfDeviceIdRef.current &&
          parsed.state === "consented" &&
          parsed.consent_mode === "unattended" &&
          !agentRef.current
        ) {
          void bridge
            .beginUnattended({ sessionId: parsed.id })
            .then((result) => {
              if (result.approved) {
                beginAgent(parsed.id);
              }
            })
            .catch(() => undefined);
          return;
        }

        const current = sessionRef.current;
        if (!current || current.id !== parsed.id) {
          void refresh();
          return;
        }
        setSession(parsed);
        if (parsed.state === "denied") {
          setNotice("对方拒绝了这次请求。");
          teardown();
        } else if (parsed.state === "expired") {
          setNotice("对方一直没有回应，请求已经超时。");
          teardown();
        } else if (parsed.state === "ended") {
          setNotice("会话已经结束。");
          teardown();
        } else if (parsed.state === "consented" && !controllerRef.current) {
          void beginMedia(parsed);
        }
        void refresh();
      });

      source.addEventListener("signal", (event) => {
        const data = JSON.parse((event as MessageEvent<string>).data) as {
          session_id: string;
          kind: string;
          payload: string;
        };
        const agent = agentRef.current;
        if (agent) {
          void agent.accept(data.kind, data.payload).catch(() => undefined);
          return;
        }
        const current = sessionRef.current;
        if (current && current.id === data.session_id) {
          void controllerRef.current?.accept(data.kind, data.payload);
        }
      });

      source.onerror = () => {
        source?.close();
        source = null;
        if (stopped) {
          return;
        }
        failures += 1;
        retry = window.setTimeout(open, c19SseReconnectDelay(failures));
      };
    };

    open();
    return () => {
      stopped = true;
      if (retry !== null) {
        window.clearTimeout(retry);
      }
      source?.close();
    };
  }, [beginAgent, beginMedia, refresh, teardown]);

  const connect = useCallback(
    async (device: RdDevice) => {
      setNotice(null);
      if (device.id === selfDeviceIdRef.current) {
        setNotice("这就是你正坐在前面的这台机器，不用远程。");
        return;
      }
      try {
        const created = await requestRdSession(device.id);
        setSession(created);
        sessionRef.current = created;
        if (created.state === "consented") {
          await beginMedia(created);
        } else {
          setPhase("negotiating");
          setNotice(`已经向「${device.name}」发出请求，等对方在那台机器上确认。`);
        }
        void refresh();
      } catch (error) {
        setNotice(error instanceof Error ? error.message : "发起失败。");
      }
    },
    [beginMedia, refresh],
  );

  const deny = useCallback(
    async (target: RdSession) => {
      try {
        await respondRdSession(target.id, false);
      } catch {
        setNotice("拒绝没有成功，请重试。");
      }
      setIncoming((prev) => prev.filter((item) => item.id !== target.id));
      void refresh();
    },
    [refresh],
  );

  const toggleUnattended = useCallback(async () => {
    const bridge = bridgeRef.current;
    const device = selfDevice;
    if (!bridge || !device) {
      return;
    }
    try {
      const result = await bridge.markUnattended({
        deviceId: device.id,
        enabled: !device.is_unattended,
      });
      if (!result.confirmed) {
        return;
      }
      void refresh();
    } catch {
      // 主进程那边弹框没确认或接口失败，状态不动就是了
      setNotice("公用机设置没有生效。");
    }
  }, [refresh, selfDevice]);

  const myDevices = useMemo(
    () => devices.filter((device) => device.is_mine),
    [devices],
  );
  const otherDevices = useMemo(
    () => devices.filter((device) => !device.is_mine),
    [devices],
  );

  return (
    <div className="dashboard-page cc-dash cc-rd">
      <DashboardScene />

      <header className="cc-head">
        <div>
          <h1>远程桌面</h1>
          <p className="cc-rd-sub">
            连别人的机器一律要对方在那台机器上点同意；连你自己的机器直接进。
          </p>
        </div>
        <button className="cc-rd-ghost" onClick={() => void refresh()} type="button">
          刷新
        </button>
      </header>

      {notice ? <p className="cc-rd-notice">{notice}</p> : null}
      {nativeReason ? <p className="cc-rd-notice">{nativeReason}</p> : null}

      {incoming.length > 0 ? (
        <section className="cc-card cc-rd-incoming">
          <h2>有人要控制你的机器</h2>
          <p className="cc-rd-sub">
            同意要在那台机器上的弹框里点。人不在机器跟前又想长期放行，就把它标成公用机。
          </p>
          <ul className="cc-rd-list">
            {incoming.map((item) => (
              <li key={item.id}>
                <span>
                  {item.controller_name ?? `用户 ${item.controller_user_id}`}
                  {" 请求控制 "}
                  {item.device_name ?? "你的机器"}
                </span>
                <button className="cc-rd-danger" onClick={() => void deny(item)} type="button">
                  拒绝
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {stream && session ? (
        <RemoteViewerMount
          controller={controllerRef.current}
          deviceName={session.device_name ?? "远程机器"}
          onEnd={() => void hangUp("controller_left")}
          stream={stream}
        />
      ) : null}

      {selfDevice ? (
        <section className="cc-card">
          <h2>这台机器</h2>
          <ul className="cc-rd-list">
            <li>
              <span className="cc-rd-name">{selfDevice.name}</span>
              <span className="cc-rd-meta">{platformLabel(selfDevice.platform)}</span>
              <span className="cc-rd-online">可被远程</span>
              {selfDevice.is_unattended ? <span className="cc-rd-tag">公用机</span> : null}
              <button className="cc-rd-ghost" onClick={() => void toggleUnattended()} type="button">
                {selfDevice.is_unattended ? "取消公用机" : "设为公用机"}
              </button>
            </li>
          </ul>
          <p className="cc-rd-sub">
            公用机是给车间、前台这种没人值守的机器用的：名单里的人连它不再弹同意框。
            设置时会在这台机器上再确认一次。
          </p>
        </section>
      ) : null}

      <section className="cc-card">
        <h2>我的机器</h2>
        {myDevices.length === 0 ? (
          <p className="cc-rd-empty">
            还没有机器登记上来。在那台电脑上打开控制台客户端并登录，它会自己出现。
          </p>
        ) : (
          <DeviceTable devices={myDevices} disabled={session !== null} onConnect={connect} />
        )}
      </section>

      <section className="cc-card">
        <h2>其他人的机器</h2>
        {otherDevices.length === 0 ? (
          <p className="cc-rd-empty">暂时没有别人的机器在线。</p>
        ) : (
          <DeviceTable devices={otherDevices} disabled={session !== null} onConnect={connect} />
        )}
      </section>

      <section className="cc-card">
        <h2>操控台账</h2>
        <p className="cc-rd-sub">谁在什么时候连过谁，所有人都查得到。</p>
        <ul className="cc-rd-ledger">
          {ledger.slice(0, 30).map((item) => (
            <li key={item.id}>
              <span className={`cc-rd-state cc-rd-state-${item.state}`}>
                {stateLabel(item.state)}
              </span>
              <span>
                {item.controller_name ?? `用户 ${item.controller_user_id}`}
                {" → "}
                {item.device_name ?? "已删除的机器"}
              </span>
              <span className="cc-rd-time">
                {formatTime(item.started_at ?? item.requested_at)}
              </span>
              {item.consent_mode === "unattended" ? (
                <span className="cc-rd-tag">免同意</span>
              ) : null}
            </li>
          ))}
        </ul>
      </section>

      <p className="cc-rd-foot">
        当前登录：{user?.username ?? "—"}
        {phase === "idle" ? "" : ` · 连接状态 ${phase}`}
      </p>
    </div>
  );
}

function RemoteViewerMount({
  controller,
  deviceName,
  onEnd,
  stream,
}: {
  controller: RdController | null;
  deviceName: string;
  onEnd: () => void;
  stream: MediaStream;
}) {
  const holder = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const video = holder.current?.querySelector("video");
    if (video) {
      video.srcObject = stream;
    }
  }, [stream]);

  if (!controller) {
    return null;
  }
  return (
    <div ref={holder}>
      <RemoteViewer controller={controller} deviceName={deviceName} onEnd={onEnd} />
    </div>
  );
}

function DeviceTable({
  devices,
  disabled,
  onConnect,
}: {
  devices: RdDevice[];
  disabled: boolean;
  onConnect: (device: RdDevice) => void;
}) {
  return (
    <ul className="cc-rd-list">
      {devices.map((device) => (
        <li key={device.id}>
          <span className="cc-rd-name">{device.name}</span>
          <span className="cc-rd-meta">{platformLabel(device.platform)}</span>
          <span className="cc-rd-meta">
            {device.owner_name ?? `用户 ${device.owner_user_id}`}
          </span>
          <span className={device.is_online ? "cc-rd-online" : "cc-rd-offline"}>
            {deviceStatusLabel(device)}
          </span>
          {device.is_unattended ? <span className="cc-rd-tag">公用机</span> : null}
          <button
            className="cc-rd-primary"
            disabled={disabled || !device.is_online || device.busy}
            onClick={() => onConnect(device)}
            type="button"
          >
            {device.needs_consent ? "请求控制" : "直接连接"}
          </button>
        </li>
      ))}
    </ul>
  );
}

function stateLabel(state: RdSession["state"]): string {
  const labels: Record<RdSession["state"], string> = {
    active: "进行中",
    consented: "已同意",
    denied: "被拒绝",
    ended: "已结束",
    expired: "已超时",
    requested: "等待确认",
  };
  return labels[state];
}

function formatTime(value: string): string {
  if (!value) {
    return "—";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "—";
  }
  return parsed.toLocaleString("zh-CN", { hour12: false });
}
