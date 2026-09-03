"use client";

/**
 * 组织切换器。
 *
 * 为什么需要它（2026-08-31 体检）：
 * `middleware/org_context.py` 一直在读 `auth_session.active_org_id`，而这一列
 * 根本不存在，于是「会话选定组织」那条分支永不执行 —— 任何拥有 ≥2 个 active
 * 成员关系、又不是某组织 owner_user_id 的用户，解析链全落空、整站 403。
 * 而前端**没有任何切换入口**，撞上了也没有自救出口。
 *
 * 本轮补齐了列、写入端点、登录挑默认组织，这里是最后一环：让人能看见自己
 * 现在以哪个组织的身份在操作，并且能换。
 *
 * 放在顶栏而不是侧边栏：侧边栏那棵「组织」树是**模块分组导航**（哪些功能属于
 * 哪个组织），不是身份切换。把两件事放一起会让人以为点了树就切换了。
 */

import { useCallback, useEffect, useState } from "react";
import { Building2, Check, ChevronDown } from "lucide-react";

import { apiRequest } from "@/lib/api";

type AvailableOrg = {
  org_id: string;
  org_name: string;
  org_type: string;
  role: string;
  is_active_context: boolean;
};

type AvailableOrgsResponse = {
  organizations: AvailableOrg[];
  active_org_id: string | null;
};

const ORG_TYPE_LABEL: Record<string, string> = {
  store: "贸易",
  factory: "制造",
};

export function OrgSwitcher() {
  const [orgs, setOrgs] = useState<AvailableOrg[]>([]);
  const [activeOrgId, setActiveOrgId] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [switching, setSwitching] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      // 失败一律静默 —— 顶栏不该为「拉不到组织列表」挂一条红字。
      //
      // ⚠️ 2026-09-02 收口时的一处**有意的行为改变**：这条以前是裸 fetch，
      // 401 被这里吞掉、什么都不做。收口后走 `apiRequest`，401 会派发
      // AUTH_UNAUTHORIZED_EVENT，auth-provider 收到就 resetAuthState()。
      // 查过后端：`/auth/organizations` 只在**未登录**时返 401（登录用户
      // 哪怕只有一个组织也是 200 + 单元素列表），而这个组件只在登录后的
      // 控制台外壳里渲染。所以现实中唯一会碰到的 401 是「页面开着时会话过期」
      // —— 那种情况下把人送回登录页是对的，静默假装无组织才是错的。
      const payload = await apiRequest<AvailableOrgsResponse>(
        "/auth/organizations",
      );
      setOrgs(payload.organizations ?? []);
      setActiveOrgId(payload.active_org_id ?? null);
    } catch {
      setOrgs([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const switchTo = useCallback(
    async (orgId: string) => {
      if (orgId === activeOrgId) {
        setOpen(false);
        return;
      }
      setSwitching(orgId);
      setError(null);
      try {
        try {
          await apiRequest("/auth/switch-organization", {
            body: { org_id: orgId },
            method: "POST",
          });
        } catch (switchError) {
          setError(
            (switchError as Error).message.slice(0, 120) || "切换失败",
          );
          return;
        }
        // 组织换了，整页的模块清单、权限、业务数据全都要重取 ——
        // 与其逐个刷新，不如整页重载，语义最清楚也最不容易出错。
        window.location.reload();
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "切换失败");
      } finally {
        setSwitching(null);
      }
    },
    [activeOrgId],
  );

  // 只有一个组织（或取不到）时不显示 —— 单组织的人不需要这个东西占地方。
  if (orgs.length < 2) {
    return null;
  }

  const active = orgs.find((org) => org.org_id === activeOrgId) ?? orgs[0];

  return (
    <div className="org-switcher">
      <button
        aria-expanded={open}
        aria-haspopup="listbox"
        className="org-switcher-trigger"
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        <Building2 aria-hidden size={14} />
        <span className="org-switcher-name">{active?.org_name}</span>
        <ChevronDown aria-hidden size={14} />
      </button>

      {open ? (
        <div className="org-switcher-menu" role="listbox">
          <div className="org-switcher-hint">以哪个组织的身份操作</div>
          {orgs.map((org) => {
            const isActive = org.org_id === activeOrgId;
            return (
              <button
                aria-selected={isActive}
                className="org-switcher-option"
                disabled={switching !== null}
                key={org.org_id}
                onClick={() => void switchTo(org.org_id)}
                role="option"
                type="button"
              >
                <span className="org-switcher-option-name">{org.org_name}</span>
                <span className="org-switcher-option-meta">
                  {ORG_TYPE_LABEL[org.org_type] ?? org.org_type}
                  {org.role ? ` · ${org.role}` : ""}
                </span>
                {isActive ? <Check aria-hidden size={14} /> : null}
                {switching === org.org_id ? <span>切换中…</span> : null}
              </button>
            );
          })}
          {error ? (
            <div className="org-switcher-error" role="alert">
              {error}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
