"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { OverlayModal } from "@/components/overlay-modal";

import styles from "./AmzOverview.module.css";
import { AmzSeriesChart } from "./AmzSeriesChart";
import {
  decideSuggestion,
  getEmployeePanel,
  getOverviewSeries,
  getStores,
  getSuggestions,
  type AmzEmployeePanel,
  type AmzEmployeePanelItem,
  type AmzSeries,
  type AmzStore,
  type AmzSuggestion,
} from "./api";

const TONE: Record<string, string> = { A: styles.toneA, B: styles.toneB, C: styles.toneC, D: styles.toneD };
const SEVERITY_LABEL: Record<string, string> = { bad: "紧急", warn: "要看", info: "提示", good: "好消息" };
const ACTION_LABEL: Record<string, string> = {
  harvest: "收割",
  negative: "否词",
  demand_reserve: "需求储备",
  bid_down: "精准倒挂",
  campaign_stability: "活动稳定性",
  loss_line: "亏卖线",
  spend_without_sales: "花费涨销量跌",
  season_countdown: "季节倒计时",
};
const STORE_FLAG: Record<string, string> = { US: "🇺🇸", DE: "🇩🇪" };

function money(value: number, currency = "USD") {
  const symbol = currency === "EUR" ? "€" : "$";
  return `${symbol}${Math.round(value).toLocaleString("en-US")}`;
}

function acosTone(acos: number | null) {
  if (acos === null) return styles.muted;
  if (acos >= 45) return styles.bad;
  if (acos >= 35) return styles.warn;
  return styles.good;
}

function phaseOf(store: AmzStore): { label: string; cls: string } {
  // 季节相位在 A4 由数据算;现在按店里的主产品线给固定标签(种子期)。
  if (store.store_code === "05us") return { label: "热水棒预热期", cls: styles.phPre };
  return { label: "尾季", cls: styles.phTail };
}

/**
 * A 系列总览(设计稿第五版):五店+合计卡 → 员工面板(通知条/未读/最新消息)→ 两条线 → 季节相位;
 * 员工卡点开是浮窗,里面是他发来的消息,放行/驳回/稍后只记录(影子期)。<900px 单列 + 底部 tab。
 */
