"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  approveFact,
  createFact,
  factRevisions,
  listFacts,
  retireFact,
  updateFact,
  type CraftFact,
  type FactDraft,
  type FactRevision,
  type FactsState,
} from "./api";

const GOLD = "var(--color-warning)";
const GREEN = "var(--color-success)";
const RED = "var(--color-error)";
const MUTED = "var(--color-muted)";

const STATUS_META: Record<string, { label: string; color: string }> = {
  draft: { label: "待批准", color: GOLD },
  approved: { label: "已批准", color: GREEN },
  retired: { label: "已停用", color: MUTED },
};

const CONTENT_KIND_LABEL: Record<string, string> = {
  geo_item: "GEO 指南",
  seo_item: "SEO 文章",
  b2b_page: "B2B 页面",
};

const EMPTY_DRAFT: FactDraft = {
  topic: "",
  claim: "",
  detail: "",
  value: "",
  unit: "",
  basis: "",
};

function statusChip(status: string) {
  const meta = STATUS_META[status] ?? { label: status, color: MUTED };
  return (
    <span
      style={{
        border: `1px solid ${meta.color}66`,
        borderRadius: 999,
        color: meta.color,
        fontSize: 11,
        padding: "2px 10px",
        whiteSpace: "nowrap",
      }}
    >
      {meta.label}
    </span>
  );
}

