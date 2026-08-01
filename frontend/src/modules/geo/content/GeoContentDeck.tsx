"use client";

import { useCallback, useEffect, useState } from "react";

import { ContentHealthPanel } from "../../content/ContentHealthPanel";
import { LinkNetPanel } from "../../content/LinkNetPanel";
import {
  analyzeItem,
  generateCluster,
  getCritiqueSummary,
  getPublishState,
  getBacklinkState,
  getMonitorState,
  seedMonitorFromCluster,
  runMonitorSweep,
  probeTopicTerrain,
  dispatchBacklinks,
  publishCluster,
  reviseItem,
  generateProductSpotlight,
  getCluster,
  getClusterJobs,
  getTopicCandidates,
  listClusters,
  reviewItem,
  savePickedQuestions,
  mineClusterQuestions,
  type GeoCluster,
  type GeoClusterProduct,
  type GeoCritiqueSummary,
  type GeoPublishState,
  type GeoBacklinkState,
  type GeoMonitorState,
  type GeoItem,
  type GeoJob,
  type GeoTopicCandidate,
} from "./api";

/* ------------------------------------------------------------------ tokens */

const GOLD = "#d9a441";
const BLUE = "#6aa6e8";
const GREEN = "#55bd88";
const RED = "#dd6d63";
const MUTED = "#8b98a8";

type StatusMeta = { label: string; color: string };

const CLUSTER_STATUS: Record<string, StatusMeta> = {
  draft: { label: "待选题", color: MUTED },
  generating: { label: "生成中", color: GOLD },
  ready: { label: "就绪", color: BLUE },
  needs_review: { label: "待审核", color: GOLD },
  approved: { label: "已批准", color: GREEN },
  archived: { label: "已归档", color: MUTED },
};

const REVIEW_STATUS: Record<string, StatusMeta> = {
  pending: { label: "待审", color: GOLD },
  approved: { label: "已批准", color: GREEN },
  rejected: { label: "已驳回", color: RED },
};

const ITEM_TYPE_LABEL: Record<string, string> = {
  hub: "话题枢纽",
  how_it_works: "原理",
  comparison: "对比",
  scenario: "场景",
  qa: "问答",
  question_answer: "单题深答",
  product_spotlight: "产品专属",
};

const INTENT_LABEL: Record<string, string> = {
  operation: "操作",
  compatibility: "兼容",
  travel_logistics: "出行",
  maintenance: "保养",
  safety: "安全",
  buyer_concern: "买家关切",
  wet_weather: "涉水",
  cold_weather: "低温",
  wind_weather: "风况",
  altitude_performance: "高海拔",
};

function clusterMeta(status: string): StatusMeta {
  return CLUSTER_STATUS[status] ?? { label: status, color: MUTED };
}

function normQ(q: string): string {
  return q.trim().toLowerCase().replace(/\?+$/, "").trim();
}

function auditClean(item: GeoItem): boolean {
  return item.brand_audit?.clean === true;
}

/* ------------------------------------------------------------------- tabs */

// 按工作流顺序分组,而不是按代码顺序:选题 → 内容 → 发布 → 监测。
// 原来八个板块竖着堆一页,找个功能要滚很久。
type TabKey = "topics" | "content" | "publish" | "monitor";

const TABS: { key: TabKey; label: string; hint: string }[] = [
  { key: "topics", label: "选题", hint: "本簇产品 · 候选问句 · 阵地探测" },
  { key: "content", label: "内容", hint: "生成的文章 · 审核 · AI 解读 · 批评汇总" },
  { key: "publish", label: "发布", hint: "发到站点 · 产品页反链" },
  { key: "monitor", label: "阵地监测", hint: "自然搜索排名 · 可攻度" },
];

/* -------------------------------------------------------------- component */

