"use client";

import {
  AlertTriangle,
  ArrowRight,
  ChevronDown,
  ChevronRight,
  FolderTree,
  ListChecks,
  LoaderCircle,
  PackagePlus,
  Play,
  RefreshCw,
  Search,
  ShieldAlert,
  Sparkles,
  Sprout,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  createCandidate,
  createRun,
  generateProfile,
  getCandidates,
  getKeywords,
  getProfile,
  getQuota,
  getRuns,
  getTree,
  importCandidateToK,
  reviewCandidate,
  reviewKeyword,
  searchTree,
  type CandidateItem,
  type KeywordItem,
  type ProfileResponse,
  type QuotaResponse,
  type RunItem,
  type TreeNode,
} from "./api";
import styles from "./EnrichmentDeck.module.css";

const RUN_POLL_MS = 5000;
const IDLE_POLL_MS = 30000;
const ROOT_KEY = "__root__";

type TreeRow = { node: TreeNode; depth: number };

function flattenTree(
  childrenByParent: Map<string, TreeNode[]>,
  expanded: Set<string>,
): TreeRow[] {
  const rows: TreeRow[] = [];
  const walk = (parentKey: string, depth: number) => {
    for (const node of childrenByParent.get(parentKey) ?? []) {
      rows.push({ node, depth });
      if (expanded.has(node.id)) {
        walk(node.id, depth + 1);
      }
    }
  };
  walk(ROOT_KEY, 0);
  return rows;
}

function runStatusLabel(status: string) {
  switch (status) {
    case "succeeded":
      return "完成";
    case "running":
      return "爬取中";
    case "queued":
      return "排队中";
    case "failed":
      return "失败";
    case "quota_exhausted":
      return "额度用尽·明天续";
    case "cancelled":
      return "已取消";
    default:
      return status;
  }
}

function runModeLabel(mode: string) {
  switch (mode) {
    case "full":
      return "爬词+找货";
    case "keywords_only":
      return "只爬词";
    case "sourcing_only":
      return "只找货";
    default:
      return mode;
  }
}

function keywordTypeLabel(type: string) {
  switch (type) {
    case "related":
      return "相关搜索";
    case "people_also_ask":
      return "用户在问";
    case "organic_title":
      return "SERP 标题";
    default:
      return type;
  }
}

function candidateStatusLabel(status: string) {
  switch (status) {
    case "pending_review":
      return "待审";
    case "approved":
      return "已放行";
    case "rejected":
      return "已拒绝";
    case "imported_to_k":
      return "已进 K";
    default:
      return status;
  }
}

