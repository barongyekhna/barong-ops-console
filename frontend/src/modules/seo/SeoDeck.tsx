"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { LinkNetPanel } from "../content/LinkNetPanel";
import { CraftFactDeck } from "./facts/CraftFactDeck";
import {
  generateArticle,
  getMonitor,
  listItems,
  listPublishes,
  listTopics,
  probeTerrain,
  publishItems,
  rebuildFactoryIndex,
  reviewItem,
  reviseItem,
  runRadar,
  seedMonitor,
  setTopicStatus,
  type MonitorRow,
  type PublishJob,
  type RadarRun,
  type SeoItem,
  type SeoJob,
  type SeoTopic,
} from "./facts/api";

const GOLD = "#d9a441";
const BLUE = "#6aa6e8";
const GREEN = "#55bd88";
const RED = "#dd6d63";
const MUTED = "#8b98a8";

type TabKey = "facts" | "topics" | "items" | "publish" | "monitor";

const TABS: { key: TabKey; label: string; hint: string }[] = [
  { key: "facts", label: "工艺事实", hint: "内容的原料。库有多厚，内容就有多硬" },
  { key: "topics", label: "关键词雷达", hint: "写什么。GEO 够得到的自动不进这里" },
  { key: "items", label: "内容", hint: "生成、审阅、按批评重写" },
  { key: "publish", label: "发布", hint: "/factory/ 与 /posts/，草稿优先" },
  { key: "monitor", label: "阵地监测", hint: "打不打得动，反过来影响排序" },
];

const AUDIENCE_LABEL: Record<string, string> = {
  consumer: "C 端",
  wholesale: "B 端批发",
  brand: "品牌/工艺",
};

const KIND_LABEL: Record<string, string> = {
  craft_story: "工艺故事",
  material_explainer: "材料取舍",
  testing: "测试报告",
  buying_guide: "选购指南",
  wholesale_guide: "采购指南",
  brand_story: "品牌故事",
};

const SOURCE_LABEL: Record<string, string> = {
  keyword_radar: "关键词",
  store_type: "店型覆盖",
  craft_topic: "工艺话题",
  manual: "手输",
};

const REVIEW_LABEL: Record<string, { label: string; color: string }> = {
  pending: { label: "待审", color: GOLD },
  approved: { label: "已批准", color: GREEN },
  rejected: { label: "已驳回", color: RED },
};

