"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import styles from "./AmzWorkspace.module.css";
import {
  deleteGrant,
  getEmployees,
  getGrants,
  getSeedImports,
  getStores,
  upsertGrant,
  type AmzEmployee,
  type AmzGrant,
  type AmzSeedImport,
  type AmzStore,
} from "./api";

const ROLE_LABEL: Record<string, string> = { view: "查看", operate: "操作", grant: "授权" };
const EMPLOYEE_TONE: Record<string, string> = { A: "toneA", B: "toneB", C: "toneC", D: "toneD" };

function money(value: number, currency: string) {
  const symbol = currency === "EUR" ? "€" : "$";
  return `${symbol}${Math.round(value).toLocaleString("en-US")}`;
}

function acosClass(acos: number | null) {
  if (acos === null) return styles.muted;
  if (acos >= 45) return styles.bad;
  if (acos >= 35) return styles.warn;
  return styles.good;
}

/**
 * A0 的工作台:店铺一张表(按公司分组 + 合计)、种子导入台账、店铺授权、员工名片。
 * 两条线 / 员工消息 / 浮窗随 A2 来;这里先把「五店一表」和「谁能看哪个店」立住。
 */
export function AmzWorkspace() {
  const [stores, setStores] = useState<AmzStore[]>([]);
  const [isOwner, setIsOwner] = useState(false);
  const [seeds, setSeeds] = useState<AmzSeedImport[]>([]);
  const [employees, setEmployees] = useState<AmzEmployee[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    // 一路失败不吞掉另一路已经成功的结果。
    const [storesResult, seedsResult, employeesResult] = await Promise.allSettled([
      getStores(),
      getSeedImports(),
      getEmployees(),
    ]);
    const errors: string[] = [];
    if (storesResult.status === "fulfilled") {
      setStores(storesResult.value.items);
      setIsOwner(storesResult.value.is_owner);
    } else {
      errors.push(String(storesResult.reason?.message ?? storesResult.reason));
    }
    if (seedsResult.status === "fulfilled") setSeeds(seedsResult.value.items);
    else errors.push(String(seedsResult.reason?.message ?? seedsResult.reason));
    if (employeesResult.status === "fulfilled") setEmployees(employeesResult.value.items);
    else errors.push(String(employeesResult.reason?.message ?? employeesResult.reason));
    setError(errors.length ? errors.join(" / ") : null);
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const totals = useMemo(() => {
    const byCurrency = new Map<string, { spend: number; sales: number; orders: number; stores: number }>();
    for (const store of stores) {
      const bucket = byCurrency.get(store.currency) ?? { spend: 0, sales: 0, orders: 0, stores: 0 };
      bucket.spend += store.ads.spend;
      bucket.sales += store.ads.sales;
      bucket.orders += store.ads.orders;
      bucket.stores += 1;
      byCurrency.set(store.currency, bucket);
    }
    return Array.from(byCurrency.entries());
  }, [stores]);

  return (
    <div className={styles.workspace}>
      <div className={styles.topbar}>
        <div className={styles.mode}>
          <span className={styles.dot} />
          影子模式 · 只记不做 · 至少一个月
        </div>
        <button className={styles.button} onClick={() => void load()} type="button">
          刷新
        </button>
      </div>
      {error ? <div className={styles.error}>{error}</div> : null}

      <section className={styles.panel} aria-label="店铺">
        <div className={styles.panelHead}>
          <h2>店铺</h2>
          <span className={styles.muted}>
            {isOwner ? "owner · 全部店铺" : `你被授权的店铺 · ${stores.length} 个`} · 数字是已导入期(种子报表)的合计
          </span>
        </div>
        <div className={styles.totals}>
          {totals.map(([currency, bucket]) => {
            const acos = bucket.sales > 0 ? Math.round((bucket.spend / bucket.sales) * 1000) / 10 : null;
            return (
              <div className={styles.total} key={currency}>
                <span className={styles.totalLabel}>
                  {currency} 合计 · {bucket.stores} 店
                </span>
                <b className={acosClass(acos)}>{acos === null ? "—" : `${acos}%`}</b>
                <span className={styles.muted}>
                  花费 {money(bucket.spend, currency)} · 广告销售 {money(bucket.sales, currency)} · 单 {bucket.orders}
                </span>
              </div>
            );
          })}
          {totals.length === 0 && !loading ? <div className={styles.muted}>还没有店铺数据。</div> : null}
        </div>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>店铺</th>
                <th>公司</th>
                <th>站点</th>
                <th>ACOS</th>
                <th>花费</th>
                <th>广告销售</th>
                <th>订单</th>
                <th>数据期</th>
                <th>交易行</th>
                <th>我的角色</th>
              </tr>
            </thead>
            <tbody>
              {stores.map((store) => (
                <tr key={store.store_code}>
                  <td>
                    <b>{store.display_name}</b> <code>{store.store_code}</code>
                  </td>
                  <td>{store.company_name}</td>
                  <td>
                    {store.country} · {store.region.toUpperCase()}
                  </td>
                  <td className={acosClass(store.ads.acos_pct)}>
                    {store.ads.acos_pct === null ? "—" : `${store.ads.acos_pct}%`}
                  </td>
                  <td>{money(store.ads.spend, store.currency)}</td>
                  <td>{money(store.ads.sales, store.currency)}</td>
                  <td>{store.ads.orders}</td>
                  <td className={styles.muted}>
                    {store.ads.first_date ? `${store.ads.first_date} → ${store.ads.last_date}` : "—"}
                  </td>
                  <td>{store.transactions.rows}</td>
                  <td>
                    <span className={styles.pill}>{ROLE_LABEL[store.role] ?? store.role}</span>
                  </td>
                </tr>
              ))}
              {stores.length === 0 && !loading ? (
                <tr>
                  <td className={styles.muted} colSpan={10}>
                    没有你能看的店铺。owner 或持有「授权」角色的人可以在下面给你开。
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      <section className={styles.panel} aria-label="数字员工">
        <div className={styles.panelHead}>
          <h2>数字员工</h2>
          <span className={styles.muted}>四名 · 各管一块 · A2 起上岗,消息与浮窗随之而来</span>
        </div>
        <div className={styles.crew}>
          {employees.map((item) => (
            <div className={styles.emp} key={item.employee}>
              <span className={`${styles.avatar} ${styles[EMPLOYEE_TONE[item.employee] ?? "toneA"]}`}>{item.employee}</span>
              <div>
                <div className={styles.empRole}>{item.name ?? item.employee} · {item.role_label}</div>
                <div className={styles.muted}>{item.character ?? item.username}</div>
              </div>
            </div>
          ))}
        </div>
      </section>

      {stores.some((store) => store.role === "grant") ? (
        <GrantsPanel stores={stores.filter((store) => store.role === "grant")} />
      ) : null}

      <section className={styles.panel} aria-label="种子导入">
        <div className={styles.panelHead}>
          <h2>种子导入台账</h2>
          <span className={styles.muted}>var/amazon/seed · 每日搜索词 + 交易一览 · 同一份文件绝不导两遍</span>
        </div>
        {seeds.length === 0 ? (
          <div className={styles.muted}>还没有导入记录。</div>
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>文件</th>
                  <th>店铺</th>
                  <th>类型</th>
                  <th>解析行</th>
                  <th>新插入</th>
                  <th>导入时间</th>
                </tr>
              </thead>
              <tbody>
                {seeds.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <code>{item.file_name}</code>
                    </td>
                    <td>{item.store_code}</td>
                    <td>{item.kind === "ads_search_terms" ? "搜索词日报" : "交易一览"}</td>
                    <td>{item.rows}</td>
                    <td>{String(item.details.inserted ?? "—")}</td>
                    <td className={styles.muted}>{item.imported_at ? item.imported_at.slice(0, 16).replace("T", " ") : "—"}</td>
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

function GrantsPanel({ stores }: { stores: AmzStore[] }) {
  const [storeCode, setStoreCode] = useState(stores[0]?.store_code ?? "");
  const [grants, setGrants] = useState<AmzGrant[]>([]);
  const [userId, setUserId] = useState("");
  const [role, setRole] = useState("view");
  const [status, setStatus] = useState<string | null>(null);

  const load = useCallback(async (code: string) => {
    if (!code) return;
    try {
      const payload = await getGrants(code);
      setGrants(payload.items);
      setStatus(null);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void load(storeCode);
  }, [load, storeCode]);

  async function submit() {
    const id = Number(userId);
    if (!Number.isInteger(id) || id <= 0) {
      setStatus("用户 id 要是正整数(用户管理页里看)。");
      return;
    }
    try {
      await upsertGrant(storeCode, id, role);
      setUserId("");
      setStatus("已保存");
      await load(storeCode);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    }
  }

  async function remove(id: number) {
    try {
      await deleteGrant(storeCode, id);
      setStatus("已移除");
      await load(storeCode);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <section className={styles.panel} aria-label="店铺授权">
      <div className={styles.panelHead}>
        <h2>店铺授权</h2>
        <span className={styles.muted}>人维度的门 · 只 owner 绕过 · super_admin 也要有行 · 查看 &lt; 操作 &lt; 授权</span>
      </div>
      <div className={styles.grantRow}>
        <label>
          店铺
          <select id="amz-grant-store" onChange={(event) => setStoreCode(event.target.value)} value={storeCode}>
            {stores.map((store) => (
              <option key={store.store_code} value={store.store_code}>
                {store.display_name} · {store.store_code}
              </option>
            ))}
          </select>
        </label>
        <label>
          用户 id
          <input
            id="amz-grant-user"
            inputMode="numeric"
            onChange={(event) => setUserId(event.target.value)}
            placeholder="用户管理页里的 id"
            value={userId}
          />
        </label>
        <label>
          角色
          <select id="amz-grant-role" onChange={(event) => setRole(event.target.value)} value={role}>
            <option value="view">查看</option>
            <option value="operate">操作</option>
            <option value="grant">授权</option>
          </select>
        </label>
        <button className={styles.button} onClick={() => void submit()} type="button">
          保存
        </button>
        {status ? <span className={styles.muted}>{status}</span> : null}
      </div>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>用户 id</th>
              <th>角色</th>
              <th>授权人</th>
              <th>时间</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {grants.map((grant) => (
              <tr key={grant.user_id}>
                <td>{grant.user_id}</td>
                <td>
                  <span className={styles.pill}>{ROLE_LABEL[grant.role] ?? grant.role}</span>
                </td>
                <td>{grant.granted_by_user_id ?? "—"}</td>
                <td className={styles.muted}>{grant.created_at ? grant.created_at.slice(0, 16).replace("T", " ") : "—"}</td>
                <td>
                  <button className={styles.linkButton} onClick={() => void remove(grant.user_id)} type="button">
                    移除
                  </button>
                </td>
              </tr>
            ))}
            {grants.length === 0 ? (
              <tr>
                <td className={styles.muted} colSpan={5}>
                  这个店还没有任何授权行(owner 不需要行)。
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}