export function GeoContentDeck() {
  const [clusters, setClusters] = useState<GeoCluster[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<GeoCluster | null>(null);
  const [items, setItems] = useState<GeoItem[]>([]);
  const [products, setProducts] = useState<GeoClusterProduct[]>([]);
  const [jobs, setJobs] = useState<GeoJob[]>([]);
  const [candidates, setCandidates] = useState<GeoTopicCandidate[]>([]);
  const [picked, setPicked] = useState<Map<string, string>>(new Map());
  const [pickedQuestions, setPickedQuestions] = useState<Map<string, string>>(
    new Map(),
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [spotlightBusy, setSpotlightBusy] = useState<string | null>(null);
  const [loadingTopics, setLoadingTopics] = useState(false);
  const [mineReport, setMineReport] = useState<string | null>(null);
  const [probeBusy, setProbeBusy] = useState(false);
  const [tab, setTab] = useState<TabKey>("content");
  const [openProducts, setOpenProducts] = useState(false);
  const [openTopics, setOpenTopics] = useState(true);
  const [openAnalysis, setOpenAnalysis] = useState<Set<string>>(new Set());
  const [analyzeBusy, setAnalyzeBusy] = useState<string | null>(null);
  const [reviseBusy, setReviseBusy] = useState<string | null>(null);
  const [summary, setSummary] = useState<GeoCritiqueSummary | null>(null);
  const [summaryBusy, setSummaryBusy] = useState(false);
  const [openSummary, setOpenSummary] = useState(false);
  const [publish, setPublish] = useState<GeoPublishState | null>(null);
  const [publishBusy, setPublishBusy] = useState(false);
  const [backlink, setBacklink] = useState<GeoBacklinkState | null>(null);
  const [backlinkBusy, setBacklinkBusy] = useState(false);
  const [monitor, setMonitor] = useState<GeoMonitorState | null>(null);
  const [monitorBusy, setMonitorBusy] = useState<string | null>(null);

  const refreshClusters = useCallback(async () => {
    try {
      const { clusters: list } = await listClusters();
      setClusters(list);
      setSelectedId((current) => current ?? list[0]?.id ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  const refreshDetail = useCallback(async (clusterId: string) => {
    try {
      const { cluster, items: list, products: prods } = await getCluster(clusterId);
      setDetail(cluster);
      setItems(list);
      setProducts(prods || []);
      const { jobs: jobList } = await getClusterJobs(clusterId);
      setJobs(jobList);
      try {
        setPublish(await getPublishState(clusterId));
      } catch {
        setPublish(null);
      }
      try {
        setBacklink(await getBacklinkState());
      } catch {
        setBacklink(null);
      }
      try {
        setMonitor(await getMonitorState());
      } catch {
        setMonitor(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  const loadTopics = useCallback(async (clusterId: string) => {
    setLoadingTopics(true);
    try {
      const { candidates: cands, picked: savedPicks } =
        await getTopicCandidates(clusterId);
      setCandidates(cands);
      const p = new Map<string, string>();
      const pq = new Map<string, string>();
      for (const sp of savedPicks) {
        const k = normQ(sp.question);
        p.set(k, sp.intent || "");
        pq.set(k, sp.question);
      }
      setPicked(p);
      setPickedQuestions(pq);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingTopics(false);
    }
  }, []);

  useEffect(() => {
    void refreshClusters();
  }, [refreshClusters]);

  useEffect(() => {
    if (selectedId) {
      void refreshDetail(selectedId);
      void loadTopics(selectedId);
    }
  }, [selectedId, refreshDetail, loadTopics]);

  const busyGenerating =
    detail?.status === "generating" ||
    jobs.some((j) => j.status === "pending" || j.status === "running");

  useEffect(() => {
    if (!selectedId || !busyGenerating) return;
    const timer = setInterval(() => {
      void refreshDetail(selectedId);
      void refreshClusters();
    }, 4000);
    return () => clearInterval(timer);
  }, [selectedId, busyGenerating, refreshDetail, refreshClusters]);

  async function handleGenerate() {
    if (!selectedId) return;
    setBusy(true);
    setError(null);
    try {
      await generateCluster(selectedId);
      await refreshDetail(selectedId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function togglePick(c: GeoTopicCandidate) {
    const k = normQ(c.question);
    setPicked((prev) => {
      const n = new Map(prev);
      if (n.has(k)) n.delete(k);
      else n.set(k, c.intent);
      return n;
    });
    setPickedQuestions((prev) => {
      const n = new Map(prev);
      if (n.has(k)) n.delete(k);
      else n.set(k, c.question);
      return n;
    });
  }

  async function handleProbeTerrain() {
    if (!selectedId) return;
    setProbeBusy(true);
    setError(null);
    try {
      await probeTopicTerrain(selectedId);
      await loadTopics(selectedId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setProbeBusy(false);
    }
  }

  async function handleMineQuestions() {
    if (!selectedId) return;
    setBusy(true);
    setError(null);
    setMineReport(null);
    try {
      const report = await mineClusterQuestions(selectedId);
      setMineReport(
        `挖到 ${report.new_questions} 个新问句（打了 ${report.queries_spent} 发，` +
          `二级展开 ${report.expanded} 个）。` +
          (report.notes.length ? " " + report.notes.join("；") : ""),
      );
      await loadTopics(selectedId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleSavePicks() {
    if (!selectedId) return;
    setBusy(true);
    setError(null);
    try {
      const questions = Array.from(pickedQuestions.entries()).map(([k, q]) => ({
        question: q,
        intent: picked.get(k) || "",
      }));
      await savePickedQuestions(selectedId, questions);
      await refreshDetail(selectedId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleSpotlight(p: GeoClusterProduct) {
    if (!selectedId) return;
    setSpotlightBusy(p.product_id);
    setError(null);
    try {
      await generateProductSpotlight(selectedId, p.product_id);
      await refreshDetail(selectedId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSpotlightBusy(null);
    }
  }

  function toggleAnalysis(itemId: string) {
    setOpenAnalysis((prev) => {
      const n = new Set(prev);
      if (n.has(itemId)) n.delete(itemId);
      else n.add(itemId);
      return n;
    });
  }

  async function handleAnalyze(item: GeoItem) {
    setAnalyzeBusy(item.id);
    setError(null);
    try {
      await analyzeItem(item.id);
      if (selectedId) await refreshDetail(selectedId);
      setOpenAnalysis((prev) => new Set(prev).add(item.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setAnalyzeBusy(null);
    }
  }

  async function handleRevise(item: GeoItem) {
    setReviseBusy(item.id);
    setError(null);
    try {
      await reviseItem(item.id);
      if (selectedId) await refreshDetail(selectedId);
      setOpenAnalysis((prev) => new Set(prev).add(item.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setReviseBusy(null);
    }
  }

  async function handleSummary() {
    if (!selectedId) return;
    setSummaryBusy(true);
    setError(null);
    try {
      const s = await getCritiqueSummary(selectedId);
      setSummary(s);
      setOpenSummary(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSummaryBusy(false);
    }
  }

  async function handlePublish() {
    if (!selectedId) return;
    setPublishBusy(true);
    setError(null);
    try {
      await publishCluster(selectedId);
      await refreshDetail(selectedId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPublishBusy(false);
    }
  }

  async function handleBacklinks() {
    setBacklinkBusy(true);
    setError(null);
    try {
      await dispatchBacklinks();
      if (selectedId) await refreshDetail(selectedId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBacklinkBusy(false);
    }
  }

  async function handleMonitor(action: "seed" | "run") {
    setMonitorBusy(action);
    setError(null);
    try {
      if (action === "seed") {
        if (!selectedId) return;
        await seedMonitorFromCluster(selectedId);
      } else {
        await runMonitorSweep();
      }
      setMonitor(await getMonitorState());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setMonitorBusy(null);
    }
  }

  async function handleReview(item: GeoItem, status: "approved" | "rejected") {
    try {
      await reviewItem(item.id, status);
      if (selectedId) await refreshDetail(selectedId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const pendingCount = products.filter((p) => p.is_pending).length;
  // 只在"最近一次生成确实失败"时报警。原来写的是在整个历史里 find 任何一条
  // failed,于是历史上失败过一次,这条红字就永久挂着——哪怕后面已经成功三次。
  // jobs 由后端按时间倒序给出。
  const latestJob = jobs[0] ?? null;
  const failedJob = latestJob?.status === "failed" ? latestJob : null;

  return (
    <div style={SHELL}>
      {error ? (
        <div style={{ ...BANNER, borderColor: "rgba(221,109,99,0.45)", color: RED }}>
          {error}
        </div>
      ) : null}

      <div style={GRID}>
        {/* ------------------------------------------------ 左：话题簇列表 */}
        <aside style={{ ...CARD, padding: 14, alignSelf: "start" }}>
          <div style={PANEL_HEAD}>
            <strong>话题簇</strong>
            <span style={COUNT_PILL}>{clusters.length}</span>
          </div>
          {clusters.length === 0 ? (
            <p style={HINT}>
              还没有话题簇。产品在 P 系列上架成功后会自动按类目建簇。
            </p>
          ) : (
            <ul style={{ ...RESET_LIST, gap: 8 }}>
              {clusters.map((c) => {
                const meta = clusterMeta(c.status);
                const active = selectedId === c.id;
                const count = c.item_count ?? 0;
                return (
                  <li key={c.id}>
                    <button
                      onClick={() => setSelectedId(c.id)}
                      style={{
                        ...CLUSTER_BTN,
                        borderLeftColor: meta.color,
                        ...(active ? CLUSTER_BTN_ON : {}),
                      }}
                    >
                      <span style={CLUSTER_TITLE}>{c.title}</span>
                      <span style={CLUSTER_SUB}>
                        <span style={{ ...DOT, background: meta.color }} />
                        <span style={{ color: meta.color, fontWeight: 600 }}>
                          {meta.label}
                        </span>
                        <span style={{ opacity: 0.45 }}>·</span>
                        <span style={{ opacity: 0.7 }}>{count} 篇</span>
                        {(c.product_ids?.length ?? 0) > 0 ? (
                          <>
                            <span style={{ opacity: 0.45 }}>·</span>
                            <span style={{ opacity: 0.7 }}>
                              {c.product_ids?.length} 品
                            </span>
                          </>
                        ) : null}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </aside>

        {/* ------------------------------------------------------ 右：详情 */}
        <main style={{ display: "grid", gap: 12, alignContent: "start" }}>
          {!detail ? (
            <div style={{ ...CARD, padding: 28 }}>
              <p style={HINT}>选择左侧一个话题簇。</p>
            </div>
          ) : (
            <>
              <header style={{ ...CARD, ...STICKY_HEAD }}>
                <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                  <div style={{ flex: 1, minWidth: 220 }}>
                    <h2 style={{ margin: "0 0 6px", fontSize: 18 }}>{detail.title}</h2>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                      <span
                        style={{
                          ...BADGE,
                          color: clusterMeta(detail.status).color,
                          borderColor: `${clusterMeta(detail.status).color}66`,
                          background: `${clusterMeta(detail.status).color}1a`,
                        }}
                      >
                        {clusterMeta(detail.status).label}
                      </span>
                      <span style={{ fontSize: 12, opacity: 0.6 }}>
                        {detail.category_path || detail.topic || "—"}
                      </span>
                    </div>
                  </div>
                  <button
                    onClick={() => void handleGenerate()}
                    disabled={busy || busyGenerating}
                    style={PRIMARY_BTN}
                  >
                    {busyGenerating ? "生成中…" : "生成内容"}
                  </button>
                </div>
              </header>

              {pendingCount > 0 ? (
                <div style={{ ...BANNER, borderColor: `${GOLD}66`, background: `${GOLD}14` }}>
                  <strong style={{ color: GOLD }}>有 {pendingCount} 个新上架产品</strong>
                  <span style={{ opacity: 0.85 }}>
                    　已审核内容不受影响（链接会自动包含新产品）；想让正文也提到它，重新「生成内容」即可。
                  </span>
                </div>
              ) : null}

              {failedJob ? (
                <div style={{ ...BANNER, borderColor: "rgba(221,109,99,0.45)", color: RED }}>
                  生成失败：{failedJob.error || "未知错误"}
                  {failedJob.finished_at || failedJob.started_at ? (
                    <span style={{ opacity: 0.6, fontSize: 12 }}>
                      　（{new Date(
                        failedJob.finished_at || failedJob.started_at || "",
                      ).toLocaleString()}）
                    </span>
                  ) : null}
                </div>
              ) : null}

              {/* 横向 tab：按工作流顺序，不用再滚一长条 */}
              <nav
                style={{
                  ...CARD,
                  padding: "6px 8px",
                  display: "flex",
                  gap: 6,
                  flexWrap: "wrap",
                  alignItems: "center",
                }}
              >
                {TABS.map((t) => {
                  const on = tab === t.key;
                  const badge =
                    t.key === "content"
                      ? items.length
                      : t.key === "topics"
                        ? picked.size
                        : t.key === "monitor"
                          ? monitor?.summary.watched ?? 0
                          : publish?.publishable_count ?? 0;
                  return (
                    <button
                      key={t.key}
                      onClick={() => setTab(t.key)}
                      title={t.hint}
                      style={{
                        appearance: "none",
                        cursor: "pointer",
                        border: on ? `1px solid ${GOLD}66` : "1px solid rgba(255,255,255,.10)",
                        background: on ? `${GOLD}1a` : "transparent",
                        color: on ? GOLD : "inherit",
                        fontWeight: on ? 600 : 400,
                        borderRadius: 8,
                        padding: "8px 14px",
                        fontSize: 14,
                        display: "flex",
                        alignItems: "center",
                        gap: 7,
                      }}
                    >
                      {t.label}
                      {badge > 0 ? (
                        <span style={{ ...BADGE, fontSize: 11, padding: "1px 6px", opacity: on ? 1 : 0.6 }}>
                          {badge}
                        </span>
                      ) : null}
                    </button>
                  );
                })}
                <span style={{ marginLeft: "auto", fontSize: 12, opacity: 0.5, paddingRight: 4 }}>
                  {TABS.find((t) => t.key === tab)?.hint}
                </span>
              </nav>

              {tab === "topics" ? (
                <>
                {/* 本簇产品（默认折叠） */}
                <section style={CARD}>
                  <button
                    onClick={() => setOpenProducts((v) => !v)}
                    style={SECTION_TOGGLE}
                  >
                    <span style={{ ...CHEVRON, transform: openProducts ? "rotate(90deg)" : "none" }}>
                      ▸
                    </span>
                    <strong>本簇产品</strong>
                    <span style={COUNT_PILL}>{products.length}</span>
                    {pendingCount > 0 ? (
                      <span style={{ ...BADGE, color: GOLD, borderColor: `${GOLD}66` }}>
                        {pendingCount} 新
                      </span>
                    ) : null}
                    <span style={{ marginLeft: "auto", fontSize: 12, opacity: 0.55 }}>
                      同类目共用一个簇，避免重复内容
                    </span>
                  </button>
                  {openProducts ? (
                    <div style={SECTION_BODY}>
                      {products.length === 0 ? (
                        <p style={HINT}>暂无产品。</p>
                      ) : (
                        <ul style={{ ...RESET_LIST, gap: 6 }}>
                          {products.map((p) => (
                            <li key={p.product_id} style={ROW}>
                              <span style={SKU_PILL}>{p.sku || "—"}</span>
                              <span style={{ flex: 1, minWidth: 120 }}>
                                {p.name || p.product_id.slice(0, 8)}
                              </span>
                              {p.is_pending ? (
                                <span style={{ ...BADGE, color: GOLD, borderColor: `${GOLD}66` }}>
                                  新
                                </span>
                              ) : null}
                              {p.differentiated ? (
                                <span
                                  style={{ ...BADGE, color: GOLD, borderColor: `${GOLD}66` }}
                                  title={`独有卖点：${p.unique_points.join(", ")}`}
                                >
                                  差异较大
                                </span>
                              ) : null}
                              <button
                                onClick={() => void handleSpotlight(p)}
                                disabled={spotlightBusy !== null}
                                style={GHOST_BTN}
                              >
                                {spotlightBusy === p.product_id ? "生成中…" : "加一篇专属文章"}
                              </button>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  ) : null}
                </section>
  
                {/* 话题采集（默认展开——这里是主操作区） */}
                <section style={CARD}>
                  <button onClick={() => setOpenTopics((v) => !v)} style={SECTION_TOGGLE}>
                    <span style={{ ...CHEVRON, transform: openTopics ? "rotate(90deg)" : "none" }}>
                      ▸
                    </span>
                    <strong>话题采集</strong>
                    <span style={{ ...BADGE, color: GOLD, borderColor: `${GOLD}66` }}>
                      已选 {picked.size}
                    </span>
                    <span style={COUNT_PILL}>{candidates.length} 候选</span>
                    <span style={{ marginLeft: "auto", fontSize: 12, opacity: 0.55 }}>
                      候选来自真实搜索需求，你挑，AI 只写选中的
                    </span>
                  </button>
                  {openTopics ? (
                    <div style={SECTION_BODY}>
                      <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
                        <button
                          onClick={() => selectedId && void loadTopics(selectedId)}
                          style={GHOST_BTN}
                        >
                          刷新候选
                        </button>
                        <button
                          onClick={() => void handleMineQuestions()}
                          disabled={busy}
                          style={PRIMARY_BTN}
                          title="从类目词出发真打 Serper，并把「大家还在问」展开第二层——产品名碰不到的品类问句在这里"
                        >
                          {busy ? "深挖中…" : "深挖选题"}
                        </button>
                        <button
                          onClick={() => void handleProbeTerrain()}
                          disabled={busy || probeBusy || candidates.length === 0}
                          style={GHOST_BTN}
                          title="查这些候选问句的自然搜索阵地：谁在占位、打不打得动"
                        >
                          {probeBusy ? "探测中…" : "探测阵地"}
                        </button>
                        <button
                          onClick={() => void handleSavePicks()}
                          disabled={busy}
                          style={PRIMARY_BTN}
                        >
                          保存选题
                        </button>
                      </div>
                      {mineReport ? (
                        <p style={{ ...HINT, color: GREEN }}>{mineReport}</p>
                      ) : null}
                      {loadingTopics ? (
                        <p style={HINT}>加载候选中…</p>
                      ) : candidates.length === 0 ? (
                        <p style={HINT}>
                          无需求数据——先在 K 跑该产品的 FAQ 研究，或在 F 富化该类目关键词。
                        </p>
                      ) : (
                        <ul style={{ ...RESET_LIST, gap: 6, maxHeight: 340, overflowY: "auto" }}>
                          {candidates.map((c, i) => {
                            const k = normQ(c.question);
                            const on = picked.has(k);
                            return (
                              <li key={i}>
                                <label style={{ ...ROW, ...(on ? ROW_ON : {}), cursor: "pointer" }}>
                                  <input type="checkbox" checked={on} onChange={() => togglePick(c)} />
                                  <span style={{ flex: 1, minWidth: 120 }}>{c.question}</span>
                                  <span style={SKU_PILL}>{c.source === "k_faq" ? "K" : "F"}</span>
                                  <span style={{ ...BADGE, opacity: 0.85 }}>
                                    {INTENT_LABEL[c.intent] || c.intent}
                                  </span>
                                  {c.terrain ? (
                                    <span
                                      style={{
                                        ...BADGE,
                                        color:
                                          c.terrain.terrain === "soft"
                                            ? GREEN
                                            : c.terrain.terrain === "hard"
                                              ? RED
                                              : GOLD,
                                      }}
                                      title={`前排：${c.terrain.top_domains.join(" · ")}`}
                                    >
                                      {c.terrain.terrain === "soft"
                                        ? "软"
                                        : c.terrain.terrain === "hard"
                                          ? "硬"
                                          : "中"}
                                      {c.terrain.attackability}
                                    </span>
                                  ) : null}
                                  <span style={{ ...SCORE_PILL }}>{c.score}</span>
                                </label>
                              </li>
                            );
                          })}
                        </ul>
                      )}
                    </div>
                  ) : null}
                </section>
  
                </>
              ) : null}

              {tab === "content" ? (
                <>
                {/* 内容 */}
                <section style={CARD}>
                  <div style={{ ...SECTION_TOGGLE, cursor: "default" }}>
                    <strong>内容</strong>
                    <span style={COUNT_PILL}>{items.length}</span>
                    <span style={{ marginLeft: "auto", fontSize: 12, opacity: 0.55 }}>
                      审核通过后才能进入发布
                    </span>
                  </div>
                  <div style={SECTION_BODY}>
                    {items.length === 0 ? (
                      <p style={HINT}>
                        {busyGenerating ? "内容生成中，稍候…" : "还没有内容——先选题，再点「生成内容」。"}
                      </p>
                    ) : (
                      <div style={{ display: "grid", gap: 12 }}>
                        {items.map((item) => {
                          const rev = REVIEW_STATUS[item.review_status] ?? {
                            label: item.review_status,
                            color: MUTED,
                          };
                          return (
                            <article key={item.id} style={ITEM_CARD}>
                              <header style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                                <span style={TYPE_PILL}>
                                  {ITEM_TYPE_LABEL[item.item_type] || item.item_type}
                                </span>
                                <strong style={{ flex: 1, minWidth: 160 }}>{item.title}</strong>
                                <span
                                  style={{
                                    ...BADGE,
                                    color: auditClean(item) ? GREEN : RED,
                                    borderColor: auditClean(item) ? `${GREEN}66` : `${RED}66`,
                                  }}
                                  title="机器自动查:品牌是否干净、有无中文、数字是否有证据"
                                >
                                  自动审查 {auditClean(item) ? "✓" : "✗"}
                                </span>
                                <span
                                  style={{ ...BADGE, color: rev.color, borderColor: `${rev.color}66` }}
                                  title="你的人工审核状态"
                                >
                                  {item.review_status === "pending" ? "待你审核" : rev.label}
                                </span>
                              </header>
  
                              {item.body?.sections?.map((s, i) => (
                                <div key={i} style={{ marginTop: 8 }}>
                                  {s.heading ? <div style={{ fontWeight: 600 }}>{s.heading}</div> : null}
                                  {s.body ? <p style={BODY_TEXT}>{s.body}</p> : null}
                                </div>
                              ))}
                              {item.body?.answer_blocks?.map((b, i) => (
                                <div key={i} style={{ marginTop: 8 }}>
                                  {b.question ? (
                                    <div style={{ fontWeight: 600 }}>Q: {b.question}</div>
                                  ) : null}
                                  {b.answer ? <p style={BODY_TEXT}>A: {b.answer}</p> : null}
                                </div>
                              ))}
  
                              {!auditClean(item) && item.brand_audit ? (
                                <div style={{ ...BANNER, marginTop: 10, fontSize: 12, color: RED, borderColor: "rgba(221,109,99,0.45)" }}>
                                  {(item.brand_audit.brand_violations?.length ?? 0) > 0 ? "含第三方品牌词 " : ""}
                                  {(item.brand_audit.cjk_surfaces?.length ?? 0) > 0 ? "含中文 " : ""}
                                  {(item.brand_audit.ungrounded_numbers?.length ?? 0) > 0
                                    ? `无证据数字：${item.brand_audit.ungrounded_numbers?.map((u) => u.number).join(", ")}`
                                    : ""}
                                </div>
                              ) : null}
  
                              {(item.source_product_labels?.length ?? 0) > 0 ? (
                                <div style={{ marginTop: 8, fontSize: 12, opacity: 0.65, display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                                  <span>内链产品：</span>
                                  {item.source_product_labels?.map((label, i) => (
                                    <span key={i} style={SKU_PILL}>{label}</span>
                                  ))}
                                </div>
                              ) : null}
  
                              <footer style={{ display: "flex", gap: 8, marginTop: 10, alignItems: "center" }}>
                                <button onClick={() => void handleReview(item, "approved")} style={GHOST_BTN}>
                                  批准
                                </button>
                                <button onClick={() => void handleReview(item, "rejected")} style={GHOST_BTN}>
                                  驳回
                                </button>
                                <span style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
                                  {(item.analysis?.risks?.length ?? 0) > 0 ? (
                                    <button
                                      onClick={() => void handleRevise(item)}
                                      disabled={reviseBusy !== null}
                                      style={{ ...GHOST_BTN, borderColor: `${GOLD}66`, color: GOLD }}
                                      title="把批评喂回去重写这一篇（绝不编造事实；改不了的会说明原因）"
                                    >
                                      {reviseBusy === item.id ? "重写中…" : "按批评重写"}
                                    </button>
                                  ) : null}
                                  {item.analysis ? (
                                    <button
                                      onClick={() => toggleAnalysis(item.id)}
                                      style={{
                                        ...GHOST_BTN,
                                        borderColor: `${BLUE}66`,
                                        color: BLUE,
                                      }}
                                    >
                                      {openAnalysis.has(item.id) ? "收起解读 ▲" : "AI 解读 ▼"}
                                    </button>
                                  ) : (
                                    <button
                                      onClick={() => void handleAnalyze(item)}
                                      disabled={analyzeBusy !== null}
                                      style={GHOST_BTN}
                                    >
                                      {analyzeBusy === item.id ? "解读中…" : "生成 AI 解读"}
                                    </button>
                                  )}
                                </span>
                              </footer>
  
                              {item.revision ? (
                                <div style={REVISION_PANEL}>
                                  <div style={{ fontSize: 11, fontWeight: 700, opacity: 0.75, marginBottom: 4 }}>
                                    已按批评重写（第 {item.revision.round ?? 1} 轮）
                                  </div>
                                  {(item.revision.addressed?.length ?? 0) > 0 ? (
                                    <ul style={{ margin: "2px 0 6px", paddingLeft: 18, fontSize: 12.5, opacity: 0.9 }}>
                                      {item.revision.addressed?.map((a, i) => (
                                        <li key={i} style={{ color: GREEN }}>{a}</li>
                                      ))}
                                    </ul>
                                  ) : null}
                                  {(item.revision.unaddressed?.length ?? 0) > 0 ? (
                                    <div>
                                      <div style={{ fontSize: 11, fontWeight: 700, color: GOLD, marginBottom: 2 }}>
                                        改不了的（不编造事实）
                                      </div>
                                      <ul style={{ margin: "2px 0", paddingLeft: 18, fontSize: 12.5, opacity: 0.9 }}>
                                        {item.revision.unaddressed?.map((u, i) => (
                                          <li key={i}>
                                            {u.critique}
                                            <span style={{ opacity: 0.75 }}>　—　{u.reason}</span>
                                            {u.needs_data && u.missing_fact ? (
                                              <span style={{ ...BADGE, color: GOLD, borderColor: `${GOLD}66`, marginLeft: 6 }}>
                                                需补数据：{u.missing_fact}
                                              </span>
                                            ) : null}
                                          </li>
                                        ))}
                                      </ul>
                                    </div>
                                  ) : null}
                                </div>
                              ) : null}
  
                              {item.analysis && openAnalysis.has(item.id) ? (
                                <div style={ANALYSIS_PANEL}>
                                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                                    <strong style={{ color: BLUE, fontSize: 13 }}>AI 解读</strong>
                                    <span style={{ ...COUNT_PILL, opacity: 0.7 }}>
                                      {item.analysis.model || "deepseek"}
                                    </span>
                                    <button
                                      onClick={() => void handleAnalyze(item)}
                                      disabled={analyzeBusy !== null}
                                      style={{ ...GHOST_BTN, marginLeft: "auto" }}
                                    >
                                      {analyzeBusy === item.id ? "重新解读中…" : "重新解读"}
                                    </button>
                                    <button onClick={() => toggleAnalysis(item.id)} style={GHOST_BTN}>
                                      关闭
                                    </button>
                                  </div>
                                  {item.analysis.translation ? (
                                    <div style={ANALYSIS_BLOCK}>
                                      <div style={ANALYSIS_LABEL}>中文翻译</div>
                                      <p style={{ ...BODY_TEXT, whiteSpace: "pre-wrap" }}>
                                        {item.analysis.translation}
                                      </p>
                                    </div>
                                  ) : null}
                                  {item.analysis.geo_role ? (
                                    <div style={ANALYSIS_BLOCK}>
                                      <div style={ANALYSIS_LABEL}>在 GEO 里的作用</div>
                                      <p style={BODY_TEXT}>{item.analysis.geo_role}</p>
                                    </div>
                                  ) : null}
                                  {item.analysis.why_written_this_way ? (
                                    <div style={ANALYSIS_BLOCK}>
                                      <div style={ANALYSIS_LABEL}>为什么这么写</div>
                                      <p style={BODY_TEXT}>{item.analysis.why_written_this_way}</p>
                                    </div>
                                  ) : null}
                                  {(item.analysis.strengths?.length ?? 0) > 0 ? (
                                    <div style={ANALYSIS_BLOCK}>
                                      <div style={{ ...ANALYSIS_LABEL, color: GREEN }}>优点</div>
                                      <ul style={{ margin: "2px 0", paddingLeft: 18, fontSize: 13, opacity: 0.9 }}>
                                        {item.analysis.strengths?.map((s, i) => <li key={i}>{s}</li>)}
                                      </ul>
                                    </div>
                                  ) : null}
                                  {(item.analysis.risks?.length ?? 0) > 0 ? (
                                    <div style={ANALYSIS_BLOCK}>
                                      <div style={{ ...ANALYSIS_LABEL, color: GOLD }}>可改进 / 风险</div>
                                      <ul style={{ margin: "2px 0", paddingLeft: 18, fontSize: 13, opacity: 0.9 }}>
                                        {item.analysis.risks?.map((s, i) => <li key={i}>{s}</li>)}
                                      </ul>
                                    </div>
                                  ) : null}
                                </div>
                              ) : null}
                            </article>
                          );
                        })}
                      </div>
                    )}
                  </div>
                </section>
                {/* 批评汇总：模块级信号 */}
                <section style={CARD}>
                  <button onClick={() => setOpenSummary((v) => !v)} style={SECTION_TOGGLE}>
                    <span style={{ ...CHEVRON, transform: openSummary ? "rotate(90deg)" : "none" }}>
                      ▸
                    </span>
                    <strong>批评汇总</strong>
                    {summary ? (
                      <span style={COUNT_PILL}>{summary.critique_count} 条批评</span>
                    ) : null}
                    {(summary?.data_gaps?.length ?? 0) > 0 ? (
                      <span style={{ ...BADGE, color: GOLD, borderColor: `${GOLD}66` }}>
                        {summary?.data_gaps.length} 处需补数据
                      </span>
                    ) : null}
                    <span style={{ marginLeft: "auto", fontSize: 12, opacity: 0.55 }}>
                      反复出现的批评 = 该改写作规范，不是改单篇
                    </span>
                  </button>
                  {openSummary ? (
                    <div style={SECTION_BODY}>
                      <button
                        onClick={() => void handleSummary()}
                        disabled={summaryBusy}
                        style={{ ...PRIMARY_BTN, marginBottom: 10 }}
                      >
                        {summaryBusy ? "汇总中…" : summary ? "重新汇总" : "生成批评汇总"}
                      </button>
                      {!summary ? (
                        <p style={HINT}>点上面按钮，把所有内容的批评聚在一起看规律。</p>
                      ) : (
                        <>
                          {summary.patterns.length === 0 ? (
                            <p style={HINT}>没有发现反复出现的模式（批评都是个别问题）。</p>
                          ) : (
                            <div style={{ display: "grid", gap: 8 }}>
                              <div style={{ ...ANALYSIS_LABEL, color: GOLD }}>
                                反复出现的问题（该改写作规范）
                              </div>
                              {summary.patterns.map((pt, i) => (
                                <div key={i} style={ROW}>
                                  <span style={{ ...BADGE, color: GOLD, borderColor: `${GOLD}66` }}>
                                    {pt.affected_count} 篇
                                  </span>
                                  <span style={{ flex: 1, minWidth: 140 }}>
                                    <div style={{ fontWeight: 600 }}>{pt.pattern}</div>
                                    {pt.suggested_fix ? (
                                      <div style={{ fontSize: 12.5, opacity: 0.8, marginTop: 2 }}>
                                        建议：{pt.suggested_fix}
                                      </div>
                                    ) : null}
                                  </span>
                                </div>
                              ))}
                            </div>
                          )}
                          {summary.data_gaps.length > 0 ? (
                            <div style={{ display: "grid", gap: 8, marginTop: 14 }}>
                              <div style={{ ...ANALYSIS_LABEL, color: BLUE }}>
                                需要补进 K 的数据（重写也修不了）
                              </div>
                              {summary.data_gaps.map((g, i) => (
                                <div key={i} style={ROW}>
                                  <span style={{ ...BADGE, color: BLUE, borderColor: `${BLUE}66` }}>
                                    {g.missing_fact}
                                  </span>
                                  <span style={{ flex: 1, minWidth: 140, fontSize: 12.5, opacity: 0.85 }}>
                                    影响 {g.items.length} 篇
                                    {g.reason ? `　—　${g.reason}` : ""}
                                  </span>
                                </div>
                              ))}
                            </div>
                          ) : null}
                        </>
                      )}
                    </div>
                  ) : null}
                </section>
  
                </>
              ) : null}

              {tab === "publish" ? (
                <>
                {/* 发布到站点 */}
                <section style={CARD}>
                  <div style={{ ...SECTION_TOGGLE, cursor: "default" }}>
                    <strong>发布到站点</strong>
                    {publish ? (
                      <span style={COUNT_PILL}>
                        {publish.publishable_count}/{publish.total_count} 篇已批准
                      </span>
                    ) : null}
                    <span style={{ marginLeft: "auto", fontSize: 12, opacity: 0.55 }}>
                      只发已批准的；首发落草稿，你在 WP 后台点发布
                    </span>
                    <button
                      onClick={() => void handlePublish()}
                      disabled={publishBusy || !publish?.ready}
                      style={PRIMARY_BTN}
                    >
                      {publishBusy
                        ? "派单中…"
                        : `发布 ${publish?.publishable_count ?? 0} 篇`}
                    </button>
                  </div>
                  <div style={SECTION_BODY}>
                    {publish && publish.jobs.some((j) => j.status === "success") ? (
                      <div
                        style={{
                          ...BANNER,
                          borderColor: `${GREEN}44`,
                          background: `${GREEN}10`,
                          fontSize: 12.5,
                        }}
                      >
        已发出的文章落在 WP 后台的草稿里，等你过目后手动发布。文章之间的内链、以及{" "}
                        <a href="https://barongyekhna.com/guides/" target="_blank" rel="noreferrer">
                          /guides/ 指南主页
                        </a>{" "}
                        都已经写成发布后的正式网址。
                        <strong> 改了内容想重新推送，直接再点一次「发布」即可</strong>
                        ——会原地更新同一批文章，不会建出重复。
                      </div>
                    ) : null}
                    {publish && publish.blockers.length > 0 ? (
                      <div style={{ ...BANNER, borderColor: `${GOLD}66`, background: `${GOLD}14` }}>
                        <strong style={{ color: GOLD }}>还不能发布：</strong>
                        <ul style={{ margin: "6px 0 0", paddingLeft: 18, fontSize: 13 }}>
                          {publish.blockers.map((b, i) => (
                            <li key={i}>{b}</li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                    {publish && publish.jobs.length > 0 ? (
                      <ul style={{ ...RESET_LIST, gap: 6, marginTop: 10 }}>
                        {publish.jobs.slice(0, 5).map((j) => (
                          <li key={j.job_id} style={ROW}>
                            <span
                              style={{
                                ...BADGE,
                                color:
                                  j.status === "success"
                                    ? GREEN
                                    : j.status === "failed"
                                      ? RED
                                      : GOLD,
                              }}
                            >
                              {j.status}
                            </span>
                            <span style={{ flex: 1, minWidth: 140, fontSize: 12.5, opacity: 0.85 }}>
                              {j.finished_at || j.created_at || ""}
                              {j.error ? `　—　${j.error}` : ""}
                            </span>
                            {j.published_items.slice(0, 3).map((it, i) =>
                              it.url ? (
                                <a
                                  key={i}
                                  href={it.url}
                                  target="_blank"
                                  rel="noreferrer"
                                  style={{ ...BADGE, color: BLUE, borderColor: `${BLUE}66` }}
                                >
                                  查看 {i + 1}
                                </a>
                              ) : null,
                            )}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p style={HINT}>还没有发布过。</p>
                    )}
                  </div>
                </section>
  
                {/* 内链网：文章内链（自动）+ 产品页链接（人工，因为它是投放落地页）。
                    和 SeoDeck 挂的是同一个组件——内链网本来就是跨 GEO/SEO 的一件事。 */}
                <section style={CARD}>
                  <div style={{ ...SECTION_TOGGLE, cursor: "default" }}>
                    <strong>内链网</strong>
                    <span style={{ marginLeft: "auto", fontSize: 12, opacity: 0.55 }}>
                      产品页 · 指南 · 工艺文 · 博文，四边互链
                    </span>
                  </div>
                  <div style={SECTION_BODY}>
                    <LinkNetPanel />
                  </div>
                </section>

                {/* 内容自检：标了完成却没有产物。全绿时几乎不占地方。 */}
                <section style={CARD}>
                  <div style={SECTION_BODY}>
                    <ContentHealthPanel />
                  </div>
                </section>
  
                </>
              ) : null}

              {tab === "monitor" ? (
                <>
                {/* 阵地监测（里程碑4）：买家问句的自然搜索阵地 */}
                <section style={CARD}>
                  <div style={{ ...SECTION_TOGGLE, cursor: "default" }}>
                    <strong>阵地监测</strong>
                    {monitor ? (
                      <span style={COUNT_PILL}>
                        {monitor.summary.watched} 条在监测
                      </span>
                    ) : null}
                    <span style={{ marginLeft: "auto", fontSize: 12, opacity: 0.55 }}>
                      每条问句一次 Serper，上限 {monitor?.budget?.daily_budget ?? "—"}/天
                    </span>
                    <button
                      onClick={() => void handleMonitor("seed")}
                      disabled={!!monitorBusy || !selectedId}
                      style={GHOST_BTN}
                    >
                      {monitorBusy === "seed" ? "导入中…" : "导入本簇选题"}
                    </button>
                    <button
                      onClick={() => void handleMonitor("run")}
                      disabled={!!monitorBusy || !monitor?.summary.watched}
                      style={PRIMARY_BTN}
                    >
                      {monitorBusy === "run" ? "监测中…" : "立即监测"}
                    </button>
                  </div>
                  <div style={SECTION_BODY}>
                    <p style={HINT}>
                      Serper 看不到 AI Overview，所以这里测的是 AI 答案取材的那层——
                      自然搜索阵地：我们排第几、谁在占位、这条问句软不软。
                      <strong> 可攻分越高越值得写。</strong>
                    </p>
                    {monitor && monitor.summary.checked > 0 ? (
                      <div style={{ ...ROW, gap: 14, marginTop: 8, fontSize: 12.5 }}>
                        <span>已检 <strong>{monitor.summary.checked}</strong></span>
                        <span>我们上榜 <strong style={{ color: monitor.summary.ranked ? GREEN : RED }}>
                          {monitor.summary.ranked}
                        </strong></span>
                        <span>软阵地待攻 <strong style={{ color: GOLD }}>
                          {monitor.summary.soft_unclaimed}
                        </strong></span>
                        <span>最好名次 <strong>{monitor.summary.best_position ?? "—"}</strong></span>
                      </div>
                    ) : null}
                    {monitor && monitor.questions.length > 0 ? (
                      <ul style={{ ...RESET_LIST, gap: 10, marginTop: 12 }}>
                        {monitor.questions.map((q) => (
                          <li
                            key={q.id}
                            style={{
                              border: `1px solid ${
                                q.terrain === "soft" ? `${GREEN}55` : "rgba(255,255,255,.08)"
                              }`,
                              borderRadius: 10,
                              padding: "10px 12px",
                            }}
                          >
                            <div style={{ ...ROW, gap: 10 }}>
                              <span
                                style={{
                                  ...BADGE,
                                  color:
                                    q.terrain === "soft"
                                      ? GREEN
                                      : q.terrain === "hard"
                                        ? RED
                                        : GOLD,
                                }}
                              >
                                {q.terrain === "soft"
                                  ? "软"
                                  : q.terrain === "hard"
                                    ? "硬"
                                    : q.terrain === "mixed"
                                      ? "中"
                                      : "未检"}
                                {q.attackability !== null ? ` ${q.attackability}` : ""}
                              </span>
                              <span style={{ ...BADGE, color: q.our_position ? GREEN : MUTED }}>
                                {q.our_position ? `#${q.our_position}` : "未上榜"}
                              </span>
                              <span style={{ fontSize: 13.5 }}>{q.question}</span>
                            </div>
                            {q.top_results.length > 0 ? (
                              <div style={{ fontSize: 12, opacity: 0.6, marginTop: 6 }}>
                                前排：
                                {q.top_results.slice(0, 5).map((r, i) => (
                                  <span key={r.url}>
                                    {i > 0 ? " · " : " "}
                                    {r.domain}
                                  </span>
                                ))}
                              </div>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p style={HINT}>
                        还没有监测数据——先「导入本簇选题」，再点「立即监测」。
                      </p>
                    )}
                  </div>
                </section>
  
                </>
              ) : null}

            </>
          )}
        </main>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ styles */

const SHELL: React.CSSProperties = { display: "grid", gap: 14 };
const GRID: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(240px, 300px) minmax(0, 1fr)",
  gap: 16,
  alignItems: "start",
};
const CARD: React.CSSProperties = {
  background: "rgba(12, 20, 30, 0.55)",
  border: "1px solid rgba(120, 160, 200, 0.18)",
  borderRadius: 14,
  overflow: "hidden",
};
const STICKY_HEAD: React.CSSProperties = {
  padding: 16,
  position: "sticky",
  top: 8,
  zIndex: 2,
  backdropFilter: "blur(6px)",
};
const PANEL_HEAD: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  marginBottom: 12,
};
const SECTION_TOGGLE: React.CSSProperties = {
  width: "100%",
  display: "flex",
  alignItems: "center",
  gap: 8,
  flexWrap: "wrap",
  padding: "12px 16px",
  background: "rgba(255,255,255,0.02)",
  border: "none",
  borderBottom: "1px solid rgba(120,160,200,0.14)",
  color: "inherit",
  font: "inherit",
  cursor: "pointer",
  textAlign: "left",
};
const SECTION_BODY: React.CSSProperties = { padding: 14 };
const CHEVRON: React.CSSProperties = {
  display: "inline-block",
  transition: "transform 0.15s ease",
  opacity: 0.7,
  fontSize: 12,
};
const RESET_LIST: React.CSSProperties = {
  listStyle: "none",
  margin: 0,
  padding: 0,
  display: "grid",
};
const CLUSTER_BTN: React.CSSProperties = {
  width: "100%",
  display: "grid",
  gap: 5,
  padding: "10px 12px",
  borderRadius: 10,
  border: "1px solid rgba(120,160,200,0.14)",
  borderLeft: "3px solid transparent",
  background: "rgba(0,0,0,0.22)",
  color: "inherit",
  cursor: "pointer",
  textAlign: "left",
};
const CLUSTER_BTN_ON: React.CSSProperties = {
  background: "rgba(217,164,65,0.10)",
  border: "1px solid rgba(217,164,65,0.35)",
  borderLeft: "3px solid",
};
const CLUSTER_TITLE: React.CSSProperties = {
  fontWeight: 600,
  fontSize: 13.5,
  lineHeight: 1.35,
};
const CLUSTER_SUB: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 5,
  fontSize: 11.5,
  fontVariantNumeric: "tabular-nums",
};
const DOT: React.CSSProperties = {
  width: 6,
  height: 6,
  borderRadius: "50%",
  display: "inline-block",
};
const ROW: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "7px 10px",
  borderRadius: 8,
  border: "1px solid rgba(120,160,200,0.12)",
  background: "rgba(0,0,0,0.18)",
  fontSize: 13,
  flexWrap: "wrap",
};
const ROW_ON: React.CSSProperties = {
  border: "1px solid rgba(217,164,65,0.45)",
  background: "rgba(217,164,65,0.08)",
};
const ITEM_CARD: React.CSSProperties = {
  background: "rgba(8, 14, 22, 0.5)",
  border: "1px solid rgba(120, 160, 200, 0.14)",
  borderRadius: 10,
  padding: 14,
};
const ANALYSIS_PANEL: React.CSSProperties = {
  marginTop: 10,
  padding: 12,
  borderRadius: 10,
  border: `1px solid ${BLUE}44`,
  background: "rgba(63,127,201,0.07)",
  maxHeight: 420,
  overflowY: "auto",
};
const ANALYSIS_BLOCK: React.CSSProperties = { marginTop: 8 };
const REVISION_PANEL: React.CSSProperties = {
  marginTop: 10,
  padding: 10,
  borderRadius: 8,
  border: "1px solid rgba(217,164,65,0.3)",
  background: "rgba(217,164,65,0.06)",
};
const ANALYSIS_LABEL: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 700,
  letterSpacing: "0.04em",
  opacity: 0.75,
  marginBottom: 2,
};
const BANNER: React.CSSProperties = {
  border: "1px solid rgba(120,160,200,0.25)",
  borderRadius: 10,
  padding: "10px 14px",
  fontSize: 13,
  background: "rgba(0,0,0,0.2)",
};
const HINT: React.CSSProperties = { opacity: 0.6, fontSize: 13, margin: 0 };
const BODY_TEXT: React.CSSProperties = {
  margin: "2px 0",
  fontSize: 13,
  opacity: 0.9,
  lineHeight: 1.6,
};
const BADGE: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 600,
  padding: "2px 8px",
  borderRadius: 999,
  border: "1px solid rgba(120,160,200,0.3)",
  whiteSpace: "nowrap",
};
const COUNT_PILL: React.CSSProperties = {
  fontSize: 11,
  padding: "1px 8px",
  borderRadius: 999,
  background: "rgba(120,160,200,0.16)",
  fontVariantNumeric: "tabular-nums",
};
const SCORE_PILL: React.CSSProperties = {
  ...COUNT_PILL,
  fontFamily: "monospace",
  opacity: 0.75,
};
const SKU_PILL: React.CSSProperties = {
  fontSize: 10,
  fontWeight: 700,
  padding: "2px 7px",
  borderRadius: 5,
  background: "rgba(120,160,200,0.2)",
  fontFamily: "monospace",
  whiteSpace: "nowrap",
};
const TYPE_PILL: React.CSSProperties = {
  fontSize: 11,
  padding: "2px 8px",
  borderRadius: 6,
  background: "rgba(63,127,201,0.18)",
  color: BLUE,
  fontWeight: 600,
  whiteSpace: "nowrap",
};
const PRIMARY_BTN: React.CSSProperties = {
  padding: "8px 16px",
  borderRadius: 8,
  border: `1px solid ${GOLD}80`,
  background: `${GOLD}26`,
  color: GOLD,
  fontWeight: 600,
  cursor: "pointer",
  whiteSpace: "nowrap",
};
const GHOST_BTN: React.CSSProperties = {
  padding: "5px 12px",
  borderRadius: 7,
  border: "1px solid rgba(120,160,200,0.3)",
  background: "transparent",
  color: "inherit",
  cursor: "pointer",
  fontSize: 12,
  whiteSpace: "nowrap",
};
