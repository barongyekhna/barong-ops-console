"use client";

import { AlertTriangle, LoaderCircle } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  assignAllShipping,
  assignShipping,
  createShippingClass,
  createShippingRule,
  deleteShippingRule,
  getShippingBoard,
  getShippingClasses,
  getShippingRules,
  patchShippingClass,
  patchShippingProduct,
  patchShippingRule,
  simulateShipping,
  type ShippingBoardFilter,
  type ShippingBoardItem,
  type ShippingBoardResponse,
  type ShippingClass,
  type ShippingOrigin,
  type ShippingRule,
  type ShippingRuleType,
  type ShippingSimulationResult,
} from "./api";
import styles from "./ShippingDeck.module.css";

type ActiveTab = "board" | "rules" | "classes" | "simulate";

type RuleDraft = {
  key: string;
  id: string | null;
  priority: string;
  rule_type: ShippingRuleType;
  min_weight_kg: string;
  max_weight_kg: string;
  shipping_class_slug: string;
  active: boolean;
  notes: string;
};

type ClassDraft = {
  key: string;
  id: string | null;
  slug: string;
  name: string;
  origin: ShippingOrigin;
  active: boolean;
  notes: string;
  sort_order: number;
};

const EMPTY_SUMMARY: ShippingBoardResponse["summary"] = {
  total_dtc: 0,
  assigned: 0,
  unassigned: 0,
  review_needed: 0,
  exported_missing: 0,
};

const BOARD_FILTERS: { key: ShippingBoardFilter; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "unassigned", label: "未分配" },
  { key: "review", label: "待复核" },
  { key: "exported_missing", label: "已上架缺运费" },
];

function ruleTypeLabel(ruleType: ShippingRuleType | "manual" | null) {
  switch (ruleType) {
    case "us_stock_override":
      return "美国仓线";
    case "battery_override":
      return "带电线";
    case "weight_band":
      return "重量段位";
    case "manual":
      return "人工指定";
    default:
      return "—";
  }
}

function toRuleDraft(rule: ShippingRule): RuleDraft {
  return {
    key: rule.id,
    id: rule.id,
    priority: String(rule.priority),
    rule_type: rule.rule_type,
    min_weight_kg:
      rule.min_weight_kg === null ? "" : String(rule.min_weight_kg),
    max_weight_kg:
      rule.max_weight_kg === null ? "" : String(rule.max_weight_kg),
    shipping_class_slug: rule.shipping_class_slug,
    active: rule.active,
    notes: rule.notes ?? "",
  };
}

function toClassDraft(shippingClass: ShippingClass): ClassDraft {
  return {
    key: shippingClass.id,
    id: shippingClass.id,
    slug: shippingClass.slug,
    name: shippingClass.name,
    origin: shippingClass.origin,
    active: shippingClass.active,
    notes: shippingClass.notes ?? "",
    sort_order: shippingClass.sort_order,
  };
}

function optionalNumber(value: string) {
  const normalized = value.trim();
  if (!normalized) return null;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "—";
}

