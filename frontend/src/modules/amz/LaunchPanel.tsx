"use client";

import { useCallback, useEffect, useState } from "react";

import styles from "./AmzWorkspace.module.css";
import {
  advanceLaunch,
  closeLaunch,
  createLaunch,
  getLaunch,
  getLaunches,
  pasteReviews,
  saveLaunchInputs,
  tickLaunch,
  type AmzLaunch,
} from "./api";

const LINES: Record<string, string> = { pump: "沐浴泵", heater: "热水棒", flash: "太阳能手电", nail: "磨甲器", bundle: "套装", other: "其他" };
const STEPS = ["pnl", "battlefield", "listing", "prelaunch", "honeymoon", "verdict", "retro"];
const STEP_LABEL: Record<string, string> = { pnl: "0 损益", battlefield: "1 战场", listing: "2 listing", prelaunch: "3 上架前门", honeymoon: "4 蜜月", verdict: "5 第45天", retro: "6 复盘" };

type NumField = { key: string; label: string; hint?: string };
const PNL_FIELDS: NumField[] = [
  { key: "price_usd", label: "售价(美元)" },
  { key: "fba_fee_usd", label: "FBA 配送费(美元)", hint: "卖家后台收入计算器里看" },
  { key: "referral_pct", label: "佣金 %" },
  { key: "launch_tacos_pct", label: "推新广告 TACOS %" },
  { key: "promo_refund_pct", label: "促销与退款 %" },
  { key: "margin_floor_usd", label: "每件毛利底线(美元)" },
];
const PRELAUNCH_FIELDS: NumField[] = [
  { key: "fba_units", label: "FBA 入库件数" },
  { key: "expected_daily_units", label: "预计日销(件)" },
  { key: "launch_daily_budget_usd", label: "推新日预算上限(美元)" },
  { key: "launch_max_cpc_usd", label: "推新最高 CPC(美元)" },
];
const HONEYMOON_FIELDS: NumField[] = [
  { key: "reviews_count", label: "现在的评论数", hint: "亚马逊没有评论 API,手填" },
  { key: "main_term_rank", label: "主词自然排名", hint: "手搜一下" },
];

/**
 * 推新六步:推新只有一次,上架前把所有事做完,上架后只做三件事。
 * 每一步有门;门没过可以强制放行,但要写原因(进台账)。全部 L1:这一页不会碰亚马逊。
 */
