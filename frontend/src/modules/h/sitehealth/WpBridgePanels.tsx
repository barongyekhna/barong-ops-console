"use client";

import {
  AlertTriangle,
  LoaderCircle,
  Plus,
  RefreshCw,
  Save,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  getWpRedirects,
  getWpSentinel,
  runWpSmtpCheck,
  saveWpRedirects,
  updateHealthFinding,
  verifyWpRedirect,
  type RedirectRule,
  type RedirectVerification,
  type SmtpDiagnostic,
  type WpSentinel,
} from "./api";
import styles from "./HealthDeck.module.css";
import { suggestRedirectTarget, toRedirectPath } from "./redirect-hint";
import type { RedirectHandoff } from "./SiteHealthWorkspace";
import { OutboundConfirm } from "@/components/outbound-confirm";

type EditorRule = RedirectRule & { id: number };

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "请求失败";
}

function disconnectedCard() {
  return (
    <div className={styles.bridgeDisconnected} role="status">
      <AlertTriangle aria-hidden="true" size={20} />
      <div>
        <strong>站点桥断开</strong>
        <span>WordPress 当前不可达或凭据未就绪，请稍后重试。</span>
      </div>
    </div>
  );
}

function verificationText(result: RedirectVerification) {
  if (result.reachable === false || result.status === null) {
    return { ok: false, text: "站点桥断开" };
  }
  const location = result.location ? ` → ${result.location}` : "";
  return {
    ok: result.status >= 300 && result.status < 400 && Boolean(result.location),
    text: `${result.status}${location}`,
  };
}