export function ShippingDeck() {
  const [activeTab, setActiveTab] = useState<ActiveTab>("board");
  const [filter, setFilter] = useState<ShippingBoardFilter>("all");
  const [summary, setSummary] = useState(EMPTY_SUMMARY);
  const [items, setItems] = useState<ShippingBoardItem[]>([]);
  const [shippingClasses, setShippingClasses] = useState<ShippingClass[]>([]);
  const [rules, setRules] = useState<ShippingRule[]>([]);
  const [ruleDrafts, setRuleDrafts] = useState<RuleDraft[]>([]);
  const [classDrafts, setClassDrafts] = useState<ClassDraft[]>([]);
  const [loading, setLoading] = useState(true);
  const [boardLoading, setBoardLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [simulation, setSimulation] =
    useState<ShippingSimulationResult | null>(null);
  const [simulationForm, setSimulationForm] = useState({
    weight: "",
    length: "",
    width: "",
    height: "",
    containsBattery: false,
    usStock: false,
  });
  const draftSequence = useRef(0);

  const refreshBoard = useCallback(async (nextFilter: ShippingBoardFilter) => {
    const board = await getShippingBoard(nextFilter, 500);
    setSummary(board.summary);
    setItems(board.items);
  }, []);

  const refreshClasses = useCallback(async () => {
    const data = await getShippingClasses();
    setShippingClasses(data);
    setClassDrafts(data.map(toClassDraft));
  }, []);

  const refreshRules = useCallback(async () => {
    const data = await getShippingRules();
    setRules(data);
    setRuleDrafts(data.map(toRuleDraft));
  }, []);

  useEffect(() => {
    let current = true;
    const load = async () => {
      setLoading(true);
      try {
        const [board, classData, ruleData] = await Promise.all([
          getShippingBoard("all", 500),
          getShippingClasses(),
          getShippingRules(),
        ]);
        if (!current) return;
        setSummary(board.summary);
        setItems(board.items);
        setShippingClasses(classData);
        setClassDrafts(classData.map(toClassDraft));
        setRules(ruleData);
        setRuleDrafts(ruleData.map(toRuleDraft));
        setError(null);
      } catch (loadError) {
        if (current) setError(errorMessage(loadError));
      } finally {
        if (current) setLoading(false);
      }
    };
    void load();
    return () => {
      current = false;
    };
  }, []);

  const handleFilter = useCallback(
    async (nextFilter: ShippingBoardFilter) => {
      setFilter(nextFilter);
      setBoardLoading(true);
      setError(null);
      try {
        await refreshBoard(nextFilter);
      } catch (filterError) {
        setError(errorMessage(filterError));
      } finally {
        setBoardLoading(false);
      }
    },
    [refreshBoard],
  );

  const handleRefresh = useCallback(async () => {
    setBoardLoading(true);
    setError(null);
    try {
      await refreshBoard(filter);
    } catch (refreshError) {
      setError(errorMessage(refreshError));
    } finally {
      setBoardLoading(false);
    }
  }, [filter, refreshBoard]);

  const handleAssignAll = useCallback(async () => {
    setBusy("assign-all");
    setError(null);
    setNotice(null);
    try {
      const result = await assignAllShipping();
      setNotice(
        `已重算：${result.assigned} 个分配成功，${result.review_needed} 个待复核，${result.unresolved} 个缺数据未分配。`,
      );
      await refreshBoard(filter);
    } catch (assignError) {
      setError(errorMessage(assignError));
    } finally {
      setBusy(null);
    }
  }, [filter, refreshBoard]);

  const handleAssignOne = useCallback(
    async (productId: string) => {
      setBusy(`product:${productId}`);
      setError(null);
      try {
        await assignShipping(productId);
        await refreshBoard(filter);
      } catch (assignError) {
        setError(errorMessage(assignError));
      } finally {
        setBusy(null);
      }
    },
    [filter, refreshBoard],
  );

  const handleProductPatch = useCallback(
    async (
      productId: string,
      payload: Parameters<typeof patchShippingProduct>[1],
    ) => {
      setBusy(`product:${productId}`);
      setError(null);
      try {
        await patchShippingProduct(productId, payload);
        await refreshBoard(filter);
      } catch (patchError) {
        setError(errorMessage(patchError));
      } finally {
        setBusy(null);
      }
    },
    [filter, refreshBoard],
  );

  const updateRuleDraft = useCallback(
    (key: string, patch: Partial<RuleDraft>) => {
      setRuleDrafts((current) =>
        current.map((row) => (row.key === key ? { ...row, ...patch } : row)),
      );
    },
    [],
  );

  const handleAddRule = useCallback(() => {
    draftSequence.current += 1;
    setRuleDrafts((current) => [
      ...current,
      {
        key: `new-rule-${draftSequence.current}`,
        id: null,
        priority: "",
        rule_type: "weight_band",
        min_weight_kg: "",
        max_weight_kg: "",
        shipping_class_slug: "",
        active: true,
        notes: "",
      },
    ]);
  }, []);

  const handleSaveRule = useCallback(
    async (row: RuleDraft) => {
      setBusy(`rule:${row.key}`);
      setError(null);
      try {
        const values = {
          priority: Number(row.priority),
          min_weight_kg: optionalNumber(row.min_weight_kg),
          max_weight_kg: optionalNumber(row.max_weight_kg),
          shipping_class_slug: row.shipping_class_slug,
          active: row.active,
          notes: row.notes.trim() || null,
        };
        if (row.id) {
          await patchShippingRule(row.id, values);
        } else {
          await createShippingRule({ ...values, rule_type: row.rule_type });
        }
        await refreshRules();
      } catch (saveError) {
        setError(errorMessage(saveError));
      } finally {
        setBusy(null);
      }
    },
    [refreshRules],
  );

  const handleDeleteRule = useCallback(
    async (row: RuleDraft) => {
      if (!row.id) {
        setRuleDrafts((current) =>
          current.filter((item) => item.key !== row.key),
        );
        return;
      }
      setBusy(`rule:${row.key}`);
      setError(null);
      try {
        await deleteShippingRule(row.id);
        await refreshRules();
      } catch (deleteError) {
        setError(errorMessage(deleteError));
      } finally {
        setBusy(null);
      }
    },
    [refreshRules],
  );

  const updateClassDraft = useCallback(
    (key: string, patch: Partial<ClassDraft>) => {
      setClassDrafts((current) =>
        current.map((row) => (row.key === key ? { ...row, ...patch } : row)),
      );
    },
    [],
  );

  const handleAddClass = useCallback(() => {
    draftSequence.current += 1;
    setClassDrafts((current) => [
      ...current,
      {
        key: `new-class-${draftSequence.current}`,
        id: null,
        slug: "",
        name: "",
        origin: "cn_direct",
        active: true,
        notes: "",
        sort_order: 100,
      },
    ]);
  }, []);

  const handleSaveClass = useCallback(
    async (row: ClassDraft) => {
      setBusy(`class:${row.key}`);
      setError(null);
      try {
        if (row.id) {
          await patchShippingClass(row.id, {
            name: row.name,
            origin: row.origin,
            notes: row.notes.trim() || null,
            active: row.active,
            sort_order: row.sort_order,
          });
        } else {
          const created = await createShippingClass({
            slug: row.slug,
            name: row.name,
            origin: row.origin,
            notes: row.notes.trim() || null,
            sort_order: row.sort_order,
          });
          if (!row.active) {
            await patchShippingClass(created.id, { active: false });
          }
        }
        await Promise.all([refreshClasses(), refreshBoard(filter)]);
      } catch (saveError) {
        setError(errorMessage(saveError));
      } finally {
        setBusy(null);
      }
    },
    [filter, refreshBoard, refreshClasses],
  );

  const handleSimulate = useCallback(async () => {
    setBusy("simulate");
    setError(null);
    setSimulation(null);
    try {
      const weight = optionalNumber(simulationForm.weight);
      const length = optionalNumber(simulationForm.length);
      const width = optionalNumber(simulationForm.width);
      const height = optionalNumber(simulationForm.height);
      const volumetric =
        length !== null && width !== null && height !== null
          ? (length * width * height) / 6000
          : null;
      const result = await simulateShipping({
        weight_kg: weight,
        volumetric_kg: volumetric,
        contains_battery: simulationForm.containsBattery,
        us_stock: simulationForm.usStock,
      });
      setSimulation(result);
    } catch (simulationError) {
      setError(errorMessage(simulationError));
    } finally {
      setBusy(null);
    }
  }, [simulationForm]);

  const simulationClassName = simulation?.shipping_class_slug
    ? shippingClasses.find(
        (shippingClass) => shippingClass.slug === simulation.shipping_class_slug,
      )?.name ?? simulation.shipping_class_slug
    : null;

  return (
    <div className={styles.deck}>
      <div className={styles.statRow}>
        <div className={styles.statCard}>
          <span className={styles.statLabel}>独立站产品</span>
          <span className={styles.statValue}>
            {loading ? "—" : summary.total_dtc}
          </span>
        </div>
        <div className={styles.statCard} data-tone="success">
          <span className={styles.statLabel}>已分配</span>
          <span className={styles.statValue}>
            {loading ? "—" : summary.assigned}
          </span>
        </div>
        <div className={styles.statCard} data-tone="flight">
          <span className={styles.statLabel}>待人工复核</span>
          <span className={styles.statValue}>
            {loading ? "—" : summary.review_needed}
          </span>
        </div>
        <div className={styles.statCard} data-tone="failed">
          <span className={styles.statLabel}>已上架缺运费</span>
          <span className={styles.statValue}>
            {loading ? "—" : summary.exported_missing}
          </span>
        </div>
      </div>

      {error ? (
        <div className={styles.state} role="alert">
          <AlertTriangle aria-hidden="true" size={16} />
          <span>{error}</span>
        </div>
      ) : null}
      {notice ? <p className={styles.notice}>{notice}</p> : null}

      <div className={styles.tabs} role="tablist">
        <button
          className={`${styles.tab} ${activeTab === "board" ? styles.tabOn : ""}`}
          onClick={() => setActiveTab("board")}
          role="tab"
          type="button"
        >
          产品台账 <span className={styles.tabCount}>{summary.total_dtc}</span>
        </button>
        <button
          className={`${styles.tab} ${activeTab === "rules" ? styles.tabOn : ""}`}
          onClick={() => setActiveTab("rules")}
          role="tab"
          type="button"
        >
          分配规则 <span className={styles.tabCount}>{rules.length}</span>
        </button>
        <button
          className={`${styles.tab} ${activeTab === "classes" ? styles.tabOn : ""}`}
          onClick={() => setActiveTab("classes")}
          role="tab"
          type="button"
        >
          运费模板 <span className={styles.tabCount}>{shippingClasses.length}</span>
        </button>
        <button
          className={`${styles.tab} ${activeTab === "simulate" ? styles.tabOn : ""}`}
          onClick={() => setActiveTab("simulate")}
          role="tab"
          type="button"
        >
          试算器
        </button>
      </div>

      {activeTab === "board" ? (
        <section className={styles.panel} aria-label="产品台账">
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>
              产品台账 · 独立站产品的运费归属与溯源
            </span>
            <span className={styles.headActions}>
              <button
                className="primary-button"
                disabled={busy !== null}
                onClick={() => void handleAssignAll()}
                type="button"
              >
                重算全部
              </button>
              <button
                className="secondary-button"
                disabled={boardLoading || busy !== null}
                onClick={() => void handleRefresh()}
                type="button"
              >
                刷新
              </button>
            </span>
          </div>
          <div className={styles.filterRow}>
            {BOARD_FILTERS.map((option) => (
              <button
                className={`secondary-button ${filter === option.key ? styles.tabOn : ""}`}
                disabled={boardLoading || busy !== null}
                key={option.key}
                onClick={() => void handleFilter(option.key)}
                type="button"
              >
                {option.label}
              </button>
            ))}
          </div>
          {loading || boardLoading ? (
            <div className={styles.state}>
              <LoaderCircle aria-hidden="true" className="spin" size={16} />
              <span>正在加载…</span>
            </div>
          ) : items.length === 0 ? (
            <div className={styles.emptyHint}>—</div>
          ) : (
            <div className={styles.tableScroll}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>产品</th>
                    <th>计费重</th>
                    <th>带电</th>
                    <th>美国仓</th>
                    <th>运费模板</th>
                    <th>溯源</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => {
                    const productBusy = busy === `product:${item.product_id}`;
                    return (
                      <tr key={item.product_id}>
                        <td className={styles.productCell}>
                          <strong>{item.product_name}</strong>
                          <span>{item.sku}</span>
                        </td>
                        <td>
                          {item.used_kg === null ? (
                            <>
                              <span>—</span>
                              <span className={styles.errorCell}>缺数据</span>
                            </>
                          ) : (
                            `${item.used_kg.toFixed(2)} kg`
                          )}
                        </td>
                        <td>
                          <input
                            checked={item.contains_battery}
                            disabled={productBusy || busy !== null}
                            onChange={(event) =>
                              void handleProductPatch(item.product_id, {
                                contains_battery: event.target.checked,
                              })
                            }
                            type="checkbox"
                          />
                        </td>
                        <td>
                          <input
                            checked={item.us_stock}
                            disabled={productBusy || busy !== null}
                            onChange={(event) =>
                              void handleProductPatch(item.product_id, {
                                us_stock: event.target.checked,
                              })
                            }
                            type="checkbox"
                          />
                        </td>
                        <td>
                          <select
                            className={styles.formInput}
                            disabled={productBusy || busy !== null}
                            onChange={(event) =>
                              void handleProductPatch(item.product_id, {
                                shipping_class_slug: event.target.value || null,
                              })
                            }
                            value={item.shipping_class_slug ?? ""}
                          >
                            <option value="">未分配</option>
                            {shippingClasses
                              .filter((shippingClass) => shippingClass.active)
                              .map((shippingClass) => (
                                <option
                                  key={shippingClass.id}
                                  value={shippingClass.slug}
                                >
                                  {shippingClass.name}
                                </option>
                              ))}
                          </select>
                        </td>
                        <td>
                          <span className={styles.actionRow}>
                            {item.review_needed ? (
                              <button
                                className={`secondary-button ${styles.statusBadge}`}
                                data-status="pending_review"
                                disabled={productBusy || busy !== null}
                                onClick={() =>
                                  void handleProductPatch(item.product_id, {
                                    clear_review: true,
                                  })
                                }
                                type="button"
                              >
                                待复核
                              </button>
                            ) : null}
                            <span
                              title={
                                item.assignment
                                  ? JSON.stringify(item.assignment)
                                  : undefined
                              }
                            >
                              {ruleTypeLabel(item.assignment?.rule_type ?? null)}
                            </span>
                          </span>
                        </td>
                        <td>
                          <button
                            className="secondary-button"
                            disabled={productBusy || busy !== null}
                            onClick={() => void handleAssignOne(item.product_id)}
                            type="button"
                          >
                            重算
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ) : null}

      {activeTab === "rules" ? (
        <section className={styles.panel} aria-label="分配规则">
          <p className={styles.mutedLine}>
            评估顺序：美国仓线 → 带电线 → 重量段位（priority
            小的先）。计费重 = 实重与体积重取大（体积重 = 长×宽×高cm ÷
            6000）。缺重量数据的产品不会被分配，只会进待复核。
          </p>
          {loading ? (
            <div className={styles.state}>
              <LoaderCircle aria-hidden="true" className="spin" size={16} />
              <span>正在加载…</span>
            </div>
          ) : ruleDrafts.length === 0 ? (
            <div className={styles.emptyHint}>—</div>
          ) : (
            <div className={styles.tableScroll}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>优先级</th>
                    <th>类型</th>
                    <th>重量下限 kg</th>
                    <th>重量上限 kg</th>
                    <th>运费模板</th>
                    <th>启用</th>
                    <th>备注</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {ruleDrafts.map((row) => {
                    const rowBusy = busy === `rule:${row.key}`;
                    return (
                      <tr key={row.key}>
                        <td>
                          <input
                            className={styles.formInput}
                            onChange={(event) =>
                              updateRuleDraft(row.key, {
                                priority: event.target.value,
                              })
                            }
                            type="number"
                            value={row.priority}
                          />
                        </td>
                        <td>
                          <select
                            className={styles.formInput}
                            disabled={row.id !== null}
                            onChange={(event) =>
                              updateRuleDraft(row.key, {
                                rule_type: event.target.value as ShippingRuleType,
                              })
                            }
                            value={row.rule_type}
                          >
                            <option value="us_stock_override">美国仓线</option>
                            <option value="battery_override">带电线</option>
                            <option value="weight_band">重量段位</option>
                          </select>
                        </td>
                        <td>
                          <input
                            className={styles.formInput}
                            disabled={row.rule_type !== "weight_band"}
                            onChange={(event) =>
                              updateRuleDraft(row.key, {
                                min_weight_kg: event.target.value,
                              })
                            }
                            step="any"
                            type="number"
                            value={row.min_weight_kg}
                          />
                        </td>
                        <td>
                          <input
                            className={styles.formInput}
                            disabled={row.rule_type !== "weight_band"}
                            onChange={(event) =>
                              updateRuleDraft(row.key, {
                                max_weight_kg: event.target.value,
                              })
                            }
                            step="any"
                            type="number"
                            value={row.max_weight_kg}
                          />
                        </td>
                        <td>
                          <select
                            className={styles.formInput}
                            onChange={(event) =>
                              updateRuleDraft(row.key, {
                                shipping_class_slug: event.target.value,
                              })
                            }
                            value={row.shipping_class_slug}
                          >
                            <option value="">未分配</option>
                            {shippingClasses.map((shippingClass) => (
                              <option
                                key={shippingClass.id}
                                value={shippingClass.slug}
                              >
                                {shippingClass.name}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td>
                          <input
                            checked={row.active}
                            onChange={(event) =>
                              updateRuleDraft(row.key, {
                                active: event.target.checked,
                              })
                            }
                            type="checkbox"
                          />
                        </td>
                        <td>
                          <input
                            className={styles.formInput}
                            onChange={(event) =>
                              updateRuleDraft(row.key, {
                                notes: event.target.value,
                              })
                            }
                            value={row.notes}
                          />
                        </td>
                        <td>
                          <span className={styles.actionRow}>
                            <button
                              className="secondary-button"
                              disabled={
                                rowBusy ||
                                busy !== null ||
                                !row.priority.trim() ||
                                !row.shipping_class_slug
                              }
                              onClick={() => void handleSaveRule(row)}
                              type="button"
                            >
                              保存
                            </button>
                            <button
                              className="secondary-button"
                              disabled={rowBusy || busy !== null}
                              onClick={() => void handleDeleteRule(row)}
                              type="button"
                            >
                              删除
                            </button>
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <div className={styles.filterRow}>
            <button
              className="primary-button"
              disabled={busy !== null}
              onClick={handleAddRule}
              type="button"
            >
              新增规则
            </button>
          </div>
        </section>
      ) : null}

      {activeTab === "classes" ? (
        <section className={styles.panel} aria-label="运费模板">
          <p className={styles.mutedLine}>
            slug 必须与 WooCommerce 后台的运费类别（shipping class）slug
            完全一致——这是唯一的对齐点，填错产品会挂错模板。
          </p>
          {loading ? (
            <div className={styles.state}>
              <LoaderCircle aria-hidden="true" className="spin" size={16} />
              <span>正在加载…</span>
            </div>
          ) : classDrafts.length === 0 ? (
            <div className={styles.emptyHint}>—</div>
          ) : (
            <div className={styles.tableScroll}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>slug</th>
                    <th>名称</th>
                    <th>线路</th>
                    <th>启用</th>
                    <th>备注</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {classDrafts.map((row) => {
                    const rowBusy = busy === `class:${row.key}`;
                    return (
                      <tr key={row.key}>
                        <td>
                          <input
                            className={styles.formInput}
                            disabled={row.id !== null}
                            onChange={(event) =>
                              updateClassDraft(row.key, {
                                slug: event.target.value,
                              })
                            }
                            value={row.slug}
                          />
                        </td>
                        <td>
                          <input
                            className={styles.formInput}
                            onChange={(event) =>
                              updateClassDraft(row.key, {
                                name: event.target.value,
                              })
                            }
                            value={row.name}
                          />
                        </td>
                        <td>
                          <select
                            className={styles.formInput}
                            onChange={(event) =>
                              updateClassDraft(row.key, {
                                origin: event.target.value as ShippingOrigin,
                              })
                            }
                            value={row.origin}
                          >
                            <option value="cn_direct">中国直发</option>
                            <option value="us_stock">美国仓</option>
                          </select>
                        </td>
                        <td>
                          <input
                            checked={row.active}
                            disabled={row.id === null}
                            onChange={(event) =>
                              updateClassDraft(row.key, {
                                active: event.target.checked,
                              })
                            }
                            type="checkbox"
                          />
                        </td>
                        <td>
                          <input
                            className={styles.formInput}
                            onChange={(event) =>
                              updateClassDraft(row.key, {
                                notes: event.target.value,
                              })
                            }
                            value={row.notes}
                          />
                        </td>
                        <td>
                          <button
                            className="secondary-button"
                            disabled={
                              rowBusy ||
                              busy !== null ||
                              !row.slug.trim() ||
                              !row.name.trim()
                            }
                            onClick={() => void handleSaveClass(row)}
                            type="button"
                          >
                            保存
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <div className={styles.filterRow}>
            <button
              className="primary-button"
              disabled={busy !== null}
              onClick={handleAddClass}
              type="button"
            >
              新增模板
            </button>
          </div>
        </section>
      ) : null}

      {activeTab === "simulate" ? (
        <section className={styles.panel} aria-label="试算器">
          <div className={styles.calculatorRow}>
            <label className={styles.calculatorField}>
              <span>实重 kg</span>
              <input
                className={styles.formInput}
                onChange={(event) =>
                  setSimulationForm((current) => ({
                    ...current,
                    weight: event.target.value,
                  }))
                }
                step="any"
                type="number"
                value={simulationForm.weight}
              />
            </label>
            <label className={styles.dimensionField}>
              <span>长/宽/高 cm</span>
              <span className={styles.dimensionInputs}>
                <input
                  aria-label="长"
                  className={styles.formInput}
                  onChange={(event) =>
                    setSimulationForm((current) => ({
                      ...current,
                      length: event.target.value,
                    }))
                  }
                  step="any"
                  type="number"
                  value={simulationForm.length}
                />
                <input
                  aria-label="宽"
                  className={styles.formInput}
                  onChange={(event) =>
                    setSimulationForm((current) => ({
                      ...current,
                      width: event.target.value,
                    }))
                  }
                  step="any"
                  type="number"
                  value={simulationForm.width}
                />
                <input
                  aria-label="高"
                  className={styles.formInput}
                  onChange={(event) =>
                    setSimulationForm((current) => ({
                      ...current,
                      height: event.target.value,
                    }))
                  }
                  step="any"
                  type="number"
                  value={simulationForm.height}
                />
              </span>
            </label>
            <label className={styles.calculatorField}>
              <span>带电</span>
              <input
                checked={simulationForm.containsBattery}
                onChange={(event) =>
                  setSimulationForm((current) => ({
                    ...current,
                    containsBattery: event.target.checked,
                  }))
                }
                type="checkbox"
              />
            </label>
            <label className={styles.calculatorField}>
              <span>美国仓现货</span>
              <input
                checked={simulationForm.usStock}
                onChange={(event) =>
                  setSimulationForm((current) => ({
                    ...current,
                    usStock: event.target.checked,
                  }))
                }
                type="checkbox"
              />
            </label>
            <button
              className="primary-button"
              disabled={busy !== null}
              onClick={() => void handleSimulate()}
              type="button"
            >
              试算
            </button>
          </div>
          {simulation ? (
            <div className={styles.resultRow}>
              <div className={styles.statCard}>
                {simulation.shipping_class_slug && simulationClassName ? (
                  <span className={styles.actionRow}>
                    <span className={styles.panelTitle}>
                      → {simulationClassName}（{ruleTypeLabel(simulation.rule_type)}，
                      计费重 {simulation.used_kg === null ? "—" : `${simulation.used_kg}kg`}）
                    </span>
                    {simulation.review_needed && simulation.review_reason ? (
                      <span
                        className={styles.statusBadge}
                        data-status="pending_review"
                      >
                        {simulation.review_reason}
                      </span>
                    ) : null}
                  </span>
                ) : (
                  <span className={styles.errorCell}>
                    不分配：{simulation.review_reason}
                  </span>
                )}
              </div>
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
