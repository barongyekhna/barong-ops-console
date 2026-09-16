"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import styles from "./AmzWorkspace.module.css";
import {
  getFactSheets,
  judgeFactSheet,
  saveFactSheet,
  type AmzFactSheet,
  type AmzFactSheetFacts,
  type AmzStore,
} from "./api";

const LINE_LABEL: Record<string, string> = { pump: "沐浴泵", heater: "热水棒", flash: "太阳能手电", nail: "磨甲器", bundle: "套装", other: "其他" };
const USE_ORDER = ["copy", "image", "faq", "pnl"] as const;

type Draft = {
  product_line: string;
  store_code: string;
  sku: string;
  title: string;
  is: string;
  how_it_works: string;
  is_not: string;
  specsText: string;
  indicators: string;
  package: string;
  audience: string;
  misreadings: string;
  factory_cny: string;
  freight_cny: string;
  price_usd: string;
  competitor_asins: string;
  notes: string;
};

const EMPTY: Draft = {
  product_line: "pump",
  store_code: "",
  sku: "",
  title: "",
  is: "",
  how_it_works: "",
  is_not: "",
  specsText: "",
  indicators: "",
  package: "",
  audience: "",
  misreadings: "",
  factory_cny: "",
  freight_cny: "",
  price_usd: "",
  competitor_asins: "",
  notes: "",
};

function specsToText(specs: Record<string, string> | undefined) {
  return Object.entries(specs ?? {})
    .map(([key, value]) => `${key}: ${value}`)
    .join("\n");
}

function textToSpecs(text: string) {
  const out: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const idx = line.indexOf(":") >= 0 ? line.indexOf(":") : line.indexOf("：");
    if (idx <= 0) continue;
    const key = line.slice(0, idx).trim();
    const value = line.slice(idx + 1).trim();
    if (key && value) out[key] = value;
  }
  return out;
}

function toDraft(sheet: AmzFactSheet): Draft {
  const f = sheet.facts;
  return {
    product_line: sheet.product_line,
    store_code: sheet.store_code ?? "",
    sku: sheet.sku ?? "",
    title: sheet.title,
    is: f.is ?? "",
    how_it_works: f.how_it_works ?? "",
    is_not: f.is_not ?? "",
    specsText: specsToText(f.specs),
    indicators: f.indicators ?? "",
    package: f.package ?? "",
    audience: f.audience ?? "",
    misreadings: f.misreadings ?? "",
    factory_cny: f.cost?.factory_cny != null ? String(f.cost.factory_cny) : "",
    freight_cny: f.cost?.freight_cny != null ? String(f.cost.freight_cny) : "",
    price_usd: f.cost?.price_usd != null ? String(f.cost.price_usd) : "",
    competitor_asins: (f.competitor_asins ?? []).join(", "),
    notes: f.notes ?? "",
  };
}

function toFacts(draft: Draft): AmzFactSheetFacts {
  const cost: AmzFactSheetFacts["cost"] = {};
  if (draft.factory_cny.trim()) cost.factory_cny = Number(draft.factory_cny);
  if (draft.freight_cny.trim()) cost.freight_cny = Number(draft.freight_cny);
  if (draft.price_usd.trim()) cost.price_usd = Number(draft.price_usd);
  return {
    is: draft.is,
    how_it_works: draft.how_it_works,
    is_not: draft.is_not,
    specs: textToSpecs(draft.specsText),
    indicators: draft.indicators,
    package: draft.package,
    audience: draft.audience,
    misreadings: draft.misreadings,
    cost,
    competitor_asins: draft.competitor_asins
      .split(/[\s,，]+/)
      .map((s) => s.trim())
      .filter(Boolean),
    notes: draft.notes,
  };
}

/**
 * 产品事实表:A 系列自己的、手填的产品事实(与 K 零交集)。
 * 保存即代码判「够不够」(四个用途各自缺什么);「判一下」再让 DeepSeek 找矛盾和追问。
 * 不够的用途,笑笑不写、熊不画——门在代码里,这里只把「缺什么」摆出来。
 */
