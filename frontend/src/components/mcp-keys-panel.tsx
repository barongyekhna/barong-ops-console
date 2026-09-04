"use client";

import {
  Fingerprint,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
  ShieldOff,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { McpSecretBanner, type McpSecretPayload } from "@/components/mcp-secret-banner";
import { C19Avatar } from "@/modules/c19/C19Avatar";
import { isOwnerRole, isSuperAdminRole, normalizeRole } from "@/lib/roles";
import {
  disableUserMcpToken,
  enableUserMcpToken,
  formatUsersApiError,
  listMcpTokenLog,
  listOrganizations,
  listUsers,
  resetUserMcpToken,
  type ManagedUser,
  type McpTokenLogItem,
  type OrganizationOption,
} from "@/lib/users-api";

type TokenFilter = "all" | "issued" | "none" | "disabled";

const PAGE = 100;

const ACTION_LABELS: Record<string, string> = {
  "mcp_token.issue": "发放",
  "mcp_token.reset": "重置",
  "mcp_token.disable": "停用",
  "mcp_token.enable": "启用",
};

function formatTime(value: string | null | undefined) {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

function tokenState(user: ManagedUser): TokenFilter {
  if (!user.mcp_token?.has_token) {
    return "none";
  }
  return user.mcp_token.status === "disabled" ? "disabled" : "issued";
}

function displayName(user: ManagedUser) {
  const real = user.display_name?.trim() || user.username;
  const nick = user.nickname?.trim();
  return nick ? `${nick}（${real}）` : real;
}

export function McpKeysPanel() {
  const { user: currentUser } = useAuth();
  const role = normalizeRole(currentUser?.role ?? "");
  const owner = isOwnerRole(role);
  const superAdmin = isSuperAdminRole(role);
  const myOrg = currentUser?.organization_id ?? null;

  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [organizations, setOrganizations] = useState<OrganizationOption[]>([]);
  const [logs, setLogs] = useState<McpTokenLogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [issued, setIssued] = useState<McpSecretPayload | null>(null);

  const [orgFilter, setOrgFilter] = useState<string>("all");
  const [tokenFilter, setTokenFilter] = useState<TokenFilter>("all");
  const [query, setQuery] = useState("");
  const [showBots, setShowBots] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const all: ManagedUser[] = [];
      let offset = 0;
      // 用户总数几十个,按 100 一页翻到底就够了
      for (let guard = 0; guard < 20; guard += 1) {
        const page = await listUsers(PAGE, offset, {
          organizationId: superAdmin && myOrg ? myOrg : null,
        });
        all.push(...page.items);
        offset += page.items.length;
        if (page.items.length === 0 || offset >= page.count) {
          break;
        }
      }
      setUsers(all);
      const [orgs, log] = await Promise.all([
        owner ? listOrganizations(100, 0) : Promise.resolve(null),
        listMcpTokenLog(50),
      ]);
      if (orgs) {
        setOrganizations(orgs.items);
      }
      setLogs(log.items);
    } catch (loadError) {
      setError(formatUsersApiError(loadError, "读取接入钥匙列表失败。"));
    } finally {
      setLoading(false);
    }
  }, [owner, superAdmin, myOrg]);

  useEffect(() => {
    void load();
  }, [load]);

  const orgNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const org of organizations) {
      map.set(org.org_id, org.org_name);
    }
    for (const u of users) {
      if (u.organization_id && u.organization && u.organization !== u.organization_id) {
        map.set(u.organization_id, u.organization);
      }
    }
    return map;
  }, [organizations, users]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return users.filter((u) => {
      if (!showBots && u.is_bot) {
        return false;
      }
      if (orgFilter !== "all" && u.organization_id !== orgFilter) {
        return false;
      }
      if (tokenFilter !== "all" && tokenState(u) !== tokenFilter) {
        return false;
      }
      if (q) {
        const hay = `${u.username} ${u.display_name ?? ""} ${u.nickname ?? ""} ${u.job_title ?? ""}`.toLowerCase();
        if (!hay.includes(q)) {
          return false;
        }
      }
      return true;
    });
  }, [users, showBots, orgFilter, tokenFilter, query]);

  const counts = useMemo(() => {
    const humans = users.filter((u) => !u.is_bot);
    return {
      issued: humans.filter((u) => tokenState(u) === "issued").length,
      none: humans.filter((u) => tokenState(u) === "none").length,
      disabled: humans.filter((u) => tokenState(u) === "disabled").length,
    };
  }, [users]);

  function canManage(target: ManagedUser) {
    if (target.is_bot) {
      return false;
    }
    if (owner) {
      return true;
    }
    if (!superAdmin) {
      return false;
    }
    const targetRole = normalizeRole(target.role);
    if (targetRole === "owner" || targetRole === "super_admin") {
      return false;
    }
    return Boolean(myOrg) && target.organization_id === myOrg;
  }

  async function onReset(target: ManagedUser) {
    setNotice(null);
    setError(null);
    if (
      !window.confirm(
        `确认给 ${displayName(target)} 换一把新的 MCP 钥匙？旧钥匙立刻失效,新钥匙只显示这一次。`,
      )
    ) {
      return;
    }
    setPending(`reset-${target.id}`);
    try {
      const result = await resetUserMcpToken(target.id);
      setIssued({
        username: target.username,
        secret: result.token,
        setupCommandMac: result.setup_command_mac,
        setupCommandWindows: result.setup_command_windows,
      });
      setNotice(`已为 ${displayName(target)} 生成新钥匙。`);
      await load();
    } catch (actionError) {
      setError(formatUsersApiError(actionError, "重置钥匙失败。"));
    } finally {
      setPending(null);
    }
  }

  async function onToggle(target: ManagedUser) {
    setNotice(null);
    setError(null);
    const disabled = target.mcp_token?.status === "disabled";
    if (!disabled && target.id === currentUser?.id && !window.confirm("你在停用自己的钥匙,你的 Codex 会立刻断开。继续?")) {
      return;
    }
    setPending(`toggle-${target.id}`);
    try {
      if (disabled) {
        await enableUserMcpToken(target.id);
        setNotice(`已启用 ${displayName(target)} 的钥匙。`);
      } else {
        await disableUserMcpToken(target.id);
        setNotice(`已停用 ${displayName(target)} 的钥匙,他的 Codex 立刻连不上。`);
      }
      await load();
    } catch (actionError) {
      setError(formatUsersApiError(actionError, "更新钥匙状态失败。"));
    } finally {
      setPending(null);
    }
  }

  if (!owner && !superAdmin) {
    return (
      <div className="users-alert users-alert-error" role="alert">
        该页面只对 owner 与超级管理员开放。
      </div>
    );
  }

  return (
    <section className="users-workspace">
      {error ? (
        <div className="users-alert users-alert-error" role="alert">
          {error}
        </div>
      ) : null}
      {notice ? (
        <div className="users-alert users-alert-success" role="status">
          {notice}
        </div>
      ) : null}
      {issued ? <McpSecretBanner payload={issued} onClose={() => setIssued(null)} /> : null}

      <div className="um-toolbar" style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
        <span className="section-index" title="有效钥匙">已接入 {counts.issued}</span>
        <span className="section-index" title="还没生成钥匙">未申请 {counts.none}</span>
        <span className="section-index" title="被管理员停用">已停用 {counts.disabled}</span>
        <span style={{ flex: 1 }} />
        {owner ? (
          <select className="select-shell" onChange={(e) => setOrgFilter(e.target.value)} value={orgFilter}>
            <option value="all">全部组织</option>
            {organizations.map((org) => (
              <option key={org.org_id} value={org.org_id}>
                {org.org_name}
              </option>
            ))}
          </select>
        ) : (
          <span className="section-index">{myOrg ? orgNameById.get(myOrg) ?? "本组织" : "本组织"}</span>
        )}
        <select className="select-shell" onChange={(e) => setTokenFilter(e.target.value as TokenFilter)} value={tokenFilter}>
          <option value="all">全部状态</option>
          <option value="issued">已接入</option>
          <option value="none">未申请</option>
          <option value="disabled">已停用</option>
        </select>
        <input
          className="input-shell"
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜姓名 / 用户名 / 职位"
          value={query}
        />
        <label style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13 }}>
          <input checked={showBots} onChange={(e) => setShowBots(e.target.checked)} type="checkbox" />
          显示机器人
        </label>
        <button className="secondary-button" disabled={loading} onClick={() => void load()} type="button">
          {loading ? <LoaderCircle aria-hidden="true" className="spin" size={15} /> : <RefreshCw aria-hidden="true" size={15} />}
          刷新
        </button>
      </div>

      <div className="users-table-scroll">
        <table className="users-table">
          <thead>
            <tr>
              <th>成员</th>
              <th>角色</th>
              <th>职位</th>
              <th>组织</th>
              <th>钥匙</th>
              <th>上次使用</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {loading && users.length === 0 ? (
              <tr>
                <td colSpan={7} className="list-state">读取中…</td>
              </tr>
            ) : visible.length === 0 ? (
              <tr>
                <td colSpan={7} className="list-state">没有符合筛选的成员。</td>
              </tr>
            ) : (
              visible.map((u) => {
                const state = tokenState(u);
                const manageable = canManage(u);
                const busy = pending !== null;
                return (
                  <tr key={u.id} style={u.is_active ? undefined : { opacity: 0.55 }}>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <span style={{ width: 32, height: 32, flex: "0 0 32px" }}>
                          <C19Avatar avatarRef={u.avatar_url ?? null} className="c19-avatar" name={u.display_name || u.username} />
                        </span>
                        <span style={{ display: "grid", lineHeight: 1.25 }}>
                          <strong>{displayName(u)}</strong>
                          <span style={{ fontSize: 12, opacity: 0.7 }}>
                            {u.username}
                            {u.is_bot ? " · 机器人" : ""}
                            {u.is_active ? "" : " · 账号已停用"}
                          </span>
                        </span>
                      </div>
                    </td>
                    <td>{normalizeRole(u.role)}</td>
                    <td>{u.job_title ?? "—"}</td>
                    <td>{u.organization_id ? orgNameById.get(u.organization_id) ?? u.organization_id : "—"}</td>
                    <td>
                      {u.is_bot ? (
                        <span className="section-index">不发钥匙</span>
                      ) : state === "none" ? (
                        <span className="section-index">未申请</span>
                      ) : state === "disabled" ? (
                        <span className="section-index" style={{ color: "var(--color-text)" }}>已停用 · {u.mcp_token?.token_prefix}…</span>
                      ) : (
                        <span className="section-index" style={{ color: "var(--color-success)" }}>正常 · {u.mcp_token?.token_prefix}…</span>
                      )}
                    </td>
                    <td>{formatTime(u.mcp_token?.last_used_at)}</td>
                    <td>
                      {manageable ? (
                        <div className="users-actions">
                          <button
                            className="icon-button"
                            disabled={busy}
                            onClick={() => void onReset(u)}
                            title={state === "none" ? "生成钥匙(明文只显示一次,由你转交)" : "重置钥匙(旧的立刻失效)"}
                            aria-label="重置钥匙"
                            type="button"
                          >
                            {pending === `reset-${u.id}` ? <LoaderCircle className="spin" aria-hidden="true" size={17} /> : <Fingerprint aria-hidden="true" size={17} />}
                          </button>
                          <button
                            className={`icon-button${state === "disabled" ? "" : " icon-danger"}`}
                            disabled={busy}
                            onClick={() => void onToggle(u)}
                            title={state === "disabled" ? "启用钥匙" : "停用钥匙(他的 Codex 立刻断开)"}
                            aria-label={state === "disabled" ? "启用钥匙" : "停用钥匙"}
                            type="button"
                          >
                            {pending === `toggle-${u.id}` ? (
                              <LoaderCircle className="spin" aria-hidden="true" size={17} />
                            ) : state === "disabled" ? (
                              <ShieldCheck aria-hidden="true" size={17} />
                            ) : (
                              <ShieldOff aria-hidden="true" size={17} />
                            )}
                          </button>
                        </div>
                      ) : (
                        <span style={{ fontSize: 12, opacity: 0.6 }}>—</span>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <div className="users-list-heading" style={{ marginTop: 18 }}>
        <h3>操作记录</h3>
        <p className="list-state">谁在什么时候发放 / 重置 / 停用 / 启用了谁的钥匙(最近 50 条)。</p>
      </div>
      <div className="users-table-scroll">
        <table className="users-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>操作</th>
              <th>操作人</th>
              <th>对象</th>
              <th>IP</th>
            </tr>
          </thead>
          <tbody>
            {logs.length === 0 ? (
              <tr>
                <td colSpan={5} className="list-state">还没有记录。</td>
              </tr>
            ) : (
              logs.map((row) => (
                <tr key={row.id}>
                  <td>{formatTime(row.created_at)}</td>
                  <td>{ACTION_LABELS[row.action] ?? row.action}</td>
                  <td>{row.actor_username ?? row.actor_id ?? "—"}</td>
                  <td>{row.target_username ?? row.target_id ?? "—"}</td>
                  <td>{row.ip_address ?? "—"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