export function AmzOverview() {
  const [stores, setStores] = useState<AmzStore[]>([]);
  const [isOwner, setIsOwner] = useState(false);
  const [panel, setPanel] = useState<AmzEmployeePanel | null>(null);
  const [series, setSeries] = useState<AmzSeries | null>(null);
  const [storeFilter, setStoreFilter] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [openEmployee, setOpenEmployee] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [s, p, c] = await Promise.allSettled([
      getStores(),
      getEmployeePanel(),
      getOverviewSeries({ store: storeFilter || undefined, days: 30 }),
    ]);
    const errors: string[] = [];
    if (s.status === "fulfilled") {
      setStores(s.value.items);
      setIsOwner(s.value.is_owner);
    } else errors.push(String(s.reason?.message ?? s.reason));
    if (p.status === "fulfilled") setPanel(p.value);
    else errors.push(String(p.reason?.message ?? p.reason));
    if (c.status === "fulfilled") setSeries(c.value);
    else errors.push(String(c.reason?.message ?? c.reason));
    setError(errors.length ? errors.join(" / ") : null);
  }, [storeFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const visibleStores = useMemo(
    () => (storeFilter ? stores.filter((s) => s.store_code === storeFilter) : stores),
    [stores, storeFilter],
  );

  const totals = useMemo(() => {
    // 合计按美元:欧元卡上有原值,合计里按种子期固定汇率 1.08 折(A1 后按当日汇率)。
    const fx = (s: AmzStore) => (s.currency === "EUR" ? 1.08 : 1);
    const spend = visibleStores.reduce((n, s) => n + s.ads.spend * fx(s), 0);
    const sales = visibleStores.reduce((n, s) => n + s.ads.sales * fx(s), 0);
    const orders = visibleStores.reduce((n, s) => n + s.ads.orders, 0);
    const acos = sales > 0 ? Math.round((spend / sales) * 1000) / 10 : null;
    return { spend, sales, orders, acos, hasEur: visibleStores.some((s) => s.currency === "EUR") };
  }, [visibleStores]);

  const closeDrawer = useCallback(() => setOpenEmployee(null), []);
  const openItem = panel?.items.find((item) => item.employee === openEmployee) ?? null;

  return (
    <div className={styles.page}>
      <header className={styles.top} id="amz-top">
        <div className={styles.mode}>
          <span className={styles.dot} />
          影子模式 · 只记不做 · 至少一个月
        </div>
        <nav className={styles.filters} aria-label="店铺筛选">
          <button className={`${styles.chip} ${storeFilter === "" ? styles.chipOn : ""}`} onClick={() => setStoreFilter("")} type="button">
            所有店铺
          </button>
          {stores.map((s) => (
            <button
              className={`${styles.chip} ${styles.chipMono} ${storeFilter === s.store_code ? styles.chipOn : ""}`}
              key={s.store_code}
              onClick={() => setStoreFilter(s.store_code)}
              type="button"
            >
              {s.store_code} {s.display_name.replace(" 美国", "").replace(" 德国", "")} {STORE_FLAG[s.country] ?? ""}
            </button>
          ))}
        </nav>
      </header>
      {error ? <div className={styles.error}>{error}</div> : null}

      {/* ===== 店卡 ===== */}
      <section className={styles.fleet} id="amz-stores" aria-label="店铺总览">
        <article className={`${styles.store} ${styles.storeTotal}`}>
          <div className={styles.head}>
            <span className={styles.code}>ALL</span>
            <span className={styles.name}>{visibleStores.length} 店合计 · USD</span>
            {totals.hasEur ? <span className={`${styles.phase} ${styles.phMixed}`}>€ 按 1.08 折(种子期)</span> : null}
          </div>
          <div className={styles.big}>
            <span className={`${styles.v} ${acosTone(totals.acos)}`}>
              {totals.acos === null ? "—" : totals.acos}
              <small>%</small>
            </span>
            <span className={styles.k}>ACOS · 加权</span>
          </div>
          <div className={styles.row}>
            <div><b>{money(totals.spend)}</b><span>广告花费</span></div>
            <div><b>{money(totals.sales)}</b><span>广告销售额</span></div>
            <div><b>{totals.orders}</b><span>订单</span></div>
          </div>
          <div className={styles.alerts}>
            {panel ? (
              <>
                {panel.urgent_total > 0 ? <span className={`${styles.pip} ${styles.pipBad}`} /> : <span className={`${styles.pip} ${styles.pipGood}`} />}
                {panel.urgent_total} 紧急 · {panel.open_total} 条待你看 · TACOS 待订单接入
              </>
            ) : (
              "—"
            )}
          </div>
        </article>
        {visibleStores.map((s) => {
          const ph = phaseOf(s);
          const acos = s.ads.acos_pct;
          return (
            <article className={styles.store} key={s.store_code}>
              <div className={styles.head}>
                <span className={styles.code}>{s.store_code.toUpperCase()}</span>
                <span className={styles.name}>{s.display_name}</span>
                <span className={`${styles.phase} ${ph.cls}`}>{ph.label}</span>
              </div>
              <div className={styles.big}>
                <span className={`${styles.v} ${acosTone(acos)}`}>
                  {acos === null ? "—" : acos}
                  <small>%</small>
                </span>
                <span className={styles.k}>ACOS</span>
              </div>
              <div className={styles.row}>
                <div><b>{money(s.ads.spend, s.currency)}</b><span>花费</span></div>
                <div><b>{money(s.ads.sales, s.currency)}</b><span>销售额</span></div>
                <div><b>{s.ads.orders}</b><span>订单</span></div>
              </div>
              <div className={styles.alerts}>
                <span className={styles.muted}>
                  {s.ads.first_date ? `${s.ads.first_date} → ${s.ads.last_date}` : "尚无广告数据"} · 交易 {s.transactions.rows} 行
                </span>
              </div>
            </article>
          );
        })}
      </section>

      <div className={styles.grid}>
        {/* ===== 员工面板 ===== */}
        <section className={styles.panel} id="amz-crew" aria-label="数字员工">
          <header className={styles.panelHead}>
            <h2>数字员工</h2>
            <span className={styles.cnt}>4 名 · 各管一块</span>
            <span className={styles.right}>都在用户管理登记 · C19 可私聊</span>
          </header>
          {panel ? (
            <div className={styles.notif}>
              <span className={styles.bell}>🔔</span>
              <b>今天 4 名员工发来 {panel.open_total} 条消息</b>
              {panel.urgent_total > 0 ? (
                <span className={styles.urgent}>
                  {panel.urgent_total} 条紧急 · {panel.items.find((i) => i.urgent > 0)?.latest?.title.slice(0, 40) ?? ""}
                </span>
              ) : (
                <span className={styles.muted}>没有紧急的</span>
              )}
              <span className={styles.notifNote}>全在影子模式,只等你点一下</span>
            </div>
          ) : null}
          <div className={styles.crew}>
            {(panel?.items ?? []).map((item) => (
              <button
                className={`${styles.emp} ${item.urgent > 0 ? styles.empUrgent : ""}`}
                key={item.employee}
                onClick={() => setOpenEmployee(item.employee)}
                type="button"
              >
                <span className={`${styles.avatar} ${TONE[item.employee] ?? styles.toneA}`}>{item.employee}</span>
                {item.open > 0 ? <span className={styles.badge}>{item.open}</span> : null}
                <span className={styles.role}>{item.role_label}</span>
                <span className={styles.duty}>{item.username}</span>
                <span className={styles.mline}>
                  <i className={`${styles.pip} ${item.urgent > 0 ? styles.pipBad : item.open > 0 ? styles.pipWarn : styles.pipGood}`} />
                  {item.latest ? item.latest.title : item.employee === "D" ? "今天没有新消息" : "A2 后半段上岗,现在还没有消息"}
                </span>
              </button>
            ))}
          </div>
        </section>

        {/* ===== 两条线 + 季节 ===== */}
        <div className={styles.charts} id="amz-ads">
          <section className={`${styles.panel} ${styles.chart}`} aria-label="TACOS 走势">
            <div className={styles.chartTitle}>
              <h3>TACOS · {storeFilter || "全部店铺"}</h3>
              <span className={styles.example}>日粒度 · 种子期 · API 接上后换今天 vs 昨天按小时</span>
            </div>
            <AmzSeriesChart
              days={series?.days ?? []}
              pick={(d) => d.tacos_pct}
              unit="%"
              target={15}
              targetLabel="目标 15%"
              tone="accent"
            />
            <div className={styles.legend}>
              <span><i className={styles.legAccent} />TACOS = 广告花费 ÷ 总销售额(交易一览 Order 行)</span>
              <span><i className={styles.legDash} />目标</span>
            </div>
          </section>
          <section className={`${styles.panel} ${styles.chart}`} aria-label="总销售额走势">
            <div className={styles.chartTitle}>
              <h3>总销售额 · {storeFilter || "全部店铺"}</h3>
              <span className={styles.example}>日粒度 · 已按当日汇率折美元</span>
            </div>
            <AmzSeriesChart days={series?.days ?? []} pick={(d) => d.sales_usd} unit="$" tone="good" />
            <div className={styles.legend}>
              <span><i className={styles.legGood} />总销售额(自然 + 广告)</span>
              <span className={styles.muted}>两条线必须一起看:TACOS 降、销售额也降 = 萎缩</span>
            </div>
          </section>
          <section className={styles.panel} aria-label="季节相位">
            <header className={styles.panelHead}>
              <h2>季节相位</h2>
              <span className={styles.right}>种子期按夏季数据定;A4 起从销量 + 词频 + 竞品 BSR 叠出来</span>
            </header>
            <SeasonStrip />
          </section>
        </div>
      </div>

      {openItem ? (
        <OverlayModal label={`${openItem.employee} · ${openItem.role_label}`} onClose={closeDrawer} placement="drawer" width="min(760px, 100%)">
          <EmployeeDrawer item={openItem} onChanged={load} storeFilter={storeFilter} />
        </OverlayModal>
      ) : null}

      <nav className={styles.tabs} aria-label="手机导航">
        <a className={styles.tab} href="#amz-top">总览</a>
        <a className={`${styles.tab} ${styles.tabMsg}`} href="#amz-crew">
          {panel && panel.open_total > 0 ? <span className={styles.tabBadge}>{panel.open_total}</span> : null}
          消息
        </a>
        <a className={styles.tab} href="#amz-stores">店铺</a>
        <a className={styles.tab} href="#amz-ads">广告</a>
        <a className={styles.tab} href="/amz?tab=manage">管理</a>
      </nav>
      {isOwner ? null : null}
    </div>
  );
}