export function RedirectManager({
  handoff,
  onHandoffConsumed,
}: {
  /** 从「巡检中心」某条死链点「设跳转」带过来的 */
  handoff?: RedirectHandoff | null;
  onHandoffConsumed?: () => void;
} = {}) {
  const [rules, setRules] = useState<EditorRule[]>([]);
  const [reachable, setReachable] = useState<boolean | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // 保存是**整表覆盖**：写进去的这一份就是线上的全部跳转规则，
  // 不在列表里的旧规则会被删掉。所以点之前必须先说清楚。
  const [pendingSave, setPendingSave] = useState(false);
  const [nextId, setNextId] = useState(1);
  const [verifyingId, setVerifyingId] = useState<number | null>(null);
  // WordPress 那边**实际存着**的路径集合。用来区分「规则没生效」和「规则还没保存」——
  // 后者去验证只会拿到原样的 404，看着像出错，其实只是还没提交。
  const [savedPaths, setSavedPaths] = useState<Set<string>>(new Set());
  const [verifications, setVerifications] = useState<
    Record<number, { ok: boolean; text: string }>
  >({});

  const load = useCallback(async () => {
    setError(null);
    try {
      const data = await getWpRedirects();
      setReachable(data.reachable);
      setParseError(data.parse_error ?? null);
      const loaded = data.rules.map((rule, index) => ({ ...rule, id: index + 1 }));
      setRules(loaded);
      setNextId(loaded.length + 1);
      setSavedPaths(
        new Set(loaded.map((rule) => toRedirectPath(rule.from) ?? "")),
      );
      setVerifications({});
    } catch (loadError) {
      setError(errorMessage(loadError));
      setReachable(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // ---- 从死链「设跳转」过来的一次性交接 ----
  // 待结掉的那条死链：跳转保存**并实测生效后**才用它标记已解决。
  const [pendingFinding, setPendingFinding] = useState<
    { findingId: string; path: string; url: string } | null
  >(null);
  // 被预填/定位的那一行，界面上高亮它，让人一眼看到该确认哪行
  const [focusRuleId, setFocusRuleId] = useState<number | null>(null);
  // effect 里要读最新 rules，又不能把 rules 放进依赖（会重复触发交接）
  const rulesRef = useRef<EditorRule[]>([]);
  useEffect(() => {
    rulesRef.current = rules;
  }, [rules]);

  useEffect(() => {
    if (!handoff || reachable !== true) return; // 等跳转表读回来再填，否则会被 load() 覆盖
    const current = rulesRef.current;
    const existing = current.find(
      (rule) => toRedirectPath(rule.from) === handoff.path,
    );
    if (existing) {
      // 已经有同路径规则了，不重复加，直接定位过去
      setFocusRuleId(existing.id);
    } else {
      const id = current.reduce((max, rule) => Math.max(max, rule.id), 0) + 1;
      setRules((cur) => [
        ...cur,
        { id, from: handoff.path, to: suggestRedirectTarget(handoff.path) },
      ]);
      setNextId((cur) => Math.max(cur, id + 1));
      setFocusRuleId(id);
    }
    setPendingFinding({
      findingId: handoff.findingId,
      path: handoff.path,
      url: handoff.url,
    });
    setNotice(null);
    onHandoffConsumed?.();
    // onHandoffConsumed 每次渲染都是新函数，放进依赖会反复触发交接
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handoff, reachable]);

  const updateRule = (id: number, field: keyof RedirectRule, value: string) => {
    setRules((current) =>
      current.map((rule) => (rule.id === id ? { ...rule, [field]: value } : rule)),
    );
    setVerifications((current) => {
      const next = { ...current };
      delete next[id];
      return next;
    });
  };

  const doSave = async () => {
    setPendingSave(false);
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await saveWpRedirects(
        rules.map(({ from, to }) => ({ from, to })),
      );
      setReachable(result.reachable);
      if (!result.reachable) return;
      const saved = result.rules.map((rule, index) => ({ ...rule, id: index + 1 }));
      setRules(saved);
      setNextId(saved.length + 1);
      setSavedPaths(
        new Set(saved.map((rule) => toRedirectPath(rule.from) ?? "")),
      );
      setParseError(null);
      setFocusRuleId(null);
      setNotice(`已保存 ${saved.length} 条跳转规则`);

      // 从死链过来的：**实测一次真的 301 了**，才把那条死链标成已解决。
      // 不实测就标记 = 报告成功但可能什么都没发生（本仓库栽过，见记忆 external-side-effect-verify）。
      if (pendingFinding) {
        const verdict = verificationText(
          await verifyWpRedirect(pendingFinding.path),
        );
        if (verdict.ok) {
          await updateHealthFinding(pendingFinding.findingId, "resolve");
          setPendingFinding(null);
          setNotice(
            `跳转已生效（${verdict.text}），${pendingFinding.url} 这条死链已标记为已解决`,
          );
        } else {
          setError(
            `跳转规则已保存，但实测没生效（${verdict.text}）——这条死链**没有**标记为已解决。` +
              `检查一下目标地址是否可访问，或者该路径其实还能打开（插件只在 404 时才跳转）。`,
          );
        }
      }
    } catch (saveError) {
      setError(errorMessage(saveError));
    } finally {
      setBusy(false);
    }
  };

  const handleVerify = async (rule: EditorRule) => {
    // 没保存就验证，拿到的必然是原样的 404 —— 那不是"规则有问题"，是"规则还没上去"。
    // 直接说清楚，别让人对着一个 404 猜半天（2026-08-02 用户就在这卡住了）。
    if (!savedPaths.has(toRedirectPath(rule.from) ?? "")) {
      setVerifications((current) => ({
        ...current,
        [rule.id]: {
          ok: false,
          text: "这条还没保存，先点上面的「保存」再验证",
        },
      }));
      return;
    }
    setVerifyingId(rule.id);
    setError(null);
    try {
      const result = await verifyWpRedirect(rule.from.trim());
      setVerifications((current) => ({
        ...current,
        [rule.id]: verificationText(result),
      }));
    } catch (verifyError) {
      setVerifications((current) => ({
        ...current,
        [rule.id]: { ok: false, text: errorMessage(verifyError) },
      }));
    } finally {
      setVerifyingId(null);
    }
  };

  if (reachable === null) {
    return (
      <div className={styles.state} role="status">
        <LoaderCircle aria-hidden="true" className="spin" size={18} />
        正在读取 WordPress 跳转表…
      </div>
    );
  }

  if (!reachable) {
    return (
      <div className={styles.wpPanelStack}>
        {disconnectedCard()}
        <button className="secondary-button" onClick={() => void load()} type="button">
          重新连接
        </button>
      </div>
    );
  }

  return (
    <div className={styles.wpPanelStack}>
      <div className={styles.wpToolbar}>
        <div>
          <h2>跳转管理</h2>
          <p>整表保存到 WordPress；重复旧路径以后出现的规则为准。</p>
        </div>
        <div className={styles.actionRow}>
          <button
            className="secondary-button"
            disabled={busy || rules.length >= 200}
            onClick={() => {
              setRules((current) => [...current, { id: nextId, from: "/", to: "/" }]);
              setNextId((current) => current + 1);
            }}
            type="button"
          >
            <Plus aria-hidden="true" size={15} /> 添加规则
          </button>
          <button
            className="primary-button"
            disabled={busy}
            onClick={() => setPendingSave(true)}
            type="button"
          >
            {busy ? (
              <LoaderCircle aria-hidden="true" className="spin" size={15} />
            ) : (
              <Save aria-hidden="true" size={15} />
            )}
            保存
          </button>
        </div>
      </div>

      {parseError ? (
        <div className={styles.parseWarning} role="alert">
          <AlertTriangle aria-hidden="true" size={17} /> {parseError}
        </div>
      ) : null}
      {error ? <div className={styles.inlineError} role="alert">{error}</div> : null}
      {notice ? <div className={styles.saveToast} role="status">{notice}</div> : null}
      {pendingFinding ? (
        <div className={styles.parseWarning} role="status">
          <ShieldCheck aria-hidden="true" size={17} />
          正在为死链 <strong>{pendingFinding.url}</strong> 建跳转。
          下面高亮那行的目标是**按路径规律猜的**，确认或改掉再保存；
          保存后会实测一次，确实跳通了才把这条死链标为已解决。
        </div>
      ) : null}

      {pendingSave ? (
        <OutboundConfirm
          busy={busy}
          confirmLabel="确认覆盖"
          consequence={
            "保存是**整表覆盖**——线上会变成下面这一份规则，不在列表里的旧跳转会被删掉。"
          }
          details={[
            `本次写入 ${rules.length} 条规则`,
            "插件只在 404 时才跳转，不影响还能打开的页面",
          ]}
          onCancel={() => setPendingSave(false)}
          onConfirm={() => {
            void doSave();
          }}
          title="确认覆盖线上跳转表？"
        />
      ) : null}
      <section className={styles.panel} aria-label="WordPress 跳转规则">
        {rules.length === 0 ? (
          <div className={styles.emptyHint}>还没有跳转规则，点「添加规则」开始。</div>
        ) : (
          <div className={styles.tableScroll}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>旧路径</th>
                  <th>新目标</th>
                  <th>验证结果</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {rules.map((rule) => {
                  const verification = verifications[rule.id];
                  const focused = focusRuleId === rule.id;
                  return (
                    <tr
                      data-focus={focused ? "on" : undefined}
                      key={rule.id}
                      ref={
                        focused
                          ? (node) =>
                              node?.scrollIntoView({
                                behavior: "smooth",
                                block: "center",
                              })
                          : undefined
                      }
                    >
                      <td>
                        <input
                          aria-label="旧路径"
                          className={styles.ruleInput}
                          maxLength={500}
                          onChange={(event) => updateRule(rule.id, "from", event.target.value)}
                          value={rule.from}
                        />
                      </td>
                      <td>
                        <input
                          aria-label="新目标"
                          className={styles.ruleInput}
                          onChange={(event) => updateRule(rule.id, "to", event.target.value)}
                          value={rule.to}
                        />
                      </td>
                      <td>
                        {verification ? (
                          <span
                            className={styles.verifyResult}
                            data-ok={verification.ok ? "true" : "false"}
                          >
                            {verification.text}
                          </span>
                        ) : (
                          <span className={styles.mutedResult}>—</span>
                        )}
                      </td>
                      <td>
                        <div className={styles.actionRow}>
                          <button
                            className="secondary-button"
                            disabled={verifyingId !== null || !rule.from.trim()}
                            onClick={() => void handleVerify(rule)}
                            type="button"
                          >
                            {verifyingId === rule.id ? (
                              <LoaderCircle aria-hidden="true" className="spin" size={14} />
                            ) : (
                              <ShieldCheck aria-hidden="true" size={14} />
                            )}
                            验证
                          </button>
                          <button
                            aria-label="删除规则"
                            className="secondary-button"
                            disabled={busy}
                            onClick={() =>
                              setRules((current) =>
                                current.filter((item) => item.id !== rule.id),
                              )
                            }
                            type="button"
                          >
                            <Trash2 aria-hidden="true" size={14} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

const pingLabels: Record<string, string> = {
  redirects: "跳转表",
  "email-brand": "邮件品牌",
  perf: "性能",
  related: "相关推荐",
  track: "物流追踪",
  "email-verify": "邮件验证",
};

function formatTime(value: string) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}

export function PluginSentinel() {
  const [sentinel, setSentinel] = useState<WpSentinel | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showConfirmation, setShowConfirmation] = useState(false);
  const [smtpBusy, setSmtpBusy] = useState(false);
  const [smtpResult, setSmtpResult] = useState<SmtpDiagnostic | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSentinel(await getWpSentinel());
    } catch (loadError) {
      setError(errorMessage(loadError));
      setSentinel(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleSmtpCheck = async () => {
    setShowConfirmation(false);
    setSmtpBusy(true);
    setError(null);
    setSmtpResult(null);
    try {
      setSmtpResult(await runWpSmtpCheck());
    } catch (smtpError) {
      setError(errorMessage(smtpError));
    } finally {
      setSmtpBusy(false);
    }
  };

  if (loading) {
    return (
      <div className={styles.state} role="status">
        <LoaderCircle aria-hidden="true" className="spin" size={18} />
        正在读取插件状态…
      </div>
    );
  }

  if (!sentinel?.reachable) {
    return (
      <div className={styles.wpPanelStack}>
        {disconnectedCard()}
        {error ? <div className={styles.inlineError}>{error}</div> : null}
        <button className="secondary-button" onClick={() => void load()} type="button">
          重新连接
        </button>
      </div>
    );
  }

  return (
    <div className={styles.wpPanelStack}>
      <div className={styles.wpToolbar}>
        <div>
          <h2>插件哨兵</h2>
          <p>插件、诊断口和最近邮件状态的一屏快照；不会自动执行 SMTP 登录。</p>
        </div>
        <button className="secondary-button" onClick={() => void load()} type="button">
          <RefreshCw aria-hidden="true" size={15} /> 刷新快照
        </button>
      </div>

      {error ? <div className={styles.inlineError} role="alert">{error}</div> : null}

      <section>
        <h3 className={styles.wpSectionTitle}>插件</h3>
        <div className={styles.pluginGrid}>
          {sentinel.plugins.length === 0 ? (
            <div className={styles.emptyHint}>未读到插件清单。</div>
          ) : (
            sentinel.plugins.map((plugin) => (
              <article className={styles.pluginCard} key={plugin.plugin}>
                <span
                  className={styles.healthDot}
                  data-ok={plugin.status === "active" ? "true" : "false"}
                />
                <div>
                  <strong>{plugin.name}</strong>
                  <span>{plugin.version || "版本未知"} · {plugin.status}</span>
                </div>
              </article>
            ))
          )}
        </div>
      </section>

      <section>
        <h3 className={styles.wpSectionTitle}>诊断口</h3>
        <div className={styles.pingGrid}>
          {sentinel.pings.map((ping) => (
            <div className={styles.pingItem} key={ping.slug}>
              <span className={styles.healthDot} data-ok={ping.ok ? "true" : "false"} />
              <strong>{pingLabels[ping.slug] ?? ping.slug}</strong>
              <span>{ping.version || (ping.ok ? "在线" : "异常")}</span>
            </div>
          ))}
        </div>
      </section>

      <section className={styles.mailPanel}>
        <div className={styles.mailHead}>
          <h3 className={styles.wpSectionTitle}>最近邮件</h3>
          <span
            className={styles.failureCount}
            data-alert={sentinel.mail.recent_failures > 0 ? "true" : "false"}
          >
            失败 {sentinel.mail.recent_failures}
          </span>
        </div>
        {sentinel.mail.items.length === 0 ? (
          <div className={styles.emptyHint}>暂无邮件日志。</div>
        ) : (
          <div className={styles.tableScroll}>
            <table className={styles.table}>
              <thead>
                <tr><th>时间</th><th>收件人</th><th>主题</th></tr>
              </thead>
              <tbody>
                {sentinel.mail.items.map((mail, index) => (
                  <tr key={`${mail.time}-${mail.to}-${index}`}>
                    <td className={styles.timeCell}>{formatTime(mail.time)}</td>
                    <td>{mail.to || "—"}</td>
                    <td>{mail.subject || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className={styles.smtpPanel}>
        <div>
          <h3>SMTP 体检</h3>
          <p>只在明确点击后运行一次，不参与哨兵刷新。</p>
        </div>
        <button
          className="primary-button"
          disabled={smtpBusy}
          onClick={() => setShowConfirmation(true)}
          type="button"
        >
          {smtpBusy ? <LoaderCircle aria-hidden="true" className="spin" size={15} /> : null}
          SMTP 体检
        </button>
      </section>

      {smtpResult ? (
        smtpResult.reachable ? (
          <dl className={styles.smtpResult}>
            <div><dt>探针</dt><dd>{smtpResult.probe || "—"}</dd></div>
            <div><dt>结论</dt><dd>{smtpResult.verdict_line || "—"}</dd></div>
            <div><dt>主机</dt><dd>{smtpResult.host || "—"}</dd></div>
            <div><dt>用户名</dt><dd>{smtpResult.username || "—"}</dd></div>
          </dl>
        ) : (
          disconnectedCard()
        )
      ) : null}

      {showConfirmation ? (
        <div className={styles.confirmBackdrop} role="presentation">
          <div
            aria-labelledby="smtp-confirm-title"
            aria-modal="true"
            className={styles.confirmDialog}
            role="dialog"
          >
            <h3 id="smtp-confirm-title">确认执行 SMTP 体检？</h3>
            <p>将执行一次真实邮箱登录。请勿连续点击，以免触发邮箱服务商风控。</p>
            <div className={styles.actionRow}>
              <button
                className="secondary-button"
                onClick={() => setShowConfirmation(false)}
                type="button"
              >
                取消
              </button>
              <button
                className="primary-button"
                onClick={() => void handleSmtpCheck()}
                type="button"
              >
                确认，登录一次
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