export function SeoDeck() {
  const [tab, setTab] = useState<TabKey>("facts");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [topics, setTopics] = useState<SeoTopic[]>([]);
  const [lastRun, setLastRun] = useState<RadarRun | null>(null);
  const [seedInput, setSeedInput] = useState("");

  const [items, setItems] = useState<SeoItem[]>([]);
  const [jobs, setJobs] = useState<SeoJob[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const [publishJobs, setPublishJobs] = useState<PublishJob[]>([]);
  const [monitorRows, setMonitorRows] = useState<MonitorRow[]>([]);

  const reload = useCallback(async () => {
    try {
      if (tab === "topics") {
        const payload = await listTopics();
        setTopics(payload.topics);
        setLastRun(payload.last_run);
      } else if (tab === "items") {
        const payload = await listItems();
        setItems(payload.items);
        setJobs(payload.jobs);
      } else if (tab === "publish") {
        const [payload, itemPayload] = await Promise.all([
          listPublishes(),
          listItems(),
        ]);
        setPublishJobs(payload.jobs);
        setItems(itemPayload.items);
      } else if (tab === "monitor") {
        setMonitorRows((await getMonitor()).rows);
      }
      setError(null);
    } catch (loadError) {
      setError((loadError as Error).message);
    }
  }, [tab]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const run = useCallback(
    async (action: () => Promise<string | null>) => {
      setBusy(true);
      setError(null);
      try {
        setNotice(await action());
        await reload();
      } catch (actionError) {
        setError((actionError as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [reload],
  );

  const approvedItems = useMemo(
    () => items.filter((i) => i.review_status === "approved"),
    [items],
  );

  const toggleSelected = (id: string) => {
    const next = new Set(selected);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    setSelected(next);
  };

  /* ------------------------------------------------------------ 选题 */

  const topicsTab = (
    <div style={{ display: "grid", gap: 12 }}>
      <div style={card}>
        <div style={{ color: MUTED, fontSize: 12, marginBottom: 10 }}>
          种子来自 K 的已批准关键词、工艺库话题、以及每个已启用店型的采购决策问题。
          <strong style={{ color: "#dfe6ef" }}>
            {" "}
            GEO 够得到的题不会出现在这里
          </strong>
          ——同一话题两边都写就是自我竞争。
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input
            onChange={(e) => setSeedInput(e.target.value)}
            placeholder="额外种子词，逗号分隔（可空）"
            style={{ ...input, flex: 1, minWidth: 260 }}
            value={seedInput}
          />
          <button
            disabled={busy}
            onClick={() =>
              void run(async () => {
                const result = await runRadar(
                  seedInput
                    .split(",")
                    .map((s) => s.trim())
                    .filter(Boolean),
                );
                setSeedInput("");
                return `雷达跑完：${result.seed_count} 个种子 → ${result.candidate_count} 条新候选，${result.geo_blocked_count} 条归 GEO，花了 ${result.planner_calls} 次搜索量查询。`;
              })
            }
            style={primary}
            type="button"
          >
            跑一轮雷达
          </button>
        </div>
        {lastRun ? (
          <div style={{ color: MUTED, fontSize: 11, marginTop: 8 }}>
            上次：{lastRun.candidate_count} 条候选 ·{" "}
            {lastRun.notes?.geo_blocked ?? `${lastRun.geo_blocked_count} 条归 GEO`}
            {(lastRun.notes?.notes ?? []).map((n) => (
              <div key={n}>· {n}</div>
            ))}
          </div>
        ) : null}
      </div>

      {topics.map((topic) => {
        const support = topic.fact_support ?? {};
        return (
          <div key={topic.id} style={card}>
            <div style={{ alignItems: "center", display: "flex", flexWrap: "wrap", gap: 8 }}>
              <span style={{ color: GOLD, fontSize: 11 }}>
                {AUDIENCE_LABEL[topic.audience] ?? topic.audience}
              </span>
              <span style={{ color: MUTED, fontSize: 11 }}>
                {SOURCE_LABEL[topic.source] ?? topic.source}
              </span>
              <span style={{ color: BLUE, fontSize: 11 }}>
                → /{topic.destination}/
              </span>
              <span style={{ flex: 1 }} />
              <span style={{ color: MUTED, fontSize: 11 }}>分 {topic.score}</span>
              {topic.avg_monthly_searches !== null ? (
                <span style={{ color: MUTED, fontSize: 11 }}>
                  月搜 {topic.avg_monthly_searches}
                </span>
              ) : null}
              {topic.attackability !== null ? (
                <span
                  style={{
                    color: topic.attackability >= 50 ? GREEN : RED,
                    fontSize: 11,
                  }}
                >
                  可攻 {topic.attackability} · {topic.terrain}
                </span>
              ) : null}
            </div>

            <div style={{ color: "#dfe6ef", fontSize: 14, marginTop: 6 }}>
              {topic.keyword}
            </div>
            {topic.geo_reason ? (
              <div style={{ color: MUTED, fontSize: 11, marginTop: 4 }}>
                {topic.geo_reason}
              </div>
            ) : null}
            {support.has_support ? (
              <div style={{ color: GREEN, fontSize: 11, marginTop: 4 }}>
                有事实支撑：{(support.supported ?? []).join(" / ")}
              </div>
            ) : (
              <div style={{ color: RED, fontSize: 11, marginTop: 4 }}>
                没有事实支撑，写出来只能是空话 —— 缺{" "}
                {(support.missing ?? []).join("、")}
              </div>
            )}

            <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
              <button
                disabled={busy || topic.attackability !== null}
                onClick={() =>
                  void run(async () => {
                    const r = await probeTerrain(topic.id);
                    return `可攻度 ${r.attackability}（${r.terrain}）`;
                  })
                }
                style={ghost}
                type="button"
              >
                {topic.attackability === null ? "测可攻度" : "已测"}
              </button>
              <button
                disabled={busy || !support.has_support}
                onClick={() =>
                  void run(async () => {
                    await generateArticle(topic.id);
                    return "已排队，seo-worker 正在写（一分钟起步）。";
                  })
                }
                style={primary}
                type="button"
              >
                生成文章
              </button>
              <button
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    await setTopicStatus(topic.id, "rejected", "人工排除");
                    return "已排除。";
                  })
                }
                style={ghost}
                type="button"
              >
                不写
              </button>
            </div>
          </div>
        );
      })}
      {topics.length === 0 ? (
        <div style={{ ...card, color: MUTED, fontSize: 13 }}>
          队列是空的。先跑一轮雷达；如果跑完还是空的，多半是种子不够
          ——去 K 补关键词，或在「工艺事实」里录几条。
        </div>
      ) : null}
    </div>
  );

  /* ------------------------------------------------------------ 内容 */

  const itemsTab = (
    <div style={{ display: "grid", gap: 12 }}>
      {jobs.filter((j) => j.status === "queued" || j.status === "running").length >
      0 ? (
        <div style={{ ...card, borderColor: `${GOLD}66`, color: GOLD, fontSize: 12 }}>
          有 {jobs.filter((j) => j.status !== "success" && j.status !== "failed").length}{" "}
          个生成任务在跑。
        </div>
      ) : null}
      {jobs
        .filter((j) => j.status === "failed")
        .slice(0, 3)
        .map((j) => (
          <div
            key={j.job_id}
            style={{ ...card, borderColor: `${RED}66`, color: RED, fontSize: 12 }}
          >
            生成失败：{j.error}
          </div>
        ))}

      {items.map((item) => {
        const audit = item.brand_audit ?? {};
        const meta = REVIEW_LABEL[item.review_status] ?? {
          label: item.review_status,
          color: MUTED,
        };
        const open = expanded === item.id;
        return (
          <div key={item.id} style={card}>
            <div style={{ alignItems: "center", display: "flex", flexWrap: "wrap", gap: 8 }}>
              <span style={{ color: GOLD, fontSize: 11 }}>
                {KIND_LABEL[item.item_kind] ?? item.item_kind}
              </span>
              <span style={{ color: BLUE, fontSize: 11 }}>/{item.destination}/</span>
              <span
                style={{
                  border: `1px solid ${meta.color}66`,
                  borderRadius: 999,
                  color: meta.color,
                  fontSize: 11,
                  padding: "2px 10px",
                }}
              >
                {meta.label}
              </span>
              {audit.clean === false ? (
                <span style={{ color: RED, fontSize: 11 }}>未过审查</span>
              ) : null}
              {item.wp_status ? (
                <span style={{ color: MUTED, fontSize: 11 }}>
                  WP：{item.wp_status}
                </span>
              ) : null}
              <span style={{ flex: 1 }} />
              <button
                onClick={() => setExpanded(open ? null : item.id)}
                style={ghost}
                type="button"
              >
                {open ? "收起" : "展开"}
              </button>
            </div>

            <div style={{ color: "#dfe6ef", fontSize: 15, marginTop: 8 }}>
              {item.title}
            </div>
            <div style={{ color: MUTED, fontSize: 11, marginTop: 2 }}>
              选题：{item.topic ?? "—"}
            </div>

            {open ? (
              <div style={{ marginTop: 10 }}>
                {item.sections.map((section, index) => (
                  <div key={index} style={{ marginBottom: 10 }}>
                    <div style={{ color: GOLD, fontSize: 13 }}>
                      {section.heading}
                    </div>
                    <div style={{ color: "#c7d0da", fontSize: 13, lineHeight: 1.6 }}>
                      {section.body}
                    </div>
                  </div>
                ))}

                {(item.links?.missing_facts ?? []).length > 0 ? (
                  <div style={{ color: GOLD, fontSize: 11, marginTop: 8 }}>
                    模型说它缺这些事实（去工艺库补，比改写有用）：
                    {(item.links.missing_facts ?? []).join("；")}
                  </div>
                ) : null}

                {(audit.ungrounded_numbers ?? []).length > 0 ? (
                  <div style={{ color: RED, fontSize: 11, marginTop: 8 }}>
                    无据数字：
                    {(audit.ungrounded_numbers ?? [])
                      .map((n) => n.number)
                      .join("、")}
                  </div>
                ) : null}

                {item.analysis?.risks?.length ? (
                  <div style={{ color: MUTED, fontSize: 12, marginTop: 8 }}>
                    <div style={{ color: "#dfe6ef" }}>批评意见</div>
                    <ul style={{ margin: "4px 0 0 18px" }}>
                      {item.analysis.risks.map((r) => (
                        <li key={r}>{r}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
                  <button
                    disabled={busy || audit.clean === false}
                    onClick={() =>
                      void run(async () => {
                        await reviewItem(item.id, "approved");
                        return "已批准，可以发布了。";
                      })
                    }
                    style={primary}
                    type="button"
                  >
                    批准
                  </button>
                  <button
                    disabled={busy || !item.analysis?.risks?.length}
                    onClick={() =>
                      void run(async () => {
                        await reviseItem(item.id);
                        return "已排队重写（按批评改，改不了的会如实报出来）。";
                      })
                    }
                    style={ghost}
                    type="button"
                  >
                    按批评重写
                  </button>
                  <button
                    disabled={busy}
                    onClick={() =>
                      void run(async () => {
                        await reviewItem(item.id, "rejected");
                        return "已驳回。";
                      })
                    }
                    style={ghost}
                    type="button"
                  >
                    驳回
                  </button>
                  {item.published_url ? (
                    <a
                      href={item.published_url}
                      rel="noreferrer"
                      style={{ ...ghost, textDecoration: "none" }}
                      target="_blank"
                    >
                      看线上
                    </a>
                  ) : null}
                </div>
              </div>
            ) : null}
          </div>
        );
      })}
      {items.length === 0 ? (
        <div style={{ ...card, color: MUTED, fontSize: 13 }}>
          还没有文章。去「关键词雷达」挑一个有事实支撑的选题，点生成。
        </div>
      ) : null}
    </div>
  );

  /* ------------------------------------------------------------ 发布 */

  const publishTab = (
    <div style={{ display: "grid", gap: 12 }}>
      <div style={card}>
        <div style={{ color: MUTED, fontSize: 12, marginBottom: 10 }}>
          首次推送**刻意落草稿**，等你在 WordPress 里人工发布。
          工艺文进 /factory/，C 端博文进 /posts/，两边分类不同，
          factory 分类会自动排除出博客归档。
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button
            disabled={busy || selected.size === 0}
            onClick={() =>
              void run(async () => {
                const result = await publishItems([...selected]);
                setSelected(new Set());
                return `发布单 ${result.job_id} 已派出（${result.status}）。`;
              })
            }
            style={primary}
            type="button"
          >
            发布选中的 {selected.size} 篇
          </button>
          <button
            disabled={busy}
            onClick={() =>
              void run(async () => {
                const result = await rebuildFactoryIndex();
                return `/factory/ 已更新：${result.url ?? "（无 URL）"}；排除名单 ${result.excluded_category_ids ?? "未变"}。`;
              })
            }
            style={ghost}
            type="button"
          >
            重建 /factory/ 枢纽页
          </button>
        </div>
      </div>

      <LinkNetPanel />

      {approvedItems.map((item) => (
        <label
          key={item.id}
          style={{ ...card, alignItems: "center", cursor: "pointer", display: "flex", gap: 10 }}
        >
          <input
            checked={selected.has(item.id)}
            onChange={() => toggleSelected(item.id)}
            type="checkbox"
          />
          <span style={{ color: "#dfe6ef", fontSize: 13 }}>{item.title}</span>
          <span style={{ color: MUTED, fontSize: 11 }}>/{item.destination}/</span>
          <span style={{ flex: 1 }} />
          {item.wp_post_id ? (
            <span style={{ color: MUTED, fontSize: 11 }}>
              已在 WP（{item.wp_status ?? "?"}），再发是更新
            </span>
          ) : null}
        </label>
      ))}
      {approvedItems.length === 0 ? (
        <div style={{ ...card, color: MUTED, fontSize: 13 }}>
          没有已批准的文章。只有批准且过了审查的才能发。
        </div>
      ) : null}

      {publishJobs.length > 0 ? (
        <div style={card}>
          <div style={{ color: "#dfe6ef", fontSize: 13, marginBottom: 8 }}>
            发布记录
          </div>
          {publishJobs.map((job) => (
            <div key={job.job_id} style={{ color: MUTED, fontSize: 11 }}>
              {job.job_id.slice(0, 8)} · {job.status} ·{" "}
              {job.published_items.length} 篇
              {job.error ? (
                <span style={{ color: RED }}> · {job.error}</span>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );

  /* ------------------------------------------------------------ 监测 */

  const monitorTab = (
    <div style={{ display: "grid", gap: 12 }}>
      <div style={card}>
        <div style={{ color: MUTED, fontSize: 12, marginBottom: 10 }}>
          和 GEO 的阵地监测共用一套表——只是单位从买家问句换成关键词。
          可攻度会反过来重排选题：<strong style={{ color: "#dfe6ef" }}>打不动的题会自己沉下去</strong>。
        </div>
        <button
          disabled={busy}
          onClick={() =>
            void run(async () => {
              const r = await seedMonitor();
              return `新增 ${r.added} 条监测项，${r.topics_rescored} 个选题按最新可攻度重排。`;
            })
          }
          style={primary}
          type="button"
        >
          把已选中的选题灌进监测名单
        </button>
      </div>
      {monitorRows.map((row) => (
        <div key={row.keyword} style={card}>
          <div style={{ alignItems: "center", display: "flex", gap: 8 }}>
            <span style={{ color: "#dfe6ef", fontSize: 13, flex: 1 }}>
              {row.keyword}
            </span>
            {row.attackability !== null ? (
              <span
                style={{
                  color: row.attackability >= 50 ? GREEN : RED,
                  fontSize: 11,
                }}
              >
                可攻 {row.attackability} · {row.terrain}
              </span>
            ) : (
              <span style={{ color: MUTED, fontSize: 11 }}>还没测</span>
            )}
            {row.our_position ? (
              <span style={{ color: BLUE, fontSize: 11 }}>
                我方第 {row.our_position} 位
              </span>
            ) : null}
          </div>
        </div>
      ))}
      {monitorRows.length === 0 ? (
        <div style={{ ...card, color: MUTED, fontSize: 13 }}>
          监测名单是空的。先在雷达里选定几个题，再点上面的按钮。
        </div>
      ) : null}
    </div>
  );

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div
        style={{
          borderBottom: "1px solid #ffffff1a",
          display: "flex",
          flexWrap: "wrap",
          gap: 4,
        }}
      >
        {TABS.map((entry) => (
          <button
            key={entry.key}
            onClick={() => {
              setTab(entry.key);
              setNotice(null);
            }}
            style={{
              background: "transparent",
              border: "none",
              borderBottom:
                tab === entry.key ? `2px solid ${GOLD}` : "2px solid transparent",
              color: tab === entry.key ? GOLD : "#b9c4d1",
              cursor: "pointer",
              fontSize: 13,
              padding: "8px 14px",
            }}
            title={entry.hint}
            type="button"
          >
            {entry.label}
          </button>
        ))}
      </div>

      {error ? (
        <div style={{ ...card, borderColor: `${RED}66`, color: RED }}>{error}</div>
      ) : null}
      {notice ? (
        <div style={{ ...card, borderColor: `${GREEN}66`, color: GREEN }}>
          {notice}
        </div>
      ) : null}

      {tab === "facts" ? <CraftFactDeck /> : null}
      {tab === "topics" ? topicsTab : null}
      {tab === "items" ? itemsTab : null}
      {tab === "publish" ? publishTab : null}
      {tab === "monitor" ? monitorTab : null}
    </div>
  );
}

const card: React.CSSProperties = {
  background: "#0d131bcc",
  border: "1px solid #ffffff1a",
  borderRadius: 10,
  padding: 14,
};

const input: React.CSSProperties = {
  background: "#0a0f16",
  border: "1px solid #ffffff22",
  borderRadius: 6,
  color: "#dfe6ef",
  fontSize: 13,
  padding: "6px 10px",
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
