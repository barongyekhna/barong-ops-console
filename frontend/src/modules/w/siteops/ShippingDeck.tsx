"use client";

import { AlertTriangle, LoaderCircle } from "lucide-react";
import { Fragment, useCallback, useEffect, useRef, useState } from "react";

import {
  assignAllShipping,
  assignShipping,
  createShippingClass,
  createShippingRule,
  deleteShippingRule,
  getOrders,
  getShippingBoard,
  getShippingClasses,
  getShippingRules,
  patchOrderTracking,
  deleteShippingClass,
  patchShippingClass,
  patchShippingProduct,
  patchShippingRule,
  refreshOrderTracking,
  simulateShipping,
  syncShippingClass,
  type ShippingBoardFilter,
  type ShippingBoardItem,
  type ShippingBoardResponse,
  type ShippingClass,
  type ShippingOrigin,
  type ShippingRule,
  type ShippingRuleType,
  type ShippingSimulationResult,
  type ShippingSyncStatus,
  type ShippingZoneRate,
  type TrackingStatus,
  type WOrder,
  type WOrderFilter,
  type WOrdersResponse,
  type WritebackStatus,
} from "./api";
import styles from "./ShippingDeck.module.css";

type ActiveTab = "orders" | "board" | "rules" | "classes" | "simulate";

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
  description: string;
  zone_rates: ShippingZoneRate[];
  sync_status: ShippingSyncStatus;
  woo_class_id: number | null;
  synced_at: string | null;
  sync_error: string | null;
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

const EMPTY_ORDER_SUMMARY: WOrdersResponse["summary"] = {
  pending: 0,
  in_transit: 0,
  delivered: 0,
  exception: 0,
};

const BOARD_FILTERS: { key: ShippingBoardFilter; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "unassigned", label: "未分配" },
  { key: "review", label: "待复核" },
  { key: "exported_missing", label: "已上架缺运费" },
];

const ORDER_FILTERS: { key: WOrderFilter; label: string }[] = [
  { key: "pending", label: "待填单号" },
  { key: "tracked", label: "已填单号" },
  { key: "all", label: "全部" },
];

const TRACKING_STATUS_LABELS: Record<TrackingStatus, string> = {
  none: "待填单号",
  registered: "已登记",
  info_received: "已揽收",
  in_transit: "运输中",
  out_for_delivery: "派送中",
  delivered: "已签收",
  exception: "异常",
  expired: "查询过期",
  not_found: "暂无轨迹",
};

const WRITEBACK_STATUS_LABELS: Record<WritebackStatus, string> = {
  none: "—",
  pending: "回传中",
  success: "已回传",
  failed: "回传失败",
};

const SYNC_STATUS_LABELS: Record<ShippingSyncStatus, string> = {
  draft: "草稿",
  pending: "同步中",
  synced: "已同步",
  failed: "失败",
};

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
    description: shippingClass.description ?? "",
    zone_rates: shippingClass.zone_rates_json ?? [],
    sync_status: shippingClass.sync_status,
    woo_class_id: shippingClass.woo_class_id,
    synced_at: shippingClass.synced_at,
    sync_error: shippingClass.sync_error,
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

