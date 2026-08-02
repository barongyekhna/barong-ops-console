"use client";

import { useCallback, useEffect, useState } from "react";

import { API_PROXY_BASE, buildHeaders, readJson } from "./api-base";

const GOLD = "#d9a441";
const GREEN = "#55bd88";
const RED = "#dd6d63";
const MUTED = "#8b98a8";

type Hub = {
  key: string;
  label: string;
  path: string;
  count: number;
  pinned?: boolean;
};

/**
 * 站内入口。规矩只有一条：**枢纽页有内容就挂入口，没内容就摘掉。**
 *
 * 2026-08-01 之前两头都错着：/guides/ 有 5 篇指南却全站零入口，
 * /posts/ 正文是「Nothing Found」反而挂在主导航上。
 */
export function SiteNavPanel() {
  const [hubs, setHubs] = useState<Hub[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try {
      const response = await fetch(`${API_PROXY_BASE}/seo/site-nav`, {
        cache: "no-store",
        headers: buildHeaders(),
        method: "GET",
      });
      const data = await readJson<{ hubs: Hub[] }>(response, "站内入口加载失败");
      setHubs(data.hubs ?? []);
      setError(null);
    } catch (loadError) {
      setError((loadError as Error).message);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const togglePin = useCallback(
    async (hub: Hub) => {
      setBusy(true);
      setError(null);
      try {
        const response = await fetch(`${API_PROXY_BASE}/seo/site-nav/pin`, {
          body: JSON.stringify({ key: hub.key, pinned: !hub.pinned }),
          headers: buildHeaders(true),
          method: "POST",
        });
        await readJson<unknown>(response, "设置失败");
        setNotice(
          hub.pinned
            ? `${hub.label} 取消强制——它现在按内容决定挂不挂。`
            : `${hub.label} 已强制挂上，即使还没有已发布文章。`,
        );
        await reload();
      } catch (pinError) {
        setError((pinError as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [reload],
  );

  const sync = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`${API_PROXY_BASE}/seo/site-nav/sync`, {
        headers: buildHeaders(true),
        method: "POST",
      });
      const result = await readJson<{
        menu: {
          ok: boolean;
          added?: string[];
          removed?: string[];
          reason?: string;
          header_titles?: string[];
          header_count?: number;
          crowded?: boolean;
        };
        home: { ok: boolean; changed?: boolean; reason?: string };
      }>(response, "同步失败");
      const parts: string[] = [];
      if (result.menu?.ok) {
        const added = result.menu.added ?? [];
        const removed = result.menu.removed ?? [];
        parts.push(
          added.length || removed.length
            ? `导航：加了 ${added.join("、") || "无"}${
                removed.length ? `；摘掉 ${removed.join("、")}` : ""
              }`
            : "导航：已经是对的",
        );
      } else {
        parts.push(`导航失败：${result.menu?.reason ?? "未知"}`);
      }
      if (result.home?.ok) {
        parts.push(result.home.changed ? "主页：已更新" : "主页：已经是对的");
      } else {
        parts.push(`主页失败：${result.home?.reason ?? "未知"}`);
      }
      const titles = result.menu?.header_titles ?? [];
      if (titles.length) {
        // 让人看见导航现在长什么样。枢纽是自动进来的，不报出来的话，
        // 哪天挤到换行只会觉得「网站突然变丑了」。
        parts.push(`主导航 ${titles.length} 项：${titles.join(" · ")}`);
      }
      if (result.menu?.crowded) {
        parts.push("⚠ 项数偏多，可能会换行——考虑把次要项挪进页脚");
      }
      setNotice(parts.join("　·　"));
      await reload();
    } catch (syncError) {
      setError((syncError as Error).message);
    } finally {
      setBusy(false);
    }
  }, [reload]);

  if (hubs === null && !error) return null;

  return (
    <div style={{ display: "grid", gap: 12 }}>
      {error ? (
        <div style={{ ...card, borderColor: `${RED}66`, color: RED }}>{error}</div>
      ) : null}
      {notice ? (
        <div style={{ ...card, borderColor: `${GREEN}66`, color: GREEN }}>
          {notice}
        </div>
      ) : null}

      <div style={card}>
        <div
          style={{ alignItems: "center", display: "flex", flexWrap: "wrap", gap: 8 }}
        >
          <strong style={{ color: "#dfe6ef", fontSize: 14 }}>站内入口</strong>
          <span style={{ color: MUTED, fontSize: 12 }}>
            主导航与主页的枢纽入口
          </span>
          <span style={{ flex: 1 }} />
          <button disabled={busy} onClick={() => void sync()} style={primary} type="button">
            同步站内入口
          </button>
        </div>
        <div style={{ color: MUTED, fontSize: 11, marginTop: 8 }}>
          规矩只有一条：**有内容就挂入口，没内容就摘掉**。文章一发布会自动跑，
          这个按钮只为立刻看效果。
        </div>
        <ul style={{ color: "#c7d0da", fontSize: 12, margin: "8px 0 0 18px" }}>
          {(hubs ?? []).map((hub) => (
            <li key={hub.key} style={{ marginBottom: 4 }}>
              {hub.label}（{hub.path}）：
              {hub.count > 0 ? (
                <span style={{ color: GREEN }}>{hub.count} 篇，会挂在导航上</span>
              ) : hub.pinned ? (
                <span style={{ color: GREEN }}>
                  0 篇，但已强制挂上
                </span>
              ) : (
                <span style={{ color: GOLD }}>还没有已发布的文章，入口不挂</span>
              )}
              <button
                disabled={busy}
                onClick={() => void togglePin(hub)}
                style={{ ...ghost, marginLeft: 8 }}
                type="button"
              >
                {hub.pinned ? "取消强制" : "强制挂上"}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

const card: React.CSSProperties = {
  background: "#0d131bcc",
  border: "1px solid #ffffff1a",
  borderRadius: 10,
  padding: 14,
};

const ghost: React.CSSProperties = {
  background: "transparent",
  border: "1px solid #ffffff22",
  borderRadius: 5,
  color: "#b9c4d1",
  cursor: "pointer",
  fontSize: 11,
  padding: "2px 8px",
};

const primary: React.CSSProperties = {
  background: `${GOLD}22`,
  border: `1px solid ${GOLD}88`,
  borderRadius: 6,
  color: GOLD,
  cursor: "pointer",
  fontSize: 12,
  padding: "6px 14px",
};
