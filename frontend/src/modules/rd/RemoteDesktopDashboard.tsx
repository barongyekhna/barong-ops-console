"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { DashboardScene } from "@/components/dashboard-scene";
import { useAuth } from "@/components/auth-provider";
import { c19SseReconnectDelay } from "@/modules/c19/C19EventStreamRecovery";

import { RdAgent } from "./agent";
import {
  installRdDiagnostics,
  rdTrace,
  rdTraceError,
  requestQueueSnapshot,
  startRdTicks,
  stopRdTicks,
} from "./diagnostics";
import {
  activateRdSession,
  endRdSession,
  heartbeatRdDevice,
  listRdDevices,
  listRdSessions,
  registerRdDevice,
  requestRdSession,
  rdStreamUrl,
  respondRdSession,
  withRdRetry,
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
import {
  RD_HANDSHAKE_TIMEOUT_MS,
  RdController,
  type RdConnectionPhase,
  type RdFailureStage,
} from "./webrtc";

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
const TERMINAL_STATES: ReadonlySet<string> = new Set(["denied", "expired", "ended"]);

/** 失败要说清楚卡在哪一步——「连接失败」四个字没法据此做任何事。 */
function failureNotice(stage: RdFailureStage): string {
  if (stage === "local") {
    return "连接没建起来：这台电脑上的浏览器组件没能准备好连接。关掉客户端重开再试；反复不成请告诉管理员。";
  }
  if (stage === "signal") {
    return "连接没建起来：这台电脑的请求没能送到服务器（网络中断或连接卡住）。直接再点一次；还不行就关掉客户端重开。";
  }
  if (stage === "no_answer") {
    return "连接没建起来：对方同意了，但那台电脑一直没回应握手。请对方确认控制台客户端开着、网络正常，再点一次。";
  }
  return "连接没建起来：两台电脑之间的通路没打通（直连和中转都没成）。可以再试一次；反复不成请把这句话发给管理员。";
}

/** 结束的回报也要送到——送不到的话被控机会被一条死会话占住。 */
function reportEnd(
  sessionId: string,
  reason: "controller_left" | "agent_kicked" | "connection_lost",
): Promise<void> {
  return withRdRetry(() => endRdSession(sessionId, reason), undefined, {
    sessionId,
    step: "end_post",
  }).catch(() => undefined);
}

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
  /** 被控端这一侧正在服务的会话。和控制端的 session 分开记,两个身份可以同时成立。 */
  const agentSessionIdRef = useRef<string | null>(null);
  const agentWatchdogRef = useRef<number | null>(null);
  /** 已经弹过原生同意框的会话。流 55 秒重开一次会把还没答的请求再推一遍,不能弹第二个框。 */
  const promptedRef = useRef<Set<string>>(new Set());
  /** 已经收到的最后一条信令 id:重开流时带上,后端就不重放。 */
  const lastSignalIdRef = useRef(0);
  const seenSignalIdsRef = useRef<Set<number>>(new Set());
  const bridgeRef = useRef<RdNativeBridge | null>(null);
  const selfDeviceIdRef = useRef<string | null>(null);
  const sessionRef = useRef<RdSession | null>(null);
  sessionRef.current = session;

  const onTerminalRef = useRef<((item: RdSession) => void) | null>(null);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const [nextDevices, nextLedger] = await Promise.all([
        listRdDevices(signal),
        listRdSessions(signal),
      ]);
      setDevices(nextDevices);
      setLedger(nextLedger);
      // SSE 万一漏了「结束了」这一条,台账是兜底:自己正挂着的会话在台账上已经是终态,
      // 就地收摊
      const byId = new Map(nextLedger.map((item) => [item.id, item]));
      const mine = sessionRef.current;
      const mineNow = mine ? byId.get(mine.id) : undefined;
      if (mineNow && TERMINAL_STATES.has(mineNow.state)) {
        onTerminalRef.current?.(mineNow);
      }
      const agentId = agentSessionIdRef.current;
      const agentNow = agentId ? byId.get(agentId) : undefined;
      if (agentNow && TERMINAL_STATES.has(agentNow.state)) {
        onTerminalRef.current?.(agentNow);
      }
      const selfId = selfDeviceIdRef.current;
      if (selfId) {
        setSelfDevice(nextDevices.find((item) => item.id === selfId) ?? null);
      }
    } catch (error) {
      // 刷新失败保留上一份数据,不要把列表清空成一片白
      if (!signal?.aborted) {
        rdTraceError("refresh_fail", error, requestQueueSnapshot());
      }
    }
  }, []);

  // ---- 黑匣子:上次没传完的先补传,之后每一步都先记本地再传 ----
  useEffect(() => installRdDiagnostics(), []);

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
        rdTrace("device_registered", { device_id: registered.id });
        const beat = () => {
          void heartbeatRdDevice(registered.id, "0.4.0").catch((error) =>
            rdTraceError("heartbeat_fail", error, requestQueueSnapshot()),
          );
        };
        beat();
        timer = window.setInterval(beat, HEARTBEAT_MS);
      } catch (error) {
        rdTraceError("device_register_fail", error);
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
    if (!agentRef.current) {
      stopRdTicks();
    }
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
      rdTrace("hang_up", { reason }, current?.id ?? null);
      teardown();
      if (current) {
        // 台账那边收不收得到都不该拦着本地断开;但要尽力送到,否则对方机器被占住
        await reportEnd(current.id, reason);
      }
      void refresh();
    },
    [refresh, teardown],
  );

  const beginMedia = useCallback(
    async (target: RdSession) => {
      rdTrace("begin_media", { state: target.state }, target.id);
      startRdTicks(target.id);
      const controller = new RdController(target.id, {
        onPhase: (next, detail) => {
          setPhase(next);
          if (detail) {
            setNotice(detail);
          }
          if (next === "connected") {
            void withRdRetry(() => activateRdSession(target.id)).catch(
              () => undefined,
            );
            void refresh();
          }
        },
        onFailed: (stage) => {
          rdTrace("notice_failed", { stage }, target.id);
          setNotice(failureNotice(stage));
          void hangUp("connection_lost");
        },
        onStream: (incomingStream) => setStream(incomingStream),
      });
      controllerRef.current = controller;
      try {
        await controller.start();
      } catch (error) {
        rdTraceError("begin_media_throw", error, {}, target.id);
        setNotice(failureNotice("local"));
        void hangUp("connection_lost");
      }
    },
    [hangUp, refresh],
  );

  /** 被控端:收摊。先把结束原因报上去,再让主进程撤红条、收回屏幕和键鼠。 */
  const stopAgent = useCallback(
    (reason: "agent_kicked" | "connection_lost" | null) => {
      const sessionId = agentSessionIdRef.current;
      rdTrace("agent_stop", { reason }, sessionId);
      if (!controllerRef.current) {
        stopRdTicks();
      }
      if (agentWatchdogRef.current !== null) {
        window.clearTimeout(agentWatchdogRef.current);
        agentWatchdogRef.current = null;
      }
      agentRef.current?.close();
      agentRef.current = null;
      agentSessionIdRef.current = null;
      const bridge = bridgeRef.current;
      void (async () => {
        if (sessionId && reason) {
          await reportEnd(sessionId, reason);
        }
        // 主进程那边也会报一次「结束」,会话已经是终态时后端直接忽略
        await bridge?.stop().catch(() => undefined);
        void refresh();
      })();
    },
    [refresh],
  );

  /** 被控端:开始交出屏幕。主进程已经批准(或已自行核实)过了才会走到这。 */
  const beginAgent = useCallback(
    (sessionId: string) => {
      const bridge = bridgeRef.current;
      if (!bridge || agentRef.current) {
        return;
      }
      agentSessionIdRef.current = sessionId;
      rdTrace("begin_agent", {}, sessionId);
      startRdTicks(sessionId);
      const agent = new RdAgent(sessionId, bridge, {
        onEnded: (reason) => {
          stopAgent(reason === "agent_kicked" ? "agent_kicked" : "connection_lost");
        },
        onLive: () => {
          if (agentWatchdogRef.current !== null) {
            window.clearTimeout(agentWatchdogRef.current);
            agentWatchdogRef.current = null;
          }
          void withRdRetry(() => activateRdSession(sessionId)).catch(
            () => undefined,
          );
          void refresh();
        },
      });
      agentRef.current = agent;
      // 同意了,对方却一直没来(发起端掉线 / 关了页面):不能让这台机器顶着红条干等
      agentWatchdogRef.current = window.setTimeout(() => {
        agentWatchdogRef.current = null;
        if (agentRef.current === agent) {
          rdTrace("agent_watchdog", { has_offer: agent.hasOffer }, sessionId);
          stopAgent("connection_lost");
        }
      }, RD_HANDSHAKE_TIMEOUT_MS + 15_000);
    },
    [refresh, stopAgent],
  );

  // 会话进了终态:控制端收画面、被控端撤红条。SSE 和台账轮询两条路都走这里
  onTerminalRef.current = (item: RdSession) => {
    rdTrace("terminal", { reason: item.end_reason, state: item.state }, item.id);
    if (agentSessionIdRef.current === item.id) {
      stopAgent(null);
    }
    const current = sessionRef.current;
    if (current && current.id === item.id) {
      if (item.state === "denied") {
        setNotice("对方拒绝了这次请求。");
      } else if (item.state === "expired") {
        setNotice("对方一直没有回应，请求已经超时。");
      } else if (item.end_reason === "handshake_failed") {
        setNotice(failureNotice("no_answer"));
      } else if (controllerRef.current) {
        setNotice("会话已经结束。");
      }
      teardown();
    }
  };

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
      source = new EventSource(rdStreamUrl(lastSignalIdRef.current), {
        withCredentials: true,
      });
      source.onopen = () => {
        rdTrace("sse_open", { after: lastSignalIdRef.current, failures });
        failures = 0;
      };

      source.addEventListener("request", (event) => {
        const parsed = normalizeRdSession(
          JSON.parse((event as MessageEvent<string>).data),
        );
        if (!parsed) {
          return;
        }
        rdTrace("sse_request", {}, parsed.id);
        const bridge = bridgeRef.current;
        if (bridge && parsed.device_id === selfDeviceIdRef.current) {
          if (promptedRef.current.has(parsed.id)) {
            return;
          }
          promptedRef.current.add(parsed.id);
          // 弹的是主进程的原生框。同意与否由主进程直接回报给控制台，网页
          // 不经手，也无从声称。
          void bridge
            .consent({
              requesterName:
                parsed.controller_name ?? `用户 ${parsed.controller_user_id}`,
              sessionId: parsed.id,
            })
            .then((result) => {
              rdTrace("consent_result", { approved: result.approved }, parsed.id);
              if (result.approved) {
                beginAgent(parsed.id);
              }
              void refresh();
            })
            .catch((error) => rdTraceError("consent_fail", error, {}, parsed.id));
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
        rdTrace("sse_session", { state: parsed.state }, parsed.id);
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

        if (TERMINAL_STATES.has(parsed.state)) {
          onTerminalRef.current?.(parsed);
          void refresh();
          return;
        }

        const current = sessionRef.current;
        if (!current || current.id !== parsed.id) {
          void refresh();
          return;
        }
        setSession(parsed);
        if (parsed.state === "consented" && !controllerRef.current) {
          void beginMedia(parsed);
        }
        void refresh();
      });

      source.addEventListener("signal", (event) => {
        const data = JSON.parse((event as MessageEvent<string>).data) as {
          session_id: string;
          id?: number;
          kind: string;
          payload: string;
        };
        rdTrace("sse_signal", { id: data.id ?? null, kind: data.kind }, data.session_id);
        if (typeof data.id === "number") {
          // 同一条信令只喂一次
          if (seenSignalIdsRef.current.has(data.id)) {
            return;
          }
          seenSignalIdsRef.current.add(data.id);
          lastSignalIdRef.current = Math.max(lastSignalIdRef.current, data.id);
        }
        const agent = agentRef.current;
        if (agent && agentSessionIdRef.current === data.session_id) {
          void agent.accept(data.kind, data.payload).catch(() => undefined);
          return;
        }
        const current = sessionRef.current;
        if (current && current.id === data.session_id) {
          void controllerRef.current?.accept(data.kind, data.payload);
        }
      });

      source.onerror = () => {
        rdTrace("sse_error", {
          failures: failures + 1,
          online: navigator.onLine,
          state: source?.readyState ?? null,
        });
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
        rdTrace("connect_click", { device_id: device.id, ...requestQueueSnapshot() });
        const created = await requestRdSession(device.id);
        rdTrace("session_requested", { state: created.state }, created.id);
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
        rdTraceError("connect_fail", error, requestQueueSnapshot());
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