export function LaunchPanel() {
  const [list, setList] = useState<AmzLaunch[]>([]);
  const [manualItems, setManualItems] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [launch, setLaunch] = useState<AmzLaunch | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [override, setOverride] = useState("");
  const [lessons, setLessons] = useState("");
  const [paste, setPaste] = useState({ whose: "competitor" as "ours" | "competitor", text: "", asin: "" });
  const [create, setCreate] = useState({ store_code: "03us", product_line: "bundle", title: "" });

  const loadList = useCallback(async () => {
    try {
      const payload = await getLaunches();
      setList(payload.items);
      setManualItems(payload.manual_items);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    }
  }, []);

  const loadOne = useCallback(async (id: string) => {
    try {
      const row = await getLaunch(id);
      setLaunch(row);
      setDraft(Object.fromEntries(Object.entries(row.inputs).map(([k, v]) => [k, v == null ? "" : String(v)])));
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  useEffect(() => {
    if (selected) void loadOne(selected);
  }, [selected, loadOne]);

  async function act(fn: () => Promise<AmzLaunch | unknown>, ok: string) {
    setBusy(true);
    try {
      const result = await fn();
      if (result && typeof result === "object" && "stage" in (result as AmzLaunch)) {
        const row = result as AmzLaunch;
        setLaunch(row);
        setDraft(Object.fromEntries(Object.entries(row.inputs).map(([k, v]) => [k, v == null ? "" : String(v)])));
      } else if (selected) {
        await loadOne(selected);
      }
      await loadList();
      setStatus(ok);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function numbers(fields: NumField[]) {
    const out: Record<string, unknown> = {};
    for (const f of fields) {
      const raw = (draft[f.key] ?? "").trim();
      if (raw !== "") out[f.key] = Number(raw);
    }
    return out;
  }

  function Fields({ fields }: { fields: NumField[] }) {
    return (
      <div className={styles.sheetRow}>
        {fields.map((f) => (
          <label key={f.key}>
            {f.label}
            <input inputMode="decimal" onChange={(e) => setDraft((prev) => ({ ...prev, [f.key]: e.target.value }))} placeholder={f.hint} value={draft[f.key] ?? ""} />
          </label>
        ))}
      </div>
    );
  }

  const stepIndex = launch ? STEPS.indexOf(launch.stage === "growth" || launch.stage === "killed" ? "retro" : launch.stage) : -1;

  return (
    <div className={styles.workspace}>
      {status ? <div className={styles.muted} style={{ padding: "6px 2px" }}>{status}</div> : null}
      <section className={styles.panel} aria-label="推新">
        <div className={styles.panelHead}>
          <h2>推新 · 六步</h2>
          <span className={styles.muted}>推新只有一次:上架前把事做完,上架后只做三件事 · 门没过可强制放行但要写原因</span>
        </div>
        <div className={styles.sheetLayout}>
          <div className={styles.sheetList}>
            {list.map((row) => (
              <button className={`${styles.sheetItem} ${selected === row.id ? styles.sheetItemOn : ""}`} key={row.id} onClick={() => setSelected(row.id)} type="button">
                <span>{row.title}</span>
                <small>
                  {row.store_code} · {row.product_line_label} · {row.stage_label}
                </small>
              </button>
            ))}
            {list.length === 0 ? <div className={styles.muted}>还没有推新。套装是第一次实跑。</div> : null}
            <div className={styles.sheetForm} style={{ marginTop: 10 }}>
              <b className={styles.muted}>开一个推新</b>
              <div className={styles.sheetRow}>
                <label>
                  店铺
                  <input onChange={(e) => setCreate({ ...create, store_code: e.target.value })} value={create.store_code} />
                </label>
                <label>
                  产品线
                  <select onChange={(e) => setCreate({ ...create, product_line: e.target.value })} value={create.product_line}>
                    {Object.entries(LINES).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <label>
                名字
                <input onChange={(e) => setCreate({ ...create, title: e.target.value })} placeholder="热水棒 + 淋浴泵 冬季套装" value={create.title} />
              </label>
              <button className={styles.linkButton} disabled={busy} onClick={() => void act(async () => { const row = await createLaunch(create); setSelected(row.id); return row; }, "建好了,先过损益表门。")} type="button">
                开始
              </button>
            </div>
          </div>

          <div className={styles.sheetForm}>
            {!launch ? (
              <div className={styles.muted}>左边选一个推新。</div>
            ) : (
              <>
                <div className={styles.verdict}>
                  <div className={styles.verdictRow}>
                    <b>{launch.title}</b>
                    <span className={styles.muted}>
                      {launch.store_code} · {launch.product_line_label} · {launch.sku ?? "SKU 未定"} · {launch.asin ?? "ASIN 未定"}
                      {launch.live_on ? ` · 上架 ${launch.live_on}` : ""}
                    </span>
                  </div>
                  <div className={styles.sheetActions}>
                    {STEPS.map((step, i) => (
                      <span className={i === stepIndex ? styles.good : i < stepIndex ? styles.muted : styles.muted} key={step} style={{ fontWeight: i === stepIndex ? 700 : 400 }}>
                        {i < stepIndex ? "✓ " : ""}
                        {STEP_LABEL[step]}
                      </span>
                    ))}
                  </div>
                </div>

                {/* 0 损益表门 */}
                <div className={styles.verdict}>
                  <div className={styles.verdictRow}>
                    <b className={launch.pnl.ok ? styles.good : styles.bad}>0 损益表门:{launch.pnl.ok ? "过" : "不过"}</b>
                    <span className={styles.muted}>
                      {launch.pnl.margin_usd != null ? `每件毛利 $${launch.pnl.margin_usd}(${launch.pnl.margin_pct}%)· 底线 $${launch.pnl.floor_usd}` : `缺:${(launch.pnl.missing ?? []).join("、")}`}
                      {launch.pnl.breakeven_price_usd ? ` · 过线售价 $${launch.pnl.breakeven_price_usd}` : ""}
                    </span>
                  </div>
                  {launch.pnl.lines ? (
                    <div className={styles.muted}>
                      {Object.entries(launch.pnl.lines).map(([k, v]) => `${k} ${v >= 0 ? "" : "−"}$${Math.abs(v)}`).join(" · ")}
                    </div>
                  ) : null}
                  <Fields fields={PNL_FIELDS} />
                  <div className={styles.muted}>出厂价和头程从事实表里取,不在这里填。</div>
                </div>

                {/* 1 战场 */}
                <div className={styles.verdict}>
                  <div className={styles.verdictRow}>
                    <b>1 看战场</b>
                    <span className={styles.muted}>对手差评贴进来,系统归簇找前三个坑,上架前堵进五点 1 和副图 2</span>
                  </div>
                  {(launch.battlefield.pits ?? []).length ? (
                    <ul className={styles.verdictList}>
                      {launch.battlefield.pits?.map((p) => (
                        <li key={p.theme}>
                          <b>{p.theme}</b> · {p.family_label} · {p.count} 条({p.share_pct}%)→ {p.owner}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <div className={styles.muted}>还没有对手差评。</div>
                  )}
                  <div className={styles.sheetRow}>
                    <label>
                      谁的评论
                      <select onChange={(e) => setPaste({ ...paste, whose: e.target.value as "ours" | "competitor" })} value={paste.whose}>
                        <option value="competitor">对手的</option>
                        <option value="ours">自家的</option>
                      </select>
                    </label>
                    <label>
                      ASIN(可空)
                      <input onChange={(e) => setPaste({ ...paste, asin: e.target.value })} value={paste.asin} />
                    </label>
                  </div>
                  <label>
                    评论原文(每条之间空一行,开头可以写「2星」)
                    <textarea onChange={(e) => setPaste({ ...paste, text: e.target.value })} rows={5} value={paste.text} />
                  </label>
                  <div className={styles.sheetActions}>
                    <button
                      className={styles.linkButton}
                      disabled={busy || !paste.text.trim()}
                      onClick={() =>
                        void act(async () => {
                          const res = await pasteReviews({ product_line: launch.product_line, whose: paste.whose, text: paste.text, asin: paste.asin || undefined, store_code: paste.whose === "ours" ? launch.store_code : undefined });
                          setPaste({ ...paste, text: "" });
                          return res;
                        }, "评论已入库归簇。")
                      }
                      type="button"
                    >
                      入库并归簇
                    </button>
                  </div>
                </div>

                {/* 3 上架前门 */}
                <div className={styles.verdict}>
                  <div className={styles.verdictRow}>
                    <b className={launch.checklist.all_green ? styles.good : styles.warn}>3 上架前门:{launch.checklist.all_green ? "全绿" : "没全绿"}</b>
                  </div>
                  <ul className={styles.verdictList}>
                    {(launch.checklist.items ?? []).map((item) => (
                      <li key={item.key}>
                        {item.auto ? (
                          <b className={item.ok ? styles.good : styles.bad}>{item.ok ? "✓" : "✗"}</b>
                        ) : (
                          <input checked={item.ok} disabled={busy} onChange={(e) => void act(() => tickLaunch(launch.id, item.key, e.target.checked), "已记。")} type="checkbox" />
                        )}{" "}
                        {item.label} <span className={styles.muted}>· {item.detail}</span>
                      </li>
                    ))}
                  </ul>
                  <Fields fields={PRELAUNCH_FIELDS} />
                  <div className={styles.muted}>{Object.keys(manualItems).length} 项需要人勾,其余自动判。</div>
                </div>

                {/* 4 蜜月 */}
                {launch.live_on ? (
                  <div className={styles.verdict}>
                    <div className={styles.verdictRow}>
                      <b>4 蜜月期 第 {String(launch.honeymoon.day ?? "—")} / 45 天</b>
                      <span className={styles.muted}>只做三件事:收词升精准 · 看四个数 · 守纪律(不砍价、不改 listing)</span>
                    </div>
                    <div className={styles.muted}>
                      转化率 {String(launch.honeymoon.cvr_pct ?? "—")}% · 件数 {String(launch.honeymoon.units ?? "—")} · 访问 {String(launch.honeymoon.sessions ?? "—")} · 主词点击份额 {String(launch.honeymoon.main_term_click_share_pct ?? "—")}%
                    </div>
                    <Fields fields={HONEYMOON_FIELDS} />
                    <label>
                      主词
                      <input onChange={(e) => setDraft((prev) => ({ ...prev, main_term: e.target.value }))} value={draft.main_term ?? ""} />
                    </label>
                  </div>
                ) : null}

                {/* 5 判定 + 6 复盘 */}
                {launch.verdict.result ? (
                  <div className={styles.verdict}>
                    <div className={styles.verdictRow}>
                      <b className={launch.verdict.result === "pass" ? styles.good : styles.bad}>5 第 45 天:{launch.verdict.result === "pass" ? "达标" : launch.verdict.result === "fail" ? "没达标" : "缺数"}</b>
                      <span className={styles.muted}>{launch.verdict.judged_on}</span>
                    </div>
                    <ul className={styles.verdictList}>
                      {(launch.verdict.missing ?? []).map((m) => (
                        <li key={m}>缺:{m}</li>
                      ))}
                      {(launch.verdict.breaks ?? []).map((b) => (
                        <li key={b.link}>
                          <b>{b.link}</b>:{b.why} → {b.fix}
                        </li>
                      ))}
                    </ul>
                    {launch.stage === "verdict" ? (
                      <>
                        <label>
                          复盘教训(一行一条,至少一条)
                          <textarea onChange={(e) => setLessons(e.target.value)} rows={3} value={lessons} />
                        </label>
                        <div className={styles.sheetActions}>
                          <button className={styles.button} disabled={busy} onClick={() => void act(() => closeLaunch(launch.id, "growth", lessons.split("\n").filter((l) => l.trim())), "进成长期,复盘已进经验库。")} type="button">
                            进成长期
                          </button>
                          <button className={styles.linkButton} disabled={busy} onClick={() => void act(() => closeLaunch(launch.id, "killed", lessons.split("\n").filter((l) => l.trim())), "已砍,复盘已进经验库。")} type="button">
                            砍掉
                          </button>
                        </div>
                      </>
                    ) : null}
                    {launch.retro.lessons ? <div className={styles.muted}>复盘:{launch.retro.lessons.join(";")}</div> : null}
                  </div>
                ) : null}

                <div className={styles.sheetActions}>
                  <button className={styles.linkButton} disabled={busy} onClick={() => void act(() => saveLaunchInputs(launch.id, { ...numbers([...PNL_FIELDS, ...PRELAUNCH_FIELDS, ...HONEYMOON_FIELDS]), main_term: draft.main_term || undefined }), "已保存并重算。")} type="button">
                    保存数字并重算
                  </button>
                  {["pnl", "battlefield", "listing", "prelaunch"].includes(launch.stage) ? (
                    <>
                      <button className={styles.button} disabled={busy} onClick={() => void act(() => advanceLaunch(launch.id), "往下走了一步。")} type="button">
                        下一步
                      </button>
                      <input onChange={(e) => setOverride(e.target.value)} placeholder="门没过要强制放行?写原因" value={override} />
                      <button className={styles.linkButton} disabled={busy || !override.trim()} onClick={() => void act(() => advanceLaunch(launch.id, override), "已强制放行,原因进台账。")} type="button">
                        强制放行
                      </button>
                    </>
                  ) : null}
                </div>
              </>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
