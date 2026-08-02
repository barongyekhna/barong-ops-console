"use client";

import { useCallback, useEffect, useState } from "react";

import { API_PROXY_BASE, buildHeaders, readJson } from "./api-base";

const GOLD = "#d9a441";
const GREEN = "#55bd88";
const RED = "#dd6d63";
const MUTED = "#8b98a8";

type Stranded = {
  kind: string;
  label: string;
  id: string;
  name: string;
  status: string;
  reason: string;
};

/**
 * 内容自检：**标了完成，产物却不存在**。
 *
 * 这种记录不会报错、不会变红、不会出现在任何列表里——它只是静静地少一篇
 * 内容，而控制台以为写过了，永远不会再派它出去。2026-08-01 用户问「都做完
 * 了吗」，是我一条条查库才翻出来的。全绿时这块**几乎不占地方**，因为它平时
 * 就该是安静的。
 */
export function ContentHealthPanel() {
  const [rows, setRows] = useState<Stranded[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try {
      const response = await fetch(`${API_PROXY_BASE}/seo/content-health`, {
        cache: "no-store",
        headers: buildHeaders(),
        method: "GET",
      });
      const data = await readJson<{ stranded: Stranded[] }>(
        response,
        "内容自检加载失败",
      );
      setRows(data.stranded ?? []);
      setError(null);
    } catch (loadError) {
      setError((loadError as Error).message);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const resetAll = useCallback(async () => {
    if (!rows?.length) return;
    setBusy(true);
    setError(null);
    try {
      // 按类型分组——GEO 簇和 SEO 选题复位成不同的状态。
      const byKind = new Map<string, string[]>();
      for (const row of rows) {
        byKind.set(row.kind, [...(byKind.get(row.kind) ?? []), row.id]);
      }
      let total = 0;
      for (const [kind, ids] of byKind) {
        const response = await fetch(
          `${API_PROXY_BASE}/seo/content-health/reset`,
          {
            body: JSON.stringify({ ids, kind }),
            headers: buildHeaders(true),
            method: "POST",
          },
        );
        const result = await readJson<{ reset: number }>(response, "复位失败");
        total += result.reset ?? 0;
      }
      setNotice(`已复位 ${total} 条，它们现在可以重新生成了。`);
      await reload();
    } catch (resetError) {
      setError((resetError as Error).message);
    } finally {
      setBusy(false);
    }
  }, [reload, rows]);

  if (rows === null && !error) return null;

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
          <strong style={{ color: "#dfe6ef", fontSize: 14 }}>内容自检</strong>
          {rows && rows.length > 0 ? (
            <span style={{ color: GOLD, fontSize: 12 }}>
              ⚠ 有 {rows.length} 条标了完成，却一篇内容都没有
            </span>
          ) : (
            <span style={{ color: MUTED, fontSize: 12 }}>没有卡住的记录</span>
          )}
          <span style={{ flex: 1 }} />
          <button
            disabled={busy || !rows?.length}
            onClick={() => void resetAll()}
            style={rows?.length ? primary : ghost}
            type="button"
          >
            一键复位
          </button>
        </div>
        <div style={{ color: MUTED, fontSize: 11, marginTop: 8 }}>
          复位后它们会重新进入可派单状态。**已经有文章的记录碰不到**——
          复位时会再验一次。
        </div>
        {rows && rows.length > 0 ? (
          <ul style={{ color: "#c7d0da", fontSize: 12, margin: "8px 0 0 18px" }}>
            {rows.slice(0, 10).map((row) => (
              <li key={row.id}>{row.reason}</li>
            ))}
          </ul>
        ) : null}
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

const primary: React.CSSProperties = {
  background: `${GOLD}22`,
  border: `1px solid ${GOLD}88`,
  borderRadius: 6,
  color: GOLD,
  cursor: "pointer",
  fontSize: 12,
  padding: "6px 14px",
};

const ghost: React.CSSProperties = {
  background: "transparent",
  border: "1px solid #ffffff22",
  borderRadius: 6,
  color: "#b9c4d1",
  cursor: "pointer",
  fontSize: 12,
  padding: "5px 12px",
};