export function CraftFactDeck() {
  const [state, setState] = useState<FactsState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [topicFilter, setTopicFilter] = useState<string>("");
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<FactDraft>(EMPTY_DRAFT);
  const [creating, setCreating] = useState(false);
  const [revisionsOf, setRevisionsOf] = useState<string | null>(null);
  const [revisions, setRevisions] = useState<FactRevision[]>([]);

  const reload = useCallback(async () => {
    try {
      setState(await listFacts());
      setError(null);
    } catch (loadError) {
      setError((loadError as Error).message);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const run = useCallback(
    async (action: () => Promise<string | null>) => {
      setBusy(true);
      setError(null);
      try {
        const message = await action();
        setNotice(message);
        await reload();
      } catch (actionError) {
        setError((actionError as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [reload],
  );

  const facts = useMemo(() => {
    const all = state?.facts ?? [];
    return topicFilter ? all.filter((f) => f.topic === topicFilter) : all;
  }, [state, topicFilter]);

  const staleFactIds = useMemo(() => {
    const ids = new Set<string>();
    for (const entry of state?.stale ?? []) {
      for (const fact of entry.stale_facts) {
        ids.add(fact.fact_id);
      }
    }
    return ids;
  }, [state]);

  const beginEdit = (fact: CraftFact) => {
    setCreating(false);
    setEditing(fact.id);
    setDraft({
      topic: fact.topic,
      claim: fact.claim,
      detail: fact.detail ?? "",
      value: fact.value ?? "",
      unit: fact.unit ?? "",
      basis: fact.basis ?? "",
      change_reason: "",
    });
  };

  const showRevisions = async (factId: string) => {
    if (revisionsOf === factId) {
      setRevisionsOf(null);
      return;
    }
    try {
      const payload = await factRevisions(factId);
      setRevisions(payload.revisions);
      setRevisionsOf(factId);
    } catch (loadError) {
      setError((loadError as Error).message);
    }
  };

  const field = (
    label: string,
    key: keyof FactDraft,
    placeholder: string,
    multiline = false,
  ) => (
    <label style={{ display: "grid", gap: 4 }}>
      <span style={{ color: MUTED, fontSize: 11 }}>{label}</span>
      {multiline ? (
        <textarea
          onChange={(event) =>
            setDraft({ ...draft, [key]: event.target.value })
          }
          placeholder={placeholder}
          rows={2}
          style={inputStyle}
          value={(draft[key] as string) ?? ""}
        />
      ) : (
        <input
          onChange={(event) =>
            setDraft({ ...draft, [key]: event.target.value })
          }
          placeholder={placeholder}
          style={inputStyle}
          value={(draft[key] as string) ?? ""}
        />
      )}
    </label>
  );

  const editor = (
    <div style={cardStyle}>
      <div style={{ display: "grid", gap: 10 }}>
        <div style={{ display: "grid", gap: 10, gridTemplateColumns: "1fr 1fr" }}>
          {field("话题分类", "topic", "waterproof-sealing / lithium-pack …")}
          <div style={{ display: "grid", gap: 10, gridTemplateColumns: "2fr 1fr" }}>
            {field("数值（可选）", "value", "30")}
            {field("单位", "unit", "minutes")}
          </div>
        </div>
        {field(
          "陈述（一句可核的话，会被直接引用）",
          "claim",
          "主体密封为双道 O 圈 + 超声波焊接",
          true,
        )}
        {field("补充说明（可选）", "detail", "仅主机，控制盒不浸水", true)}
        {field(
          "依据（自测 / 供应商规格 / 标准号 —— 空的不许批准）",
          "basis",
          "自测：2026-07 浸泡测试记录",
          true,
        )}
        {editing
          ? field("修改原因", "change_reason", "为什么改这条")
          : null}
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <button
          disabled={busy || !draft.topic.trim() || !draft.claim.trim()}
          onClick={() =>
            void run(async () => {
              if (editing) {
                const result = await updateFact(editing, draft);
                setEditing(null);
                setDraft(EMPTY_DRAFT);
                return result.note ?? "已保存（未构成实质修改，版本不变）。";
              }
              await createFact(draft);
              setCreating(false);
              setDraft(EMPTY_DRAFT);
              return "已录入，待批准。";
            })
          }
          style={primaryButton}
          type="button"
        >
          {editing ? "保存" : "录入"}
        </button>
        <button
          onClick={() => {
            setEditing(null);
            setCreating(false);
            setDraft(EMPTY_DRAFT);
          }}
          style={ghostButton}
          type="button"
        >
          取消
        </button>
      </div>
    </div>
  );

  return (
    <div style={{ display: "grid", gap: 16 }}>
      {error ? (
        <div style={{ ...cardStyle, borderColor: `${RED}66`, color: RED }}>
          {error}
        </div>
      ) : null}
      {notice ? (
        <div style={{ ...cardStyle, borderColor: `${GREEN}66`, color: GREEN }}>
          {notice}
        </div>
      ) : null}

      {/* 需复核清单：工艺一改，引用旧版的内容在这里显形 */}
      {(state?.stale?.length ?? 0) > 0 ? (
        <div style={{ ...cardStyle, borderColor: `${GOLD}88` }}>
          <div style={{ color: GOLD, fontSize: 13, marginBottom: 8 }}>
            需复核 · {state?.stale.length} 篇内容引用了已改动的事实
          </div>
          <div style={{ color: MUTED, fontSize: 12, marginBottom: 10 }}>
            过期的真话和编造一样有害——它带着可信的外表，没有任何输出护栏会报警。
          </div>
          <div style={{ display: "grid", gap: 8 }}>
            {state?.stale.map((entry) => (
              <div
                key={`${entry.content_kind}:${entry.content_id}`}
                style={{ fontSize: 12 }}
              >
                <span style={{ color: "var(--color-text-strong)" }}>
                  {CONTENT_KIND_LABEL[entry.content_kind] ?? entry.content_kind}{" "}
                  {entry.content_id}
                </span>
                <ul style={{ color: MUTED, margin: "4px 0 0 18px" }}>
                  {entry.stale_facts.map((fact) => (
                    <li key={fact.fact_id}>
                      {fact.claim.slice(0, 60)} —— 引用 v{fact.used_version}，
                      现已是 v{fact.current_version}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div
        style={{
          alignItems: "center",
          display: "flex",
          flexWrap: "wrap",
          gap: 8,
        }}
      >
        <button
          onClick={() => {
            setCreating(true);
            setEditing(null);
            setDraft(EMPTY_DRAFT);
          }}
          style={primaryButton}
          type="button"
        >
          + 录入工艺事实
        </button>
        <span style={{ color: MUTED, fontSize: 12 }}>
          共 {state?.facts.length ?? 0} 条，已批准 {state?.approved_count ?? 0} 条
          —— 只有已批准的才允许进内容
        </span>
        <span style={{ flex: 1 }} />
        <select
          onChange={(event) => setTopicFilter(event.target.value)}
          style={inputStyle}
          value={topicFilter}
        >
          <option value="">全部话题</option>
          {(state?.topics ?? []).map((topic) => (
            <option key={topic} value={topic}>
              {topic}
            </option>
          ))}
        </select>
      </div>

      {creating || (editing && !facts.some((f) => f.id === editing))
        ? editor
        : null}

      <div style={{ display: "grid", gap: 10 }}>
        {facts.map((fact) => (
          <div key={fact.id} style={cardStyle}>
            <div
              style={{
                alignItems: "center",
                display: "flex",
                flexWrap: "wrap",
                gap: 8,
              }}
            >
              <span style={{ color: GOLD, fontSize: 11 }}>{fact.topic}</span>
              {statusChip(fact.status)}
              <span style={{ color: MUTED, fontSize: 11 }}>v{fact.version}</span>
              {staleFactIds.has(fact.id) ? (
                <span style={{ color: GOLD, fontSize: 11 }}>
                  有内容还引用着旧版
                </span>
              ) : null}
              <span style={{ flex: 1 }} />
              {fact.status !== "approved" ? (
                <button
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      await approveFact(fact.id);
                      return "已批准，可以进内容了。";
                    })
                  }
                  style={ghostButton}
                  type="button"
                >
                  批准
                </button>
              ) : null}
              <button
                disabled={busy}
                onClick={() => beginEdit(fact)}
                style={ghostButton}
                type="button"
              >
                编辑
              </button>
              <button
                disabled={busy}
                onClick={() => void showRevisions(fact.id)}
                style={ghostButton}
                type="button"
              >
                版本历史
              </button>
              {fact.status !== "retired" ? (
                <button
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      await retireFact(fact.id);
                      return "已停用（不删除——已发布内容还引用着它）。";
                    })
                  }
                  style={ghostButton}
                  type="button"
                >
                  停用
                </button>
              ) : null}
            </div>

            <div style={{ color: "var(--color-text-strong)", fontSize: 14, marginTop: 8 }}>
              {fact.claim}
              {fact.value ? (
                <span style={{ color: GOLD }}>
                  {" "}
                  · {fact.value} {fact.unit ?? ""}
                </span>
              ) : null}
            </div>
            {fact.detail ? (
              <div style={{ color: MUTED, fontSize: 12, marginTop: 4 }}>
                {fact.detail}
              </div>
            ) : null}
            <div style={{ color: MUTED, fontSize: 11, marginTop: 6 }}>
              依据：{fact.basis || "（空——没有依据的事实不许批准）"}
            </div>

            {editing === fact.id ? editor : null}

            {revisionsOf === fact.id ? (
              <div
                style={{
                  borderTop: "1px solid color-mix(in srgb, var(--color-line-strong) 8%, transparent)",
                  marginTop: 10,
                  paddingTop: 10,
                }}
              >
                {revisions.map((revision) => (
                  <div
                    key={revision.version}
                    style={{ color: MUTED, fontSize: 11, marginBottom: 6 }}
                  >
                    <span style={{ color: "var(--color-text-strong)" }}>v{revision.version}</span>{" "}
                    {revision.change_reason ?? "—"}
                    {revision.changed_at
                      ? ` · ${revision.changed_at.slice(0, 19).replace("T", " ")}`
                      : ""}
                    <div>
                      {String(
                        (revision.snapshot as { claim?: string }).claim ?? "",
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ))}
        {facts.length === 0 ? (
          <div style={{ ...cardStyle, color: MUTED, fontSize: 13 }}>
            还没有工艺事实。工艺库有多厚，内容就有多硬——这一步代码替不了。
          </div>
        ) : null}
      </div>
    </div>
  );
}

const cardStyle: React.CSSProperties = {
  background: "color-mix(in srgb, var(--color-panel-base) 80%, transparent)",
  border: "1px solid color-mix(in srgb, var(--color-line-strong) 10%, transparent)",
  borderRadius: 10,
  padding: 14,
};

const inputStyle: React.CSSProperties = {
  background: "var(--color-surface-solid)",
  border: "1px solid color-mix(in srgb, var(--color-line-strong) 13%, transparent)",
  borderRadius: 6,
  color: "var(--color-text-strong)",
  fontSize: 13,
  padding: "6px 10px",
};

const primaryButton: React.CSSProperties = {
  background: `${GOLD}22`,
  border: `1px solid ${GOLD}88`,
  borderRadius: 6,
  color: GOLD,
  cursor: "pointer",
  fontSize: 12,
  padding: "6px 14px",
};

const ghostButton: React.CSSProperties = {
  background: "transparent",
  border: "1px solid color-mix(in srgb, var(--color-line-strong) 13%, transparent)",
  borderRadius: 6,
  color: "var(--color-text)",
  cursor: "pointer",
  fontSize: 12,
  padding: "5px 12px",
};