function formatTime(value: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  return `${date.getMonth() + 1}/${date.getDate()} ${String(
    date.getHours(),
  ).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

export function EnrichmentDeck() {
  const [childrenByParent, setChildrenByParent] = useState<
    Map<string, TreeNode[]>
  >(new Map());
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [loadingIds, setLoadingIds] = useState<Set<string>>(new Set());
  const [treeLoading, setTreeLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<TreeNode[] | null>(null);
  const [profile, setProfile] = useState<ProfileResponse | null>(null);
  const [profileBusy, setProfileBusy] = useState(false);
  const [selected, setSelected] = useState<Map<string, TreeNode>>(new Map());
  const [activeNode, setActiveNode] = useState<TreeNode | null>(null);
  const [keywords, setKeywords] = useState<KeywordItem[]>([]);
  const [candidates, setCandidates] = useState<CandidateItem[]>([]);
  const [runs, setRuns] = useState<RunItem[]>([]);
  const [quota, setQuota] = useState<QuotaResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [form, setForm] = useState({
    title: "",
    source_url: "",
    price_cny: "",
    moq: "",
    supplier_name: "",
    weight_note: "",
  });

  const mounted = useRef(true);
  const pollTimer = useRef<number | null>(null);

  const loadChildren = useCallback(async (parentId: string | null) => {
    const key = parentId ?? ROOT_KEY;
    if (parentId === null) setTreeLoading(true);
    setLoadingIds((prev) => new Set(prev).add(key));
    try {
      const data = await getTree(parentId ?? undefined);
      if (mounted.current) {
        setChildrenByParent((prev) => {
          const next = new Map(prev);
          next.set(key, data.items);
          return next;
        });
        setError(null);
      }
    } catch (loadError) {
      if (mounted.current) {
        setError(loadError instanceof Error ? loadError.message : "类目树加载失败。");
      }
    } finally {
      if (mounted.current) {
        setLoadingIds((prev) => {
          const next = new Set(prev);
          next.delete(key);
          return next;
        });
        if (parentId === null) setTreeLoading(false);
      }
    }
  }, []);

  const toggleExpand = useCallback(
    (node: TreeNode) => {
      if (expanded.has(node.id)) {
        setExpanded((prev) => {
          const next = new Set(prev);
          next.delete(node.id);
          return next;
        });
        return;
      }
      setExpanded((prev) => new Set(prev).add(node.id));
      if (!childrenByParent.has(node.id)) {
        void loadChildren(node.id);
      }
    },
    [expanded, childrenByParent, loadChildren],
  );

  const refreshTree = useCallback(() => {
    setChildrenByParent(new Map());
    setExpanded(new Set());
    void loadChildren(null);
  }, [loadChildren]);

  const loadRunsAndQuota = useCallback(async () => {
    try {
      const [runData, quotaData] = await Promise.all([getRuns(20), getQuota()]);
      if (mounted.current) {
        setRuns(runData.runs);
        setQuota(quotaData);
      }
    } catch {
      // 台账/额度静默失败，不打断主流程
    }
  }, []);

  const loadDetail = useCallback(async (node: TreeNode) => {
    try {
      const [keywordData, candidateData] = await Promise.all([
        getKeywords({ categoryId: node.id, limit: 300 }),
        getCandidates({ categoryId: node.id, limit: 100 }),
      ]);
      if (mounted.current) {
        setKeywords(keywordData.items);
        setCandidates(candidateData.items);
      }
    } catch (detailError) {
      if (mounted.current) {
        setError(
          detailError instanceof Error ? detailError.message : "类目详情加载失败。",
        );
      }
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void loadChildren(null);
    void loadRunsAndQuota();
    return () => {
      mounted.current = false;
      if (pollTimer.current !== null) window.clearInterval(pollTimer.current);
    };
  }, [loadChildren, loadRunsAndQuota]);

  const hasActiveRun = useMemo(
    () => runs.some((run) => run.status === "running" || run.status === "queued"),
    [runs],
  );

  useEffect(() => {
    if (pollTimer.current !== null) window.clearInterval(pollTimer.current);
    pollTimer.current = window.setInterval(
      () => void loadRunsAndQuota(),
      hasActiveRun ? RUN_POLL_MS : IDLE_POLL_MS,
    );
    return () => {
      if (pollTimer.current !== null) window.clearInterval(pollTimer.current);
    };
  }, [hasActiveRun, loadRunsAndQuota]);

  // 运行结束沿（running→idle）自动刷新右栏详情——找货/爬词完成后结果自己出现
  const prevActiveRun = useRef(false);
  useEffect(() => {
    if (prevActiveRun.current && !hasActiveRun && activeNode) {
      void loadDetail(activeNode);
    }
    prevActiveRun.current = hasActiveRun;
  }, [hasActiveRun, activeNode, loadDetail]);

  const toggleSelect = useCallback((node: TreeNode) => {
    setSelected((prev) => {
      const next = new Map(prev);
      if (next.has(node.id)) {
        next.delete(node.id);
      } else {
        next.set(node.id, node);
      }
      return next;
    });
  }, []);

  const openDetail = useCallback(
    (node: TreeNode) => {
      setActiveNode(node);
      setShowAddForm(false);
      setProfile(null);
      void loadDetail(node);
      void getProfile(node.id)
        .then((data) => {
          if (mounted.current) setProfile(data);
        })
        .catch(() => {
          // 画像读取失败静默（右栏按钮可重新生成）
        });
    },
    [loadDetail],
  );

  const handleGenerateProfile = useCallback(async () => {
    if (!activeNode) return;
    setProfileBusy(true);
    setError(null);
    try {
      const data = await generateProfile(activeNode.id);
      setProfile(data);
    } catch (profileError) {
      setError(
        profileError instanceof Error ? profileError.message : "类目画像生成失败。",
      );
    } finally {
      setProfileBusy(false);
    }
  }, [activeNode]);

  const handleSearch = useCallback(async () => {
    const q = searchQuery.trim();
    if (!q) {
      setSearchResults(null);
      return;
    }
    setTreeLoading(true);
    try {
      const data = await searchTree(q);
      if (mounted.current) setSearchResults(data.items);
    } catch (searchError) {
      if (mounted.current) {
        setError(searchError instanceof Error ? searchError.message : "搜索失败。");
      }
    } finally {
      if (mounted.current) setTreeLoading(false);
    }
  }, [searchQuery]);

  const handleStartRun = useCallback(async () => {
    if (selected.size === 0) return;
    setBusy("__run__");
    setError(null);
    setNotice(null);
    try {
      const run = await createRun([...selected.keys()], "full");
      setNotice(
        `富化运行已发起：${run.categories_total} 个类目节点排队「爬词 + 1688 找货」，` +
          "进度看下方台账（额度用尽会温和暂停，明天重跑自动去重续上；" +
          "1688 密钥未绑时找货段自动跳过、词照收）。",
      );
      setSelected(new Map());
      await loadRunsAndQuota();
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : "运行发起失败。");
    } finally {
      setBusy(null);
    }
  }, [selected, loadRunsAndQuota]);

  const handleSourceCategory = useCallback(async () => {
    if (!activeNode) return;
    setBusy("__source__");
    setError(null);
    setNotice(null);
    try {
      await createRun([activeNode.id], "sourcing_only");
      setNotice(
        `「${activeNode.name_zh || activeNode.name}」已排队 1688 找货` +
          "（用该类目现有关键词生成中文采购词，约 1-2 分钟）——完成后本页自动刷新，候选出现在下方候选池。",
      );
      await loadRunsAndQuota();
    } catch (sourceError) {
      setError(
        sourceError instanceof Error ? sourceError.message : "1688 找货发起失败。",
      );
    } finally {
      setBusy(null);
    }
  }, [activeNode, loadRunsAndQuota]);

  const handleKeywordReview = useCallback(
    async (keyword: KeywordItem, status: "approved" | "rejected") => {
      setBusy(keyword.id);
      try {
        const updated = await reviewKeyword(keyword.id, status);
        setKeywords((prev) =>
          prev.map((item) => (item.id === updated.id ? updated : item)),
        );
      } catch (reviewError) {
        setError(
          reviewError instanceof Error ? reviewError.message : "关键词审核失败。",
        );
      } finally {
        setBusy(null);
      }
    },
    [],
  );

  const handleCandidateAction = useCallback(
    async (candidate: CandidateItem, action: "approve" | "reject" | "reopen") => {
      setBusy(candidate.id);
      try {
        const updated = await reviewCandidate(candidate.id, action);
        setCandidates((prev) =>
          prev.map((item) => (item.id === updated.id ? updated : item)),
        );
      } catch (actionError) {
        setError(
          actionError instanceof Error ? actionError.message : "候选审核失败。",
        );
      } finally {
        setBusy(null);
      }
    },
    [],
  );

  const handleImportToK = useCallback(
    async (candidate: CandidateItem) => {
      setBusy(candidate.id);
      setNotice(null);
      try {
        const result = await importCandidateToK(candidate.id);
        setNotice(
          result.deduped
            ? "该候选之前已进过 K（已按去重处理）。"
            : "已搬进 K 产品知识库（channel=dtc，类目直绑）——去 K 里走文案/作图/上架链。",
        );
        if (activeNode) await loadDetail(activeNode);
      } catch (importError) {
        setError(importError instanceof Error ? importError.message : "进 K 失败。");
      } finally {
        setBusy(null);
      }
    },
    [activeNode, loadDetail],
  );

  const handleAddCandidate = useCallback(async () => {
    if (!activeNode || !form.title.trim()) return;
    setBusy("__add__");
    setError(null);
    try {
      await createCandidate({
        category_id: activeNode.id,
        title: form.title.trim(),
        source_url: form.source_url.trim() || undefined,
        price_cny: form.price_cny.trim() || undefined,
        moq: form.moq.trim() ? Number(form.moq.trim()) : undefined,
        supplier_name: form.supplier_name.trim() || undefined,
        weight_note: form.weight_note.trim() || undefined,
      });
      setForm({
        title: "",
        source_url: "",
        price_cny: "",
        moq: "",
        supplier_name: "",
        weight_note: "",
      });
      setShowAddForm(false);
      await loadDetail(activeNode);
    } catch (addError) {
      setError(addError instanceof Error ? addError.message : "候选创建失败。");
    } finally {
      setBusy(null);
    }
  }, [activeNode, form, loadDetail]);

  const treeRows = useMemo(
    () => flattenTree(childrenByParent, expanded),
    [childrenByParent, expanded],
  );
  const latestRun = runs[0];

  return (
    <div className={styles.deck}>
      {/* ---- 统计行 ---- */}
      <div className={styles.statRow}>
        <div className={styles.statCard}>
          <span className={styles.statLabel}>Serper 今日额度</span>
          <span className={styles.statValue}>
            {quota?.serper
              ? `${quota.serper.used}/${quota.serper.unlimited ? "∞" : quota.serper.budget}`
              : "—"}
          </span>
        </div>
        <div className={styles.statCard}>
          <span className={styles.statLabel}>1688 今日额度</span>
          <span className={styles.statValue}>
            {quota?.alibaba1688_app_calls
              ? `${quota.alibaba1688_app_calls.used}/${
                  quota.alibaba1688_app_calls.unlimited
                    ? "∞"
                    : quota.alibaba1688_app_calls.budget
                }`
              : "—"}
          </span>
        </div>
        <div className={styles.statCard} data-tone={latestRun?.status === "running" ? "flight" : undefined}>
          <span className={styles.statLabel}>最近运行</span>
          <span className={styles.statValue}>
            {latestRun
              ? `${runStatusLabel(latestRun.status)} ${latestRun.categories_done}/${latestRun.categories_total}`
              : "—"}
          </span>
        </div>
        <div className={styles.statCard} data-tone="success">
          <span className={styles.statLabel}>已选节点</span>
          <span className={styles.statValue}>{selected.size}</span>
        </div>
      </div>

      {error ? (
        <div className={styles.state} role="alert">
          <AlertTriangle aria-hidden="true" size={18} />
          <span>{error}</span>
        </div>
      ) : null}
      {notice ? <p className={styles.notice}>{notice}</p> : null}

      <div className={styles.columns}>
        {/* ---- 左：类目树 ---- */}
        <section className={styles.panel} aria-label="谷歌类目树">
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>
              <FolderTree aria-hidden="true" size={16} />
              谷歌类目树（与 K 共享 · 5595 节点）
            </span>
            <button
              className="primary-button"
              disabled={busy !== null || selected.size === 0}
              onClick={() => void handleStartRun()}
              title={
                selected.size
                  ? `对 ${selected.size} 个选中节点（含全部子类目）爬词 + 1688 找货`
                  : "先勾选类目节点"
              }
              type="button"
            >
              {busy === "__run__" ? (
                <LoaderCircle aria-hidden="true" className="spin" size={15} />
              ) : (
                <Play aria-hidden="true" size={15} />
              )}
              富化（{selected.size}）
            </button>
          </div>

          <div className={styles.searchRow}>
            <input
              className={styles.searchInput}
              onChange={(event) => setSearchQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void handleSearch();
              }}
              placeholder="搜类目，如 camping、shower…"
              value={searchQuery}
            />
            <button
              className="secondary-button"
              onClick={() => void handleSearch()}
              type="button"
            >
              <Search aria-hidden="true" size={14} />
              搜索
            </button>
          </div>

          {searchResults !== null ? (
            <p className={styles.searchHint}>
              搜索结果 {searchResults.length} 条 ·{" "}
              <button
                className={styles.linkButton}
                onClick={() => {
                  setSearchResults(null);
                  setSearchQuery("");
                }}
                type="button"
              >
                返回类目树
              </button>
            </p>
          ) : (
            <p className={styles.searchHint}>
              点 ▸ 原地展开子类目 ·{" "}
              <button
                className={styles.linkButton}
                onClick={refreshTree}
                type="button"
              >
                刷新树
              </button>
            </p>
          )}

          {treeLoading ? (
            <div className={styles.state}>
              <LoaderCircle aria-hidden="true" className="spin" size={18} />
              <span>正在加载…</span>
            </div>
          ) : (searchResults ?? treeRows).length === 0 ? (
            <div className={styles.emptyHint}>
              <p>{searchResults !== null ? "没有匹配的类目。" : "类目树为空。"}</p>
            </div>
          ) : (
            <ul className={styles.nodeList}>
              {(searchResults !== null
                ? searchResults.map((node) => ({ node, depth: 0 }))
                : treeRows
              ).map(({ node, depth }) => (
                <li
                  className={styles.nodeRow}
                  data-selected={selected.has(node.id) || undefined}
                  key={node.id}
                  style={{ paddingLeft: `${6 + depth * 16}px` }}
                >
                  {node.children_count > 0 && searchResults === null ? (
                    <button
                      aria-expanded={expanded.has(node.id)}
                      className={styles.expandButton}
                      onClick={() => toggleExpand(node)}
                      title={`${expanded.has(node.id) ? "收起" : "展开"} ${node.children_count} 个子类目`}
                      type="button"
                    >
                      {loadingIds.has(node.id) ? (
                        <LoaderCircle aria-hidden="true" className="spin" size={13} />
                      ) : expanded.has(node.id) ? (
                        <ChevronDown aria-hidden="true" size={13} />
                      ) : (
                        <ChevronRight aria-hidden="true" size={13} />
                      )}
                    </button>
                  ) : (
                    <span className={styles.expandSpacer} />
                  )}
                  <label className={styles.nodeCheck}>
                    <input
                      checked={selected.has(node.id)}
                      onChange={() => toggleSelect(node)}
                      type="checkbox"
                    />
                  </label>
                  <button
                    className={styles.nodeMain}
                    onClick={() => openDetail(node)}
                    title={node.full_path}
                    type="button"
                  >
                    <span className={styles.nodeNameWrap}>
                      <span className={styles.nodeName}>
                        {node.name_zh || node.name}
                      </span>
                      {node.name_zh ? (
                        <span className={styles.nodeNameEn}>{node.name}</span>
                      ) : null}
                    </span>
                    <span className={styles.nodeChips}>
                      {node.keywords_count > 0 ? (
                        <span className={styles.chip} data-kind="kw">
                          词 {node.keywords_count}
                        </span>
                      ) : null}
                      {node.candidates_count > 0 ? (
                        <span className={styles.chip} data-kind="cand">
                          候选 {node.candidates_count}
                        </span>
                      ) : null}
                    </span>
                  </button>
                  {node.children_count > 0 ? (
                    <span className={styles.leafMark}>{node.children_count}</span>
                  ) : (
                    <span className={styles.leafMark}>叶</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* ---- 右：类目详情（关键词 + 候选池） ---- */}
        <section className={styles.panel} aria-label="类目详情">
          {activeNode === null ? (
            <div className={styles.emptyHint}>
              <p>
                点左侧任意类目查看它的关键词与货源候选。
                勾选节点后点「爬取关键词」，Serper 会把整棵子树逐节点收割。
              </p>
            </div>
          ) : (
            <>
              <div className={styles.panelHead}>
                <span className={styles.panelTitle} title={activeNode.full_path}>
                  <Sprout aria-hidden="true" size={16} />
                  {activeNode.name_zh || activeNode.name}
                  {activeNode.name_zh ? (
                    <span className={styles.titleEn}>{activeNode.name}</span>
                  ) : null}
                </span>
                <span className={styles.headActions}>
                  <button
                    className="secondary-button"
                    disabled={busy !== null}
                    onClick={() => void handleSourceCategory()}
                    title="用该类目的关键词自动去 1688 找 3-5 个货源候选"
                    type="button"
                  >
                    {busy === "__source__" ? (
                      <LoaderCircle aria-hidden="true" className="spin" size={14} />
                    ) : (
                      <Search aria-hidden="true" size={14} />
                    )}
                    1688 找货
                  </button>
                  <button
                    className="secondary-button"
                    onClick={() => setShowAddForm((value) => !value)}
                    type="button"
                  >
                    <PackagePlus aria-hidden="true" size={14} />
                    手动贴货源
                  </button>
                </span>
              </div>
              <p className={styles.pathLine}>{activeNode.full_path}</p>

              {/* 类目产品画像：这个类目通常包含哪些产品（中英文） */}
              <div className={styles.profileBlock}>
                <div className={styles.profileHead}>
                  <span className={styles.sectionTitleInline}>
                    <Sparkles aria-hidden="true" size={13} />
                    类目产品画像
                  </span>
                  {profile?.exists ? null : (
                    <button
                      className="secondary-button"
                      disabled={profileBusy}
                      onClick={() => void handleGenerateProfile()}
                      title="AI 生成该类目通常包含的产品清单（一次生成永久缓存）"
                      type="button"
                    >
                      {profileBusy ? (
                        <LoaderCircle aria-hidden="true" className="spin" size={13} />
                      ) : (
                        <Sparkles aria-hidden="true" size={13} />
                      )}
                      生成画像
                    </button>
                  )}
                </div>
                {profile?.exists ? (
                  <ul className={styles.profileList}>
                    {profile.products.map((item) => (
                      <li className={styles.profileItem} key={item.en || item.zh}>
                        <span className={styles.profileZh}>{item.zh}</span>
                        <span className={styles.profileEn}>{item.en}</span>
                        {item.note_zh ? (
                          <span className={styles.profileNote}>{item.note_zh}</span>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className={styles.mutedLine}>
                    {profileBusy
                      ? "AI 正在分析这个类目…（约 10-30 秒）"
                      : "还没有画像。点「生成画像」看看这个类目通常应该铺哪些产品。"}
                  </p>
                )}
              </div>

              {showAddForm ? (
                <div className={styles.addForm}>
                  <input
                    className={styles.formInput}
                    onChange={(event) =>
                      setForm((prev) => ({ ...prev, title: event.target.value }))
                    }
                    placeholder="产品标题（必填）"
                    value={form.title}
                  />
                  <input
                    className={styles.formInput}
                    onChange={(event) =>
                      setForm((prev) => ({ ...prev, source_url: event.target.value }))
                    }
                    placeholder="1688 链接"
                    value={form.source_url}
                  />
                  <div className={styles.formRow}>
                    <input
                      className={styles.formInput}
                      onChange={(event) =>
                        setForm((prev) => ({ ...prev, price_cny: event.target.value }))
                      }
                      placeholder="价格 ¥"
                      value={form.price_cny}
                    />
                    <input
                      className={styles.formInput}
                      onChange={(event) =>
                        setForm((prev) => ({ ...prev, moq: event.target.value }))
                      }
                      placeholder="MOQ"
                      value={form.moq}
                    />
                    <input
                      className={styles.formInput}
                      onChange={(event) =>
                        setForm((prev) => ({
                          ...prev,
                          weight_note: event.target.value,
                        }))
                      }
                      placeholder="报重，如 1.2kg"
                      value={form.weight_note}
                    />
                  </div>
                  <input
                    className={styles.formInput}
                    onChange={(event) =>
                      setForm((prev) => ({
                        ...prev,
                        supplier_name: event.target.value,
                      }))
                    }
                    placeholder="供应商名"
                    value={form.supplier_name}
                  />
                  <button
                    className="primary-button"
                    disabled={busy !== null || !form.title.trim()}
                    onClick={() => void handleAddCandidate()}
                    type="button"
                  >
                    {busy === "__add__" ? (
                      <LoaderCircle aria-hidden="true" className="spin" size={14} />
                    ) : (
                      <PackagePlus aria-hidden="true" size={14} />
                    )}
                    加入候选池
                  </button>
                </div>
              ) : null}

              {/* 候选池 */}
              <h3 className={styles.sectionTitle}>
                货源候选（{candidates.length}）
              </h3>
              {candidates.length === 0 ? (
                <p className={styles.mutedLine}>
                  还没有候选。点上方「1688 找货」自动拉 3-5 个货源，或手动贴链接。
                </p>
              ) : (
                <ul className={styles.candidateList}>
                  {candidates.map((candidate) => (
                    <li className={styles.candidateRow} key={candidate.id}>
                      {candidate.image_url ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          alt=""
                          className={styles.thumb}
                          loading="lazy"
                          src={candidate.image_url}
                        />
                      ) : null}
                      <div className={styles.candidateMain}>
                        <strong>
                          {candidate.title}
                          <span
                            className={styles.sourceBadge}
                            data-source={candidate.source}
                          >
                            {candidate.source === "alibaba1688"
                              ? "1688 自动"
                              : "手动"}
                          </span>
                        </strong>
                        <span className={styles.candidateMeta}>
                          {candidate.price_cny ? `¥${candidate.price_cny}` : null}
                          {candidate.moq ? ` · MOQ ${candidate.moq}` : null}
                          {candidate.supplier_name
                            ? ` · ${candidate.supplier_name}`
                            : null}
                          {candidate.source_url ? (
                            <>
                              {" · "}
                              <a
                                href={candidate.source_url}
                                rel="noreferrer"
                                target="_blank"
                              >
                                货源
                              </a>
                            </>
                          ) : null}
                        </span>
                        {candidate.red_flags.length > 0 ? (
                          <span
                            className={styles.redFlag}
                            title={candidate.red_flags
                              .map((flag) => flag.reason)
                              .join("；")}
                          >
                            <ShieldAlert aria-hidden="true" size={12} />
                            红线标记 · 已断自动链，仅可人工放行
                          </span>
                        ) : null}
                      </div>
                      <div className={styles.candidateActions}>
                        <span
                          className={styles.statusBadge}
                          data-status={candidate.status}
                        >
                          {candidateStatusLabel(candidate.status)}
                        </span>
                        {candidate.status === "pending_review" ? (
                          <>
                            <button
                              className="secondary-button"
                              disabled={busy !== null}
                              onClick={() =>
                                void handleCandidateAction(candidate, "approve")
                              }
                              type="button"
                            >
                              放行
                            </button>
                            <button
                              className="secondary-button"
                              disabled={busy !== null}
                              onClick={() =>
                                void handleCandidateAction(candidate, "reject")
                              }
                              type="button"
                            >
                              删除
                            </button>
                          </>
                        ) : null}
                        {candidate.status === "approved" ? (
                          <button
                            className="primary-button"
                            disabled={busy !== null}
                            onClick={() => void handleImportToK(candidate)}
                            type="button"
                          >
                            {busy === candidate.id ? (
                              <LoaderCircle
                                aria-hidden="true"
                                className="spin"
                                size={13}
                              />
                            ) : (
                              <ArrowRight aria-hidden="true" size={13} />
                            )}
                            进 K
                          </button>
                        ) : null}
                        {candidate.status === "rejected" ? (
                          <button
                            className="secondary-button"
                            disabled={busy !== null}
                            onClick={() =>
                              void handleCandidateAction(candidate, "reopen")
                            }
                            type="button"
                          >
                            恢复
                          </button>
                        ) : null}
                      </div>
                    </li>
                  ))}
                </ul>
              )}

              {/* 关键词 */}
              <h3 className={styles.sectionTitle}>
                收割关键词（{keywords.length}）
              </h3>
              {keywords.length === 0 ? (
                <p className={styles.mutedLine}>
                  这个类目还没有关键词——勾选它并点「爬取关键词」。
                </p>
              ) : (
                <ul className={styles.keywordList}>
                  {keywords.map((keyword) => (
                    <li
                      className={styles.keywordRow}
                      data-status={keyword.status}
                      key={keyword.id}
                    >
                      <span className={styles.keywordText}>
                        {keyword.keyword_text}
                      </span>
                      <span className={styles.keywordType}>
                        {keywordTypeLabel(keyword.keyword_type)}
                      </span>
                      {keyword.status === "candidate" ? (
                        <span className={styles.keywordActions}>
                          <button
                            className={styles.kwButton}
                            data-kind="ok"
                            disabled={busy !== null}
                            onClick={() =>
                              void handleKeywordReview(keyword, "approved")
                            }
                            title="采用"
                            type="button"
                          >
                            ✓
                          </button>
                          <button
                            className={styles.kwButton}
                            data-kind="no"
                            disabled={busy !== null}
                            onClick={() =>
                              void handleKeywordReview(keyword, "rejected")
                            }
                            title="不要"
                            type="button"
                          >
                            ✕
                          </button>
                        </span>
                      ) : (
                        <span className={styles.keywordDecided}>
                          {keyword.status === "approved" ? "已采用" : "已拒绝"}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </section>
      </div>

      {/* ---- 运行台账 ---- */}
      <section className={styles.panel} aria-label="富化运行台账">
        <div className={styles.panelHead}>
          <span className={styles.panelTitle}>
            <ListChecks aria-hidden="true" size={16} />
            富化运行台账 · 额度与 R-A 共账，F 手动触发天然优先
          </span>
          <button
            className="secondary-button"
            onClick={() => void loadRunsAndQuota()}
            type="button"
          >
            <RefreshCw aria-hidden="true" size={14} />
            刷新
          </button>
        </div>
        {runs.length === 0 ? (
          <div className={styles.emptyHint}>
            <p>还没有运行记录。选好类目点「爬取关键词」就是第一条。</p>
          </div>
        ) : (
          <div className={styles.tableScroll}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>时间</th>
                  <th>选段</th>
                  <th>模式</th>
                  <th>进度</th>
                  <th>新词</th>
                  <th>新候选</th>
                  <th>状态</th>
                  <th>备注</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.run_id}>
                    <td className={styles.timeCell}>{formatTime(run.created_at)}</td>
                    <td className={styles.selectionCell}>
                      {run.selection.slice(0, 3).map((item, index) => (
                        <span key={item.id}>
                          {index > 0 ? "、" : ""}
                          <button
                            className={styles.linkButton}
                            onClick={() =>
                              openDetail({
                                id: item.id,
                                name: item.name,
                                name_zh: null,
                                full_path: item.full_path,
                                level: 0,
                                is_leaf: false,
                                children_count: 0,
                                keywords_count: 0,
                                candidates_count: 0,
                              })
                            }
                            title="打开该类目详情（关键词与货源候选都在里面）"
                            type="button"
                          >
                            {item.name}
                          </button>
                        </span>
                      ))}
                      {run.selection.length > 3
                        ? ` 等 ${run.categories_total} 节点`
                        : ""}
                    </td>
                    <td>{runModeLabel(run.mode)}</td>
                    <td>
                      {run.categories_done}/{run.categories_total}
                    </td>
                    <td>{run.keywords_found}</td>
                    <td>{run.candidates_found}</td>
                    <td>
                      <span className={styles.statusBadge} data-status={run.status}>
                        {runStatusLabel(run.status)}
                      </span>
                    </td>
                    <td>
                      {run.error ? (
                        <span className={styles.errorCell} title={run.error}>
                          {run.error}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