function formatDateTime(value: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function orderItemsTitle(order: WOrder) {
  return (order.items_json ?? [])
    .map((item) => `${item.name} × ${item.qty}`)
    .join("\n");
}

export function ShippingDeck() {
  const [activeTab, setActiveTab] = useState<ActiveTab>("orders");
  const [orderFilter, setOrderFilter] = useState<WOrderFilter>("all");
  const [orderSummary, setOrderSummary] = useState(EMPTY_ORDER_SUMMARY);
  const [orders, setOrders] = useState<WOrder[]>([]);
  const [orderLoading, setOrderLoading] = useState(false);
  const [trackingDrafts, setTrackingDrafts] = useState<Record<string, string>>(
    {},
  );
  const [editingTracking, setEditingTracking] = useState<Set<string>>(
    new Set(),
  );
  const [expandedOrders, setExpandedOrders] = useState<Set<string>>(new Set());
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

  const applyOrders = useCallback((data: WOrdersResponse) => {
    setOrderSummary(data.summary);
    setOrders(data.orders);
    setTrackingDrafts(
      Object.fromEntries(
        data.orders.map((order) => [order.id, order.tracking_number ?? ""]),
      ),
    );
  }, []);

  const refreshOrders = useCallback(
    async (nextFilter: WOrderFilter) => {
      applyOrders(await getOrders(nextFilter));
    },
    [applyOrders],
  );

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
        const [orderData, board, classData, ruleData] = await Promise.all([
          getOrders("all"),
          getShippingBoard("all", 500),
          getShippingClasses(),
          getShippingRules(),
        ]);
        if (!current) return;
        applyOrders(orderData);
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
  }, [applyOrders]);

  const handleOrderFilter = useCallback(
    async (nextFilter: WOrderFilter) => {
      setOrderFilter(nextFilter);
      setOrderLoading(true);
      setError(null);
      try {
        await refreshOrders(nextFilter);
      } catch (filterError) {
        setError(errorMessage(filterError));
      } finally {
        setOrderLoading(false);
      }
    },
    [refreshOrders],
  );

  const handleSaveTracking = useCallback(
    async (order: WOrder) => {
      const trackingNumber = (trackingDrafts[order.id] ?? "").trim();
      if (!trackingNumber && !order.tracking_number) return;
      setBusy(`tracking:${order.id}`);
      setError(null);
      setNotice(null);
      try {
        const result = await patchOrderTracking(order.id, {
          tracking_number: trackingNumber || null,
          carrier_code: trackingNumber ? order.carrier_code : null,
        });
        if (result.tracking_warning) setNotice(result.tracking_warning);
        setEditingTracking((current) => {
          const next = new Set(current);
          next.delete(order.id);
          return next;
        });
        await refreshOrders(orderFilter);
      } catch (saveError) {
        setError(errorMessage(saveError));
      } finally {
        setBusy(null);
      }
    },
    [orderFilter, refreshOrders, trackingDrafts],
  );

  const handleRefreshTracking = useCallback(
    async (orderId: string) => {
      setBusy(`refresh-tracking:${orderId}`);
      setError(null);
      try {
        await refreshOrderTracking(orderId);
        await refreshOrders(orderFilter);
      } catch (refreshError) {
        setError(errorMessage(refreshError));
      } finally {
        setBusy(null);
      }
    },
    [orderFilter, refreshOrders],
  );

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

  const updateZoneRate = useCallback(
    (
      classKey: string,
      index: number,
      patch: Partial<ShippingZoneRate>,
    ) => {
      setClassDrafts((current) =>
        current.map((row) =>
          row.key === classKey
            ? {
                ...row,
                zone_rates: row.zone_rates.map((rate, rateIndex) =>
                  rateIndex === index ? { ...rate, ...patch } : rate,
                ),
              }
            : row,
        ),
      );
    },
    [],
  );

  const addZoneRate = useCallback((classKey: string) => {
    setClassDrafts((current) =>
      current.map((row) =>
        row.key === classKey
          ? {
              ...row,
              zone_rates: [
                ...row.zone_rates,
                { zone_name: "", base_cost: "", class_cost: "" },
              ],
            }
          : row,
      ),
    );
  }, []);

  const removeZoneRate = useCallback((classKey: string, index: number) => {
    setClassDrafts((current) =>
      current.map((row) =>
        row.key === classKey
          ? {
              ...row,
              zone_rates: row.zone_rates.filter(
                (_rate, rateIndex) => rateIndex !== index,
              ),
            }
          : row,
      ),
    );
  }, []);

  const handleAddClass = useCallback(() => {
    draftSequence.current += 1;
    setClassDrafts((current) => [
      ...current,
      {
        key: `new-class-${draftSequence.current}`,
        id: null,
        slug: "",
        name: "",
        description: "",
        zone_rates: [],
        sync_status: "draft",
        woo_class_id: null,
        synced_at: null,
        sync_error: null,
        origin: "cn_direct",
        active: true,
        notes: "",
        sort_order: 100,
      },
    ]);
  }, []);

  const handleSaveClass = useCallback(
    async (row: ClassDraft, shouldSync: boolean) => {
      setBusy(`class:${row.key}`);
      setError(null);
      try {
        let classId = row.id;
        const zoneRates = row.zone_rates.filter(
          (rate) =>
            rate.zone_name.trim() ||
            rate.base_cost.trim() ||
            rate.class_cost.trim(),
        );
        if (row.id) {
          await patchShippingClass(row.id, {
            name: row.name,
            description: row.description.trim() || null,
            zone_rates_json: zoneRates,
            origin: row.origin,
            notes: row.notes.trim() || null,
            active: row.active,
            sort_order: row.sort_order,
          });
        } else {
          const created = await createShippingClass({
            slug: row.slug,
            name: row.name,
            description: row.description.trim() || null,
            zone_rates_json: zoneRates,
            origin: row.origin,
            notes: row.notes.trim() || null,
            sort_order: row.sort_order,
          });
          classId = created.id;
          if (!row.active) {
            await patchShippingClass(created.id, { active: false });
          }
        }
        if (shouldSync && classId) await syncShippingClass(classId);
        await Promise.all([refreshClasses(), refreshBoard(filter)]);
      } catch (saveError) {
        setError(errorMessage(saveError));
      } finally {
        setBusy(null);
      }
    },
    [filter, refreshBoard, refreshClasses],
  );

  const handleRetryClassSync = useCallback(
    async (classId: string) => {
      setBusy(`class-sync:${classId}`);
      setError(null);
      try {
        await syncShippingClass(classId);
        await refreshClasses();
      } catch (syncError) {
        setError(errorMessage(syncError));
      } finally {
        setBusy(null);
      }
    },
    [refreshClasses],
  );

  const handleDeleteClass = useCallback(
    async (classId: string) => {
      setBusy(`class-delete:${classId}`);
      setError(null);
      setNotice(null);
      try {
        const result = await deleteShippingClass(classId);
        setNotice(
          result.deleted
            ? "本地草稿模板已删除（未同步过 Woo，无需远端操作）。"
            : "删除任务已派给 n8n——Woo 侧删除成功回报后，本地模板会自动消失。",
        );
        await refreshClasses();
      } catch (deleteError) {
        setError(errorMessage(deleteError));
      } finally {
        setBusy(null);
      }
    },
    [refreshClasses],
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
        <div className={styles.statCard} data-tone="failed">
          <span className={styles.statLabel}>待填单号</span>
          <span className={styles.statValue}>
            {loading ? "—" : orderSummary.pending}
          </span>
        </div>
        <div className={styles.statCard} data-tone="flight">
          <span className={styles.statLabel}>运输中</span>
          <span className={styles.statValue}>
            {loading ? "—" : orderSummary.in_transit}
          </span>
        </div>
        <div className={styles.statCard} data-tone="success">
          <span className={styles.statLabel}>已签收</span>
          <span className={styles.statValue}>
            {loading ? "—" : orderSummary.delivered}
          </span>
        </div>
        <div className={styles.statCard} data-tone="failed">
          <span className={styles.statLabel}>异常</span>
          <span className={styles.statValue}>
            {loading ? "—" : orderSummary.exception}
          </span>
        </div>
      </div>

      {!loading && orderSummary.pending > 0 ? (
        <p className={styles.notice}>
          有 {orderSummary.pending} 个订单等待填写运单号——填入后自动注册 17TRACK 轨迹并回传 Woo 订单。
        </p>
      ) : null}

      {error ? (
        <div className={styles.state} role="alert">
          <AlertTriangle aria-hidden="true" size={16} />
          <span>{error}</span>
        </div>
      ) : null}
      {notice ? <p className={styles.notice}>{notice}</p> : null}

      <div className={styles.tabs} role="tablist">
        <button
          className={`${styles.tab} ${activeTab === "orders" ? styles.tabOn : ""}`}
          onClick={() => setActiveTab("orders")}
          role="tab"
          type="button"
        >
          订单与物流{" "}
          <span className={styles.tabCount}>
            {orderSummary.pending +
              orderSummary.in_transit +
              orderSummary.delivered +
              orderSummary.exception}
          </span>
        </button>
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

      {activeTab === "orders" ? (
        <section className={styles.panel} aria-label="订单与物流">
          <div className={styles.filterRow}>
            {ORDER_FILTERS.map((option) => (
              <button
                className={`secondary-button ${orderFilter === option.key ? styles.tabOn : ""}`}
                disabled={orderLoading || busy !== null}
                key={option.key}
                onClick={() => void handleOrderFilter(option.key)}
                type="button"
              >
                {option.label}
              </button>
            ))}
          </div>
          {loading || orderLoading ? (
            <div className={styles.state}>
              <LoaderCircle aria-hidden="true" className="spin" size={16} />
              <span>正在加载…</span>
            </div>
          ) : orders.length === 0 ? (
            <div className={styles.emptyHint}>
              还没有订单数据。n8n 的订单同步流配置好后，Woo 订单会自动出现在这里。
            </div>
          ) : (
            <div className={styles.tableScroll}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>订单</th>
                    <th>国家</th>
                    <th>金额</th>
                    <th>商品</th>
                    <th>下单时间</th>
                    <th>运单号</th>
                    <th>轨迹</th>
                    <th>回传</th>
                  </tr>
                </thead>
                <tbody>
                  {orders.map((order) => {
                    const trackingBusy = busy === `tracking:${order.id}`;
                    const refreshBusy =
                      busy === `refresh-tracking:${order.id}`;
                    const isEditing =
                      !order.tracking_number || editingTracking.has(order.id);
                    const isExpanded = expandedOrders.has(order.id);
                    const itemCount = (order.items_json ?? []).reduce(
                      (total, item) => total + item.qty,
                      0,
                    );
                    const firstItem = order.items_json?.[0];
                    return (
                      <Fragment key={order.id}>
                        <tr>
                          <td className={styles.productCell}>
                            <strong>{order.order_number}</strong>
                            <span>{order.customer_name ?? "—"}</span>
                          </td>
                          <td>{order.country ?? "—"}</td>
                          <td>
                            {order.total === null
                              ? "—"
                              : `${order.currency ?? ""} ${order.total}`.trim()}
                          </td>
                          <td
                            className={styles.productCell}
                            title={orderItemsTitle(order) || undefined}
                          >
                            <strong>{firstItem?.name ?? "—"}</strong>
                            {itemCount > 1 ? <span>等 {itemCount} 件</span> : null}
                          </td>
                          <td className={styles.timeCell}>
                            {formatDateTime(order.placed_at)}
                          </td>
                          <td>
                            {isEditing ? (
                              <span className={styles.trackingEditor}>
                                <input
                                  className={styles.formInput}
                                  disabled={trackingBusy || busy !== null}
                                  onChange={(event) =>
                                    setTrackingDrafts((current) => ({
                                      ...current,
                                      [order.id]: event.target.value,
                                    }))
                                  }
                                  placeholder="填入运单号，如 YT2513…"
                                  value={trackingDrafts[order.id] ?? ""}
                                />
                                <button
                                  className="secondary-button"
                                  disabled={
                                    trackingBusy ||
                                    busy !== null ||
                                    (!(trackingDrafts[order.id] ?? "").trim() &&
                                      !order.tracking_number)
                                  }
                                  onClick={() => void handleSaveTracking(order)}
                                  type="button"
                                >
                                  保存
                                </button>
                              </span>
                            ) : (
                              <span className={styles.actionRow}>
                                <button
                                  className={styles.linkButton}
                                  disabled={busy !== null}
                                  onClick={() =>
                                    setEditingTracking((current) => {
                                      const next = new Set(current);
                                      next.add(order.id);
                                      return next;
                                    })
                                  }
                                  title="更换运单号会重新消耗一次 17TRACK 注册额度"
                                  type="button"
                                >
                                  {order.tracking_number}
                                </button>
                                <span
                                  className={styles.statusBadge}
                                  data-status={order.tracking_status}
                                >
                                  {TRACKING_STATUS_LABELS[order.tracking_status]}
                                </span>
                              </span>
                            )}
                          </td>
                          <td>
                            {order.tracking_number ? (
                              <span className={styles.actionRow}>
                                <button
                                  className={styles.linkButton}
                                  onClick={() =>
                                    setExpandedOrders((current) => {
                                      const next = new Set(current);
                                      if (next.has(order.id)) next.delete(order.id);
                                      else next.add(order.id);
                                      return next;
                                    })
                                  }
                                  type="button"
                                >
                                  {isExpanded ? "收起" : "查看轨迹"}
                                </button>
                                <button
                                  className="secondary-button"
                                  disabled={refreshBusy || busy !== null}
                                  onClick={() =>
                                    void handleRefreshTracking(order.id)
                                  }
                                  type="button"
                                >
                                  刷新轨迹
                                </button>
                              </span>
                            ) : (
                              "—"
                            )}
                          </td>
                          <td>
                            <span
                              className={styles.statusBadge}
                              data-status={order.writeback_status}
                            >
                              {WRITEBACK_STATUS_LABELS[order.writeback_status]}
                            </span>
                          </td>
                        </tr>
                        {isExpanded ? (
                          <tr>
                            <td colSpan={8}>
                              <div className={styles.trackingTimeline}>
                                {(order.tracking_events_json ?? []).length > 0 ? (
                                  (order.tracking_events_json ?? []).map(
                                    (event, index) => (
                                      <p
                                        className={styles.mutedLine}
                                        key={`${event.time ?? "event"}-${index}`}
                                      >
                                        <span className={styles.timeCell}>
                                          {formatDateTime(event.time)}
                                        </span>{" "}
                                        {event.location ? `${event.location} ` : ""}
                                        {event.description ?? "—"}
                                      </p>
                                    ),
                                  )
                                ) : (
                                  <p className={styles.mutedLine}>—</p>
                                )}
                              </div>
                            </td>
                          </tr>
                        ) : null}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ) : null}

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
            slug 必须与 WooCommerce 后台的运费类别 slug 完全一致；「保存并同步到 Woo」会经 n8n 直接写入 Woo 后台，区域名需与 Woo 配送区域名一致。
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
                    <th>描述</th>
                    <th>线路</th>
                    <th>启用</th>
                    <th>备注</th>
                    <th>区域费率</th>
                    <th>同步状态</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {classDrafts.map((row) => {
                    const rowBusy = busy === `class:${row.key}`;
                    const syncInFlight = row.sync_status === "pending";
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
                            disabled={syncInFlight}
                            onChange={(event) =>
                              updateClassDraft(row.key, {
                                name: event.target.value,
                              })
                            }
                            value={row.name}
                          />
                        </td>
                        <td>
                          <input
                            className={styles.formInput}
                            disabled={syncInFlight}
                            onChange={(event) =>
                              updateClassDraft(row.key, {
                                description: event.target.value,
                              })
                            }
                            value={row.description}
                          />
                        </td>
                        <td>
                          <select
                            className={styles.formInput}
                            disabled={syncInFlight}
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
                            disabled={row.id === null || syncInFlight}
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
                            disabled={syncInFlight}
                            onChange={(event) =>
                              updateClassDraft(row.key, {
                                notes: event.target.value,
                              })
                            }
                            value={row.notes}
                          />
                        </td>
                        <td>
                          <span className={styles.zoneRates}>
                            {row.zone_rates.map((rate, index) => (
                              <span
                                className={styles.zoneRateRow}
                                key={`${row.key}-zone-${index}`}
                              >
                                <input
                                  aria-label="区域名"
                                  className={styles.formInput}
                                  disabled={syncInFlight}
                                  onChange={(event) =>
                                    updateZoneRate(row.key, index, {
                                      zone_name: event.target.value,
                                    })
                                  }
                                  placeholder="zone_name"
                                  value={rate.zone_name}
                                />
                                <input
                                  aria-label="基础运费"
                                  className={styles.formInput}
                                  disabled={syncInFlight}
                                  inputMode="decimal"
                                  onChange={(event) =>
                                    updateZoneRate(row.key, index, {
                                      base_cost: event.target.value,
                                    })
                                  }
                                  placeholder="base_cost"
                                  value={rate.base_cost}
                                />
                                <input
                                  aria-label="类别运费"
                                  className={styles.formInput}
                                  disabled={syncInFlight}
                                  inputMode="decimal"
                                  onChange={(event) =>
                                    updateZoneRate(row.key, index, {
                                      class_cost: event.target.value,
                                    })
                                  }
                                  placeholder="class_cost"
                                  value={rate.class_cost}
                                />
                                <button
                                  aria-label="删除区域"
                                  className={styles.linkButton}
                                  disabled={syncInFlight}
                                  onClick={() => removeZoneRate(row.key, index)}
                                  type="button"
                                >
                                  ✕
                                </button>
                              </span>
                            ))}
                            <button
                              className={styles.linkButton}
                              disabled={syncInFlight}
                              onClick={() => addZoneRate(row.key)}
                              type="button"
                            >
                              + 加区域
                            </button>
                          </span>
                        </td>
                        <td>
                          <span
                            className={styles.statusBadge}
                            data-status={row.sync_status}
                            title={row.sync_error ?? undefined}
                          >
                            {SYNC_STATUS_LABELS[row.sync_status]}
                          </span>
                        </td>
                        <td>
                          <span className={styles.actionRow}>
                            <button
                              className="secondary-button"
                              disabled={
                                rowBusy ||
                                busy !== null ||
                                syncInFlight ||
                                !row.slug.trim() ||
                                !row.name.trim()
                              }
                              onClick={() => void handleSaveClass(row, false)}
                              type="button"
                            >
                              保存草稿
                            </button>
                            <button
                              className="primary-button"
                              disabled={
                                rowBusy ||
                                busy !== null ||
                                syncInFlight ||
                                !row.slug.trim() ||
                                !row.name.trim()
                              }
                              onClick={() => void handleSaveClass(row, true)}
                              type="button"
                            >
                              保存并同步到 Woo
                            </button>
                            {row.id && row.sync_status === "failed" ? (
                              <button
                                className="secondary-button"
                                disabled={
                                  busy === `class-sync:${row.id}` || busy !== null
                                }
                                onClick={() =>
                                  void handleRetryClassSync(row.id as string)
                                }
                                type="button"
                              >
                                重试同步
                              </button>
                            ) : null}
                            {row.id ? (
                              <button
                                className="secondary-button"
                                disabled={rowBusy || busy !== null || syncInFlight}
                                onClick={() =>
                                  void handleDeleteClass(row.id as string)
                                }
                                title="已同步过的会先删 Woo 侧（经 n8n），回报成功后本地删除；有产品挂靠时会被拒绝"
                                type="button"
                              >
                                删除
                              </button>
                            ) : null}
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