function SeasonStrip() {
  // 今天那根红线的位置按当天在一年里的比例算。
  const now = new Date();
  const start = new Date(now.getFullYear(), 0, 1).getTime();
  const end = new Date(now.getFullYear() + 1, 0, 1).getTime();
  const todayPct = ((now.getTime() - start) / (end - start)) * 100;
  const label = `今天 ${now.getMonth() + 1}/${now.getDate()}`;
  const lanes = [
    { label: "Camping shower", sub: "01 · 03 · 04 同批货", segs: [["pre", 41, 13], ["peak", 54, 9], ["tail", 63, 11]] as const },
    { label: "Immersion heater", sub: "05 · 01us", segs: [["tail", 12, 8], ["pre", 76, 11], ["peak", 87, 13]] as const },
    { label: "热水棒 + 淋浴 套装", sub: "待王创鑫定店", segs: [["launch", 75, 5], ["peak", 80, 20]] as const },
  ];
  const segClass: Record<string, string> = { pre: styles.segPre, peak: styles.segPeak, tail: styles.segTail, launch: styles.segLaunch };
  const segLabel: Record<string, string> = { pre: "预热", peak: "旺季", tail: "尾季", launch: "上架窗口" };
  return (
    <div className={styles.season}>
      {lanes.map((lane) => (
        <div className={styles.lane} key={lane.label}>
          <div className={styles.laneLabel}>
            {lane.label}
            <small>{lane.sub}</small>
          </div>
          <div className={styles.track}>
            {lane.segs.map(([kind, left, width]) => (
              <div className={`${styles.seg} ${segClass[kind]}`} key={`${kind}-${left}`} style={{ left: `${left}%`, width: `${width}%` }}>
                {segLabel[kind]}
              </div>
            ))}
            <div className={styles.today} style={{ left: `${todayPct}%` }} data-label={label} />
          </div>
        </div>
      ))}
      <div className={styles.months}>
        {["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"].map((m) => (
          <span key={m}>{m}</span>
        ))}
      </div>
    </div>
  );
}

