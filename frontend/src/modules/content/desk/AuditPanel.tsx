"use client";

import styles from "./ContentDesk.module.css";
import type { BrandAudit } from "./types";

/**
 * 品牌 / 接地审查。四族发现，三族可以人工放行，**一族永远不行**。
 *
 * `bad_derivations`（算错的数）不给放行按钮，理由在 UI 上直说：它不是误报族。
 * 校验器**真的把算式算过一遍**，落进来意味着声明的算式和写出的数字对不上。
 * 放行它 = 主动把一个算错的数字发到面向美国买家的页面上。
 *
 * 已放行的条目**不隐藏**，半透明保留 + 显示「已放行 N 条」——放行清单跨重写
 * 结转且不自动清理，藏起来就等于让人忘了自己放过什么。
 */
export type IgnorePayload =
  | { kind: "brand"; surface: string; term: string }
  | { kind: "cjk"; surface: string }
  | { kind: "number"; surface: string; number: string };

// 指纹只在前端用于「这条放行了没有」的判断；**真正的指纹由后端算**
// （前端传原始 finding 字段，避免客户端伪造任意指纹）。
function fp(payload: IgnorePayload): string {
  const norm = (value: string) =>
    String(value ?? "").trim().toLowerCase().split(/\s+/).join(" ");
  if (payload.kind === "brand") {
    return `brand::${norm(payload.surface)}::${norm(payload.term)}`;
  }
  if (payload.kind === "cjk") return `cjk::${norm(payload.surface)}`;
  return `number::${norm(payload.surface)}::${norm(payload.number)}`;
}

export function AuditPanel({
  audit,
  busy,
  onToggleIgnore,
}: {
  audit: BrandAudit;
  busy: boolean;
  onToggleIgnore: (payload: IgnorePayload, ignored: boolean) => void;
}) {
  const ignored = new Set(audit.ignored_findings ?? []);
  const rows: { payload: IgnorePayload; text: string; surface: string }[] = [
    ...audit.brand_violations.map((v) => ({
      payload: { kind: "brand", surface: v.surface, term: v.term } as IgnorePayload,
      surface: v.surface,
      text: `出现了第三方品牌词「${v.term}」${v.evidence ? `：…${v.evidence}…` : ""}`,
    })),
    ...audit.cjk_surfaces.map((surface) => ({
      payload: { kind: "cjk", surface } as IgnorePayload,
      surface,
      text: "这里有中文——面向美国买家的页面上不该出现",
    })),
    ...audit.ungrounded_numbers.map((n) => ({
      payload: { kind: "number", surface: n.surface, number: n.number } as IgnorePayload,
      surface: n.surface,
      text: `数字「${n.number}」在我们的事实库里找不到出处`,
    })),
  ];

  if (!audit.audited) {
    return (
      <div className={styles.panel}>
        <div className={styles.panelLabel}>品牌 / 接地审查</div>
        <p className={styles.panelText}>
          这篇没有审查记录。**没有记录不等于通过**——它会被发布门禁拦住。
          按批评重写一次就会重新审。
        </p>
      </div>
    );
  }

  const ignoredCount = ignored.size;
  const nothing = rows.length === 0 && audit.bad_derivations.length === 0;

  return (
    <div className={styles.panel}>
      <div className={styles.panelLabel}>
        品牌 / 接地审查
        {ignoredCount > 0 ? ` · 已放行 ${ignoredCount} 条` : ""}
      </div>

      {nothing ? (
        <p className={styles.panelText}>没有发现问题。</p>
      ) : null}

      {rows.map((row) => {
        const isIgnored = ignored.has(fp(row.payload));
        return (
          <div
            className={`${styles.finding}${isIgnored ? ` ${styles.findingIgnored}` : ""}`}
            key={fp(row.payload)}
          >
            <span className={styles.surface}>{row.surface}</span>
            <span className={styles.findingMain}>
              {row.text}
              {isIgnored ? " · 已放行" : ""}
            </span>
            <button
              className={`${styles.btn} ${styles.btnQuiet} ${styles.btnTiny}`}
              disabled={busy}
              onClick={() => onToggleIgnore(row.payload, !isIgnored)}
              type="button"
            >
              {isIgnored ? "撤销放行" : "误报，放行"}
            </button>
          </div>
        );
      })}

      {audit.bad_derivations.length ? (
        <>
          <div className={styles.blockLabel}>算错的数字</div>
          {audit.bad_derivations.map((row, index) => (
            <div className={styles.finding} key={`${index}-${row.value}`}>
              <span className={styles.surface}>{row.from}</span>
              <span className={styles.findingMain}>
                文章里写的是「{row.value}」，但 {row.reason}
              </span>
            </div>
          ))}
          {/* 刻意没有放行按钮。这不是误报族——校验器真的算过一遍。 */}
          <p className={styles.panelText} style={{ marginTop: 8 }}>
            算错的数不能放行——改数或者重写。这一族不是误报：校验器真的把算式
            算过一遍，对不上才报的。
          </p>
        </>
      ) : null}
    </div>
  );
}