export function FactSheetPanel({ stores, canWrite }: { stores: AmzStore[]; canWrite: boolean }) {
  const [sheets, setSheets] = useState<AmzFactSheet[]>([]);
  const [uses, setUses] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const payload = await getFactSheets();
      setSheets(payload.items);
      setUses(payload.uses);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const current = useMemo(() => sheets.find((s) => s.id === selected) ?? null, [sheets, selected]);

  function pick(sheet: AmzFactSheet | null) {
    setSelected(sheet?.id ?? null);
    setDraft(sheet ? toDraft(sheet) : EMPTY);
    setStatus(null);
  }

  function set<K extends keyof Draft>(key: K, value: Draft[K]) {
    setDraft((prev) => ({ ...prev, [key]: value }));
  }

  async function save() {
    if (!draft.title.trim()) {
      setStatus("先给这份事实表起个名字,比如「沐浴泵 7800mAh」。");
      return;
    }
    setBusy(true);
    try {
      const saved = await saveFactSheet({
        product_line: draft.product_line,
        store_code: draft.store_code || null,
        sku: draft.sku.trim() || null,
        title: draft.title.trim(),
        facts: toFacts(draft),
      });
      await load();
      setSelected(saved.id);
      setDraft(toDraft(saved));
      setStatus(`已保存 v${saved.version}。下面是代码层的「够不够」。`);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function judge() {
    if (!current) return;
    setBusy(true);
    try {
      const judged = await judgeFactSheet(current.id);
      await load();
      setDraft(toDraft(judged));
      setStatus(judged.sufficiency.model_error ? `模型没接通(${judged.sufficiency.model_error}),清单判定照旧。` : "核对完了。");
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const verdict = current?.sufficiency;

  return (
    <section className={styles.panel} aria-label="产品事实表">
      <div className={styles.panelHead}>
        <h2>产品事实表</h2>
        <span className={styles.muted}>手填 · 与 K 系列零交集 · 不够的用途笑笑不写、熊不画</span>
      </div>
      <div className={styles.sheetLayout}>
        <div className={styles.sheetList}>
          <button className={`${styles.sheetItem} ${selected === null ? styles.sheetItemOn : ""}`} onClick={() => pick(null)} type="button">
            <span>＋ 新建一份</span>
            <small>按产品线;三店同款填一次共用</small>
          </button>
          {sheets.map((sheet) => {
            const ready = Object.values(sheet.sufficiency.ready ?? {}).filter(Boolean).length;
            return (
              <button className={`${styles.sheetItem} ${selected === sheet.id ? styles.sheetItemOn : ""}`} key={sheet.id} onClick={() => pick(sheet)} type="button">
                <span>{sheet.title}</span>
                <small>
                  {sheet.product_line_label}
                  {sheet.store_code ? ` · ${sheet.store_code}` : " · 跨店共用"}
                  {sheet.sku ? ` · ${sheet.sku}` : ""} · v{sheet.version} · 够用 {ready}/4
                </small>
              </button>
            );
          })}
          {sheets.length === 0 ? <div className={styles.muted}>还没有事实表。先建泵的那份,三店同款共用。</div> : null}
        </div>

        <div className={styles.sheetForm}>
          <div className={styles.sheetRow}>
            <label>
              产品线
              <select disabled={!canWrite} onChange={(e) => set("product_line", e.target.value)} value={draft.product_line}>
                {Object.entries(LINE_LABEL).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              店铺(留空 = 跨店共用)
              <select disabled={!canWrite} onChange={(e) => set("store_code", e.target.value)} value={draft.store_code}>
                <option value="">跨店共用</option>
                {stores.map((store) => (
                  <option key={store.store_code} value={store.store_code}>
                    {store.display_name} · {store.store_code}
                  </option>
                ))}
              </select>
            </label>
            <label>
              SKU(可选)
              <input disabled={!canWrite} onChange={(e) => set("sku", e.target.value)} placeholder="01-PCS-blue" value={draft.sku} />
            </label>
            <label>
              名字
              <input disabled={!canWrite} onChange={(e) => set("title", e.target.value)} placeholder="沐浴泵 7800mAh" value={draft.title} />
            </label>
          </div>
          <label>
            它是什么
            <textarea disabled={!canWrite} onChange={(e) => set("is", e.target.value)} placeholder="便携淋浴泵,7800mAh,IPX8,不加热,自带水温显示" value={draft.is} />
          </label>
          <label>
            怎么工作
            <textarea disabled={!canWrite} onChange={(e) => set("how_it_works", e.target.value)} placeholder="整机入水才抽水;三档水压;一次充电洗 60 分钟" value={draft.how_it_works} />
          </label>
          <label>
            它不是什么(买家最常见的误解写在这里)
            <textarea disabled={!canWrite} onChange={(e) => set("is_not", e.target.value)} placeholder="不是热水器,不加热;不能接自来水管加压" value={draft.is_not} />
          </label>
          <label>
            参数(一行一个,「键: 值」;尺寸写 dimensions_cm、重量写 weight_g)
            <textarea disabled={!canWrite} onChange={(e) => set("specsText", e.target.value)} placeholder={"battery_mah: 7800\nip_rating: IPX8\ndimensions_cm: 10x10x20\nweight_g: 650"} value={draft.specsText} />
          </label>
          <div className={styles.sheetRow}>
            <label>
              指示(灯 / 屏 / 声音各代表什么)
              <textarea disabled={!canWrite} onChange={(e) => set("indicators", e.target.value)} placeholder="红灯充电,绿灯充满,屏幕显示水温 °F" value={draft.indicators} />
            </label>
            <label>
              包装内含
              <textarea disabled={!canWrite} onChange={(e) => set("package", e.target.value)} placeholder="泵、软管、花洒、挂钩、USB-C 线、说明书" value={draft.package} />
            </label>
          </div>
          <div className={styles.sheetRow}>
            <label>
              人群与场景
              <textarea disabled={!canWrite} onChange={(e) => set("audience", e.target.value)} placeholder="露营、房车、宠物洗澡、冲沙、园艺" value={draft.audience} />
            </label>
            <label>
              已知误解(差评从哪来)
              <textarea disabled={!canWrite} onChange={(e) => set("misreadings", e.target.value)} placeholder="以为能加热;以为能接水龙头;泵头没入水抽不上来" value={draft.misreadings} />
            </label>
          </div>
          <div className={styles.sheetRow}>
            <label>
              出厂价(元)
              <input disabled={!canWrite} inputMode="decimal" onChange={(e) => set("factory_cny", e.target.value)} value={draft.factory_cny} />
            </label>
            <label>
              头程(元 / 件)
              <input disabled={!canWrite} inputMode="decimal" onChange={(e) => set("freight_cny", e.target.value)} value={draft.freight_cny} />
            </label>
            <label>
              售价(美元)
              <input disabled={!canWrite} inputMode="decimal" onChange={(e) => set("price_usd", e.target.value)} value={draft.price_usd} />
            </label>
            <label>
              对手 ASIN(逗号分开)
              <input disabled={!canWrite} onChange={(e) => set("competitor_asins", e.target.value)} placeholder="B0XXXXXXXX, B0YYYYYYYY" value={draft.competitor_asins} />
            </label>
          </div>
          <label>
            备注
            <textarea disabled={!canWrite} onChange={(e) => set("notes", e.target.value)} value={draft.notes} />
          </label>
          <div className={styles.sheetActions}>
            <button className={styles.button} disabled={!canWrite || busy} onClick={() => void save()} type="button">
              保存并判「够不够」
            </button>
            <button className={styles.linkButton} disabled={!canWrite || busy || !current} onClick={() => void judge()} type="button">
              让 DeepSeek 再核一遍(找矛盾、追问)
            </button>
            {status ? <span className={styles.muted}>{status}</span> : null}
          </div>

          {verdict?.code ? (
            <div className={styles.verdict} aria-label="够不够">
              {USE_ORDER.map((use) => {
                const item = verdict.code?.uses[use];
                if (!item) return null;
                return (
                  <div className={styles.verdictRow} key={use}>
                    <b className={item.ok ? styles.good : styles.warn}>
                      {item.ok ? "够" : "不够"} · {uses[use] ?? item.label}
                    </b>
                    <span className={styles.muted}>{item.ok ? "员工可以用这份表干这件事" : `缺:${item.missing.join("、")}`}</span>
                  </div>
                );
              })}
              {verdict.code.contradictions.length ? (
                <div>
                  <b className={styles.bad}>矛盾</b>
                  <ul className={styles.verdictList}>
                    {verdict.code.contradictions.map((c) => (
                      <li key={c}>{c}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {verdict.code.questions.length ? (
                <div>
                  <b>这个品类买家一定会问,表里还没说清</b>
                  <ul className={styles.verdictList}>
                    {verdict.code.questions.map((q) => (
                      <li key={q}>{q}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {verdict.model ? (
                <div>
                  <b>DeepSeek 补的</b>
                  <ul className={styles.verdictList}>
                    {verdict.model.contradictions.map((c) => (
                      <li key={`c-${c}`}>矛盾:{c}</li>
                    ))}
                    {verdict.model.questions.map((q) => (
                      <li key={`q-${q}`}>追问:{q}</li>
                    ))}
                    {USE_ORDER.flatMap((use) => (verdict.model?.missing_hints[use] ?? []).map((h) => <li key={`h-${use}-${h}`}>{uses[use] ?? use}还缺:{h}</li>))}
                  </ul>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