function EmployeeDrawer({ item, onChanged, storeFilter }: { item: AmzEmployeePanelItem; onChanged: () => Promise<void>; storeFilter: string }) {
  const [rows, setRows] = useState<AmzSuggestion[]>([]);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [showDecided, setShowDecided] = useState(false);

  const load = useCallback(async () => {
    try {
      const payload = await getSuggestions({ employee: item.employee, store: storeFilter || undefined, status: showDecided ? "all" : "open" });
      setRows(payload.items);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    }
  }, [item.employee, showDecided, storeFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  async function decide(row: AmzSuggestion, decision: "approve" | "reject" | "later") {
    const reason = (reasons[row.id] ?? "").trim();
    if (decision === "reject" && !reason) {
      setStatus("驳回要写一句原因——那句话是员工的教材。");
      return;
    }
    setBusy(row.id);
    try {
      await decideSuggestion(row.id, decision, reason || undefined);
      setStatus(decision === "approve" ? "已记录:放行(影子期不会碰亚马逊)" : decision === "reject" ? "已记录:驳回 + 原因" : "已记录:稍后");
      await load();
      await onChanged();
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className={styles.drawer}>
      <div className={styles.drawerHead}>
        <span className={`${styles.avatar} ${TONE[item.employee] ?? styles.toneA}`}>{item.employee}</span>
        <div>
          <b>{item.employee} · {item.role_label}员工</b>
          <div className={styles.muted}>
            {item.open} 条待看 · {item.urgent} 条紧急 · 影子模式:点「放行」只记录你的判断
          </div>
        </div>
        <label className={styles.toggle}>
          <input checked={showDecided} onChange={(e) => setShowDecided(e.target.checked)} type="checkbox" />
          含已处理
        </label>
      </div>
      {status ? <div className={styles.status}>{status}</div> : null}
      {rows.length === 0 ? (
        <div className={styles.empty}>
          {item.employee === "D" ? "没有消息。规则每天跑一次;种子数据停在 9 月中,新数据要等 A1 接上 API。" : "这名员工 A2 后半段上岗,现在还没有消息。"}
        </div>
      ) : (
        rows.map((row) => (
          <article className={`${styles.msg} ${styles[`sev_${row.severity}`] ?? ""}`} key={row.id}>
            <div className={styles.stripe} />
            <div>
              <div className={styles.meta}>
                <span className={styles.tag}>{row.store_code}</span>
                <span className={`${styles.tag} ${styles.tagAct}`}>{ACTION_LABEL[row.action_type] ?? row.action_type}</span>
                <span className={`${styles.tag} ${styles.tagLvl}`}>{row.level === "L0" ? "L0 影子" : row.level}</span>
                <span className={styles.muted}>
                  {SEVERITY_LABEL[row.severity] ?? row.severity} · 数据截至 {row.as_of ?? "—"}
                  {row.status !== "open" ? ` · 已${row.status === "approved" ? "放行" : row.status === "rejected" ? "驳回" : "搁置"}` : ""}
                </span>
              </div>
              <div className={styles.what}>{row.title}</div>
              <div className={styles.why}>{row.why}</div>
              {row.prediction ? (
                <div className={styles.pred}>
                  <span className={styles.predK}>预测</span>
                  <span>{row.prediction}</span>
                </div>
              ) : null}
              {row.reject_reason ? <div className={styles.pred}><span className={styles.predK}>原因</span><span>{row.reject_reason}</span></div> : null}
              {row.status === "open" ? (
                <div className={styles.actRow}>
                  <button className={`${styles.btn} ${styles.btnGo}`} disabled={busy === row.id} onClick={() => void decide(row, "approve")} type="button">
                    放行(记录)
                  </button>
                  <input
                    className={styles.reason}
                    id={`amz-reason-${row.id}`}
                    onChange={(e) => setReasons((prev) => ({ ...prev, [row.id]: e.target.value }))}
                    placeholder="驳回原因(必填)"
                    value={reasons[row.id] ?? ""}
                  />
                  <button className={`${styles.btn} ${styles.btnNo}`} disabled={busy === row.id} onClick={() => void decide(row, "reject")} type="button">
                    驳回
                  </button>
                  <button className={`${styles.btn} ${styles.btnNo}`} disabled={busy === row.id} onClick={() => void decide(row, "later")} type="button">
                    稍后
                  </button>
                </div>
              ) : null}
            </div>
          </article>
        ))
      )}
    </div>
  );
}
