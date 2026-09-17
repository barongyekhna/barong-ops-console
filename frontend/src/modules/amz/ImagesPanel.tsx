"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import styles from "./AmzWorkspace.module.css";
import {
  createImageBrief,
  decideImageAsset,
  getImageBrief,
  getImageBriefs,
  imageAssetUrl,
  markImageBriefLive,
  uploadImageReference,
  uploadImageSubmission,
  type AmzImageAsset,
  type AmzImageBrief,
  type AmzImageBriefDetail,
} from "./api";

const STATUS_LABEL: Record<string, string> = { queued: "排队中", in_review: "审图中", approved: "已选定", live: "已上线", closed: "已关闭" };
const VERDICT_LABEL: Record<string, string> = { passed: "四道门全过", failed: "有门没过", unknown: "看图模型没接通" };

/**
 * 图片通道:殷熊的 brief 队列。brief 带证据和事实,参考图由人上传(实拍 / 现在的主图 / 兄弟店主图 / 对手缩略图),
 * 画由 Codex 桌面版画(深链唤起),交稿走四道门,人选定后手动传亚马逊,再回来点「已上线」,14 / 28 天自动回看。
 * 图片线永远 L1:这一页没有任何「传到亚马逊」的按钮。
 */
export function ImagesPanel({ briefId, suggestionId }: { briefId: string | null; suggestionId: string | null }) {
  const [briefs, setBriefs] = useState<AmzImageBrief[]>([]);
  const [kinds, setKinds] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<string | null>(briefId);
  const [detail, setDetail] = useState<AmzImageBriefDetail | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [refKind, setRefKind] = useState("competitor_thumb");
  const [refNote, setRefNote] = useState("");
  const [subNote, setSubNote] = useState("");
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [manual, setManual] = useState({ store_code: "01us", position: "main", sku: "", reason: "" });

  const loadList = useCallback(async () => {
    try {
      const payload = await getImageBriefs();
      setBriefs(payload.items);
      setKinds(payload.reference_kinds);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    }
  }, []);

  const loadDetail = useCallback(async (id: string) => {
    try {
      setDetail(await getImageBrief(id));
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  useEffect(() => {
    if (selected) void loadDetail(selected);
    else setDetail(null);
  }, [selected, loadDetail]);

  // 从员工浮窗带着 suggestion 过来:直接建 brief(事实表不够会被拒,原因显示出来)。
  useEffect(() => {
    if (!suggestionId) return;
    let cancelled = false;
    (async () => {
      setBusy(true);
      try {
        const brief = await createImageBrief({ suggestion_id: suggestionId });
        if (cancelled) return;
        await loadList();
        setSelected(brief.id);
        setStatus("brief 已建好。上传参考图,然后唤起 Codex。");
      } catch (err) {
        if (!cancelled) setStatus(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setBusy(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [suggestionId, loadList]);

  const brief = detail?.brief ?? null;
  const chosen = useMemo(() => detail?.submissions.find((s) => s.id === brief?.chosen_asset_id) ?? null, [detail, brief]);

  async function run<T>(fn: () => Promise<T>, ok: string) {
    setBusy(true);
    try {
      await fn();
      if (selected) await loadDetail(selected);
      await loadList();
      setStatus(ok);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function invokeCodex() {
    if (!detail) return;
    const prompt = detail.codex_prompt;
    let copied = false;
    try {
      await navigator.clipboard.writeText(prompt);
      copied = true;
    } catch {
      copied = false;
    }
    window.location.href = `codex://new?prompt=${encodeURIComponent(prompt)}`;
    setStatus(copied ? "已唤起 Codex,指令也在剪贴板;没弹出就打开 Codex 粘贴。" : "已尝试唤起 Codex;没弹出就打开 Codex 手动粘贴指令。");
  }

  function onRefFile(file: File | null) {
    if (!file || !selected) return;
    void run(() => uploadImageReference(selected, file, refKind, refNote), "参考图已上传。");
    setRefNote("");
  }

  function onSubFile(file: File | null) {
    if (!file || !selected) return;
    void run(() => uploadImageSubmission(selected, file, subNote), "交稿已过四道门,看下面的结果。");
    setSubNote("");
  }

  return (
    <div className={styles.workspace}>
      {status ? <div className={styles.muted} style={{ padding: "6px 2px" }}>{status}</div> : null}
      <section className={styles.panel} aria-label="图片 brief">
        <div className={styles.panelHead}>
          <h2>图片 brief</h2>
          <span className={styles.muted}>殷熊只写 brief、只审图;画由 Codex 画,传由人传 · 每个位置最多 4 轮</span>
        </div>
        <div className={styles.sheetLayout}>
          <div className={styles.sheetList}>
            {briefs.map((b) => (
              <button className={`${styles.sheetItem} ${selected === b.id ? styles.sheetItemOn : ""}`} key={b.id} onClick={() => setSelected(b.id)} type="button">
                <span>{b.title}</span>
                <small>
                  {STATUS_LABEL[b.status] ?? b.status} · {b.rounds}/{b.max_rounds} 轮{b.live_at ? ` · 上线 ${b.live_at.slice(0, 10)}` : ""}
                </small>
              </button>
            ))}
            {briefs.length === 0 ? <div className={styles.muted}>还没有 brief。从总览里殷熊的「同屏输了」建议点「写 brief」,或在下面手动建一份。</div> : null}
            <div className={styles.sheetForm} style={{ marginTop: 10 }}>
              <b className={styles.muted}>手动建一份</b>
              <div className={styles.sheetRow}>
                <label>
                  店铺
                  <input onChange={(e) => setManual({ ...manual, store_code: e.target.value })} value={manual.store_code} />
                </label>
                <label>
                  位置
                  <select onChange={(e) => setManual({ ...manual, position: e.target.value })} value={manual.position}>
                    {["main", "angle", "benefit", "detail", "scale", "lifestyle", "package", "aplus"].map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <label>
                SKU(可空,取该店该线销量最高的)
                <input onChange={(e) => setManual({ ...manual, sku: e.target.value })} value={manual.sku} />
              </label>
              <label>
                为什么要改这张图
                <input onChange={(e) => setManual({ ...manual, reason: e.target.value })} placeholder="例如:老板看了觉得主图太暗" value={manual.reason} />
              </label>
              <button
                className={styles.linkButton}
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    const b = await createImageBrief({ store_code: manual.store_code, position: manual.position, sku: manual.sku || undefined, reason: manual.reason || undefined });
                    setSelected(b.id);
                  }, "brief 已建好。")
                }
                type="button"
              >
                建 brief
              </button>
            </div>
          </div>

          <div className={styles.sheetForm}>
            {!brief ? (
              <div className={styles.muted}>左边选一份 brief。</div>
            ) : (
              <>
                <div className={styles.verdict}>
                  <div className={styles.verdictRow}>
                    <b>{brief.title}</b>
                    <span className={styles.muted}>
                      {STATUS_LABEL[brief.status] ?? brief.status} · {brief.rounds}/{brief.max_rounds} 轮 · {brief.sku ?? "—"} · {brief.asin ?? "—"}
                    </span>
                  </div>
                  <div className={styles.sheetActions}>
                    <button className={styles.button} disabled={busy || brief.status === "live"} onClick={() => void invokeCodex()} type="button">
                      唤起 Codex 作图
                    </button>
                    {brief.status === "approved" ? (
                      <button className={styles.linkButton} disabled={busy} onClick={() => void run(() => markImageBriefLive(brief.id), "已记上线日,14 / 28 天后自动回看。")} type="button">
                        我已经传到亚马逊了 → 标记上线
                      </button>
                    ) : null}
                  </div>
                  <details>
                    <summary className={styles.muted}>完整 brief(Codex 会自己从 MCP 拉这一份)</summary>
                    <pre style={{ whiteSpace: "pre-wrap", fontSize: 12.5, lineHeight: 1.5 }}>{brief.brief_md}</pre>
                  </details>
                </div>

                <div className={styles.verdict}>
                  <div className={styles.verdictRow}>
                    <b>参考图</b>
                    <span className={styles.muted}>实拍图给形;兄弟店主图是差异化门的对照;对手缩略图是同屏门的对照</span>
                  </div>
                  <div className={styles.sheetRow}>
                    <label>
                      类型
                      <select onChange={(e) => setRefKind(e.target.value)} value={refKind}>
                        {Object.entries(kinds).map(([k, v]) => (
                          <option key={k} value={k}>
                            {v}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      备注(哪家店 / 哪个对手)
                      <input onChange={(e) => setRefNote(e.target.value)} value={refNote} />
                    </label>
                    <label>
                      选图
                      <input accept="image/*" disabled={busy || brief.status === "live"} onChange={(e) => onRefFile(e.target.files?.[0] ?? null)} type="file" />
                    </label>
                  </div>
                  <div className={styles.crew}>
                    {detail?.references.map((r) => (
                      <figure className={styles.emp} key={r.id} style={{ display: "block" }}>
                        <img alt={r.kind_label} src={imageAssetUrl(r.id, "thumbnail")} style={{ width: "100%", borderRadius: 8 }} />
                        <figcaption className={styles.muted}>
                          {r.kind_label}
                          {r.note ? ` · ${r.note}` : ""}
                        </figcaption>
                      </figure>
                    ))}
                  </div>
                </div>

                <div className={styles.verdict}>
                  <div className={styles.verdictRow}>
                    <b>交稿与四道门</b>
                    <span className={styles.muted}>Codex 经 MCP 交的和你手上传的走同一条路</span>
                  </div>
                  <div className={styles.sheetRow}>
                    <label>
                      备注
                      <input onChange={(e) => setSubNote(e.target.value)} value={subNote} />
                    </label>
                    <label>
                      手动交一张
                      <input accept="image/*" disabled={busy || brief.status === "live" || brief.rounds >= brief.max_rounds} onChange={(e) => onSubFile(e.target.files?.[0] ?? null)} type="file" />
                    </label>
                  </div>
                  {detail?.submissions.length === 0 ? <div className={styles.muted}>还没有交稿。</div> : null}
                  {detail?.submissions.map((s) => (
                    <SubmissionCard
                      busy={busy}
                      chosen={chosen?.id === s.id}
                      key={s.id}
                      onDecide={(decision) => void run(() => decideImageAsset(s.id, decision, reasons[s.id]), decision === "choose" ? "已选定。传到亚马逊后回来点「标记上线」。" : "已驳回。")}
                      reason={reasons[s.id] ?? ""}
                      setReason={(v) => setReasons((prev) => ({ ...prev, [s.id]: v }))}
                      sub={s}
                    />
                  ))}
                </div>

                {Object.keys(brief.lookback).length ? (
                  <div className={styles.verdict}>
                    <div className={styles.verdictRow}>
                      <b>上线后回看</b>
                    </div>
                    <pre style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>{JSON.stringify(brief.lookback, null, 1)}</pre>
                  </div>
                ) : null}
              </>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}

function SubmissionCard({ sub, chosen, busy, reason, setReason, onDecide }: { sub: AmzImageAsset; chosen: boolean; busy: boolean; reason: string; setReason: (v: string) => void; onDecide: (d: "choose" | "reject") => void }) {
  const verdict = sub.review.verdict ?? "unknown";
  return (
    <div className={styles.verdict} style={{ gridTemplateColumns: "160px 1fr", display: "grid", gap: 12 }}>
      <a href={imageAssetUrl(sub.id, "original")} rel="noreferrer" target="_blank">
        <img alt={`第 ${sub.round} 轮`} src={imageAssetUrl(sub.id, "thumbnail")} style={{ width: "100%", borderRadius: 8 }} />
      </a>
      <div className={styles.sheetForm}>
        <div className={styles.verdictRow}>
          <b className={verdict === "passed" ? styles.good : verdict === "failed" ? styles.bad : styles.warn}>
            第 {sub.round} 轮 · {VERDICT_LABEL[verdict] ?? verdict}
          </b>
          <span className={styles.muted}>
            {sub.width}×{sub.height} · {sub.submitted_via === "mcp" ? "Codex 交的" : "手上传"} · {sub.status === "chosen" ? "已选定" : sub.status === "rejected" ? "已驳回" : "候选"}
            {chosen ? " ✓" : ""}
          </span>
        </div>
        <ul className={styles.verdictList}>
          {(sub.review.gates ?? []).map((g) => (
            <li key={g.name}>
              <b className={g.passed === true ? styles.good : g.passed === false ? styles.bad : styles.warn}>{g.name}:{g.passed === true ? "过" : g.passed === false ? "不过" : g.skipped ? "跳过" : "未知"}</b>
              {g.skipped ? ` · ${g.skipped}` : ""}
              {g.stands_out ? ` · ${g.stands_out}` : ""}
              {g.click_rank ? ` · 这一排里第 ${g.click_rank} 个被点` : ""}
              {(g.problems ?? []).length ? ` · ${g.problems?.join(";")}` : ""}
            </li>
          ))}
        </ul>
        {(sub.review.fix ?? []).length ? (
          <div className={styles.muted}>只改这些:{sub.review.fix?.join(" / ")}</div>
        ) : null}
        {sub.review.human?.reason ? <div className={styles.muted}>驳回原因:{sub.review.human.reason}</div> : null}
        {sub.status === "staged" ? (
          <div className={styles.sheetActions}>
            <button className={styles.button} disabled={busy} onClick={() => onDecide("choose")} type="button">
              选这张
            </button>
            <input onChange={(e) => setReason(e.target.value)} placeholder="驳回原因(必填)" value={reason} />
            <button className={styles.linkButton} disabled={busy} onClick={() => onDecide("reject")} type="button">
              驳回
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
