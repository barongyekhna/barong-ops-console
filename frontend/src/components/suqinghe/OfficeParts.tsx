"use client";

import { useState, type FormEvent } from "react";

import styles from "./Office.module.css";
import {
  CANDIDATE_CARD_KIND,
  COPY_CARD_KIND,
  MARKET_CARD_KIND,
  PRICE_CARD_KIND,
  REVIEW_CARD_KIND,
  candidateCardView,
  copyCardView,
  marketCardView,
  pct,
  priceCardView,
  reviewCardView,
  usd,
} from "./card-view";
import { cardImageUrl, confidenceLabel, familyMeta, familyOf, groupCards, summaryOf, waitedText } from "./card-kinds";
import { CARD_STATUS_LABEL, GOAL_METRICS, VIA_LABEL, addGoal, controlOffice, decideCard, instructOffice, patchGoal, type OfficeCard, type OfficeGoal, type OfficeRead } from "./office-api";

/** 场景视图和列表视图共用的零件:审批卡、指挥控件、几个格式化小工具。 */

export type Runner = (label: string, action: () => Promise<unknown>) => Promise<boolean>;

// 彩蛋:连点她 5 下。纯前端、固定台词,不调 AI。口吻是女强人 + 温柔大姐姐,不撒娇不暧昧。
export const EASTER_LINES = [
  "今天的活我扛着，你去喝口水。",
  "别急，先把最要紧的一件做完，剩下的交给我。",
  "数据我盯着呢，有事我第一时间说。",
  "你定方向，细活我来跑。",
  "今天也辛苦了，早点休息，明天见。",
  "卡片我都排好序了，你挑最上面那张就行。",
];

export function pickEasterLine(): string {
  return EASTER_LINES[Math.floor(Math.random() * EASTER_LINES.length)];
}

export function minutesAgo(seconds: number | null): string {
  if (seconds == null) return "从没上过线";
  if (seconds < 60) return "刚刚";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} 分钟没动静`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours} 小时没动静` : `${Math.round(hours / 24)} 天没动静`;
}

export function timeText(iso: string | null): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("zh-CN", { hour: "2-digit", minute: "2-digit", month: "numeric", day: "numeric" });
  } catch {
    return iso;
  }
}

export function dossierIdOf(card: OfficeCard): number | null {
  if (card.kind !== "create_k_dossier") return null;
  const evidence = card.evidence as { dossier_id?: unknown } | null;
  const id = Number(evidence?.dossier_id);
  return Number.isFinite(id) && id > 0 ? id : null;
}

/* ---------------------------------------------------------------- 卡(10-27 重做):纸片 → 卷宗
 * 收件筐按家族分组,每张卡是一张米白纸片(家族色条 + 戳记 + 缩略图 + 一行基本信息 + 批/驳);
 * 点纸片铺成一页卷宗:她的结论、为什么、这张卡的正文(价目表/评分表/全文/拆解…)、不做会怎样、能不能撤回、原始证据。
 */

function DecideBar({ card, canCommand, busy, run, onDecided }: { card: OfficeCard; canCommand: boolean; busy: boolean; run: Runner; onDecided?: () => void }) {
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const meta = familyMeta(card.kind);
  if (card.status !== "pending") return null;
  return (
    <div className={styles.sheetActions} onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()} role="presentation">
      {canCommand ? (
        rejecting ? (
          <form
            className={styles.rejectForm}
            onSubmit={(event: FormEvent) => {
              event.preventDefault();
              if (!reason.trim()) return;
              void run("驳回失败", () => decideCard(card.ref, "reject", reason.trim())).then((ok) => {
                if (ok) {
                  setRejecting(false);
                  setReason("");
                  onDecided?.();
                }
              });
            }}
          >
            <textarea
              aria-label="驳回原因"
              onChange={(event) => setReason(event.target.value)}
              placeholder="驳回原因（必填，她会记住）"
              rows={2}
              value={reason}
            />
            <div className={styles.inlineActions}>
              <button disabled={busy || !reason.trim()} type="submit">
                确认驳回
              </button>
              <button onClick={() => setRejecting(false)} type="button">
                取消
              </button>
            </div>
          </form>
        ) : (
          <div className={styles.inlineActions}>
            <button
              className={styles.primary}
              disabled={busy}
              onClick={() => void run("批准失败", () => decideCard(card.ref, "approve")).then((ok) => ok && onDecided?.())}
              type="button"
            >
              {meta.needsDecision ? "批" : "知道了"}
            </button>
            <button disabled={busy} onClick={() => setRejecting(true)} type="button">
              驳
            </button>
          </div>
        )
      ) : null}
    </div>
  );
}

function CardThumb({ card, large }: { card: OfficeCard; large?: boolean }) {
  const [failed, setFailed] = useState(false);
  const meta = familyMeta(card.kind);
  return (
    <div className={large ? styles.dossierThumb : styles.sheetThumb} data-family={meta.family}>
      {failed ? (
        <span aria-hidden="true">{meta.icon}</span>
      ) : (
        <img alt="" loading="lazy" onError={() => setFailed(true)} src={cardImageUrl(card.ref)} />
      )}
    </div>
  );
}

/** 紧凑的一张纸片:谁、什么卡、关键数字,能批能驳;点正文打开卷宗。 */
export function CardSheet({
  card,
  canCommand,
  busy,
  run,
  onOpen,
}: {
  card: OfficeCard;
  canCommand: boolean;
  busy: boolean;
  run: Runner;
  onOpen: () => void;
}) {
  const meta = familyMeta(card.kind);
  const summary = summaryOf(card);
  const pending = card.status === "pending";
  return (
    <article className={styles.sheet} data-family={meta.family} data-status={card.status}>
      <button className={styles.sheetOpen} onClick={onOpen} type="button">
        <CardThumb card={card} />
        <div className={styles.sheetMain}>
          <div className={styles.sheetTitleRow}>
            <span className={styles.stamp} data-family={meta.family}>
              {meta.icon} {meta.label}
            </span>
            <strong className={styles.sheetTitle}>{summary.headline}</strong>
            <span className={styles.cardRef}>#{card.ref}</span>
          </div>
          {summary.facts.length > 0 ? <p className={styles.sheetFacts}>{summary.facts.join(" · ")}</p> : null}
          <p className={styles.sheetMeta}>
            {pending ? (
              <>
                <span>{confidenceLabel(card.confidence)}</span>
                <span>{waitedText(card.created_at)}</span>
                <span className={styles.muted}>{meta.ask}</span>
              </>
            ) : (
              <>
                <span className={styles.tag} data-status={card.status}>
                  {CARD_STATUS_LABEL[card.status] ?? card.status}
                  {card.decided_via ? ` · ${VIA_LABEL[card.decided_via] ?? card.decided_via}` : ""}
                </span>
                {card.decision_reason ? <span>原因:{card.decision_reason}</span> : null}
                <span>{timeText(card.decided_at)}</span>
              </>
            )}
          </p>
        </div>
      </button>
      <DecideBar busy={busy} canCommand={canCommand} card={card} run={run} />
    </article>
  );
}

/** 卷宗:这张卡的全部——她的结论、为什么、正文、不做会怎样、能不能撤回、原始证据,页底能批能驳。 */
export function CardDossier({
  card,
  canCommand,
  busy,
  run,
  onBack,
  onOpenDossier,
}: {
  card: OfficeCard;
  canCommand: boolean;
  busy: boolean;
  run: Runner;
  onBack: () => void;
  onOpenDossier?: (id: number) => void;
}) {
  const meta = familyMeta(card.kind);
  const summary = summaryOf(card);
  const dossierId = dossierIdOf(card);
  const [showRaw, setShowRaw] = useState(false);
  return (
    <div className={styles.dossierPage} data-family={meta.family}>
      <button className={styles.linkButton} onClick={onBack} type="button">
        ← 回收件筐
      </button>
      <header className={styles.dossierHead}>
        <CardThumb card={card} large />
        <div>
          <span className={styles.stamp} data-family={meta.family}>
            {meta.icon} {meta.label}卡 · #{card.ref}
          </span>
          <h3>{summary.headline}</h3>
          <p className={styles.sheetFacts}>{summary.facts.join(" · ")}</p>
          <p className={styles.sheetMeta}>
            <span>{confidenceLabel(card.confidence)}</span>
            <span>{card.status === "pending" ? waitedText(card.created_at) : `${CARD_STATUS_LABEL[card.status] ?? card.status} ${timeText(card.decided_at)}`}</span>
            <span>{card.reversible ? "能撤回" : "不能撤回"}</span>
          </p>
        </div>
      </header>
      <section className={styles.dossierSection}>
        <h4>她的结论</h4>
        <p>{card.conclusion}</p>
      </section>
      {card.why ? (
        <section className={styles.dossierSection}>
          <h4>为什么</h4>
          <dl className={styles.cardDetail}>
            <dt>她的理由</dt>
            <dd className={styles.preLine}>{card.why}</dd>
          </dl>
        </section>
      ) : null}
      <section className={styles.dossierSection}>
        <h4>这张卡的正文</h4>
        {card.kind === CANDIDATE_CARD_KIND ? <CandidateCardBody card={card} /> : null}
        {card.kind === PRICE_CARD_KIND ? <PriceCardBody evidence={card.evidence} /> : null}
        {card.kind === REVIEW_CARD_KIND ? <ReviewCardBody evidence={card.evidence} /> : null}
        {card.kind === COPY_CARD_KIND ? <CopyCardBody evidence={card.evidence} /> : null}
        {card.kind === MARKET_CARD_KIND ? <MarketCardBody evidence={card.evidence} /> : null}
        {familyOf(card.kind) === "dossier" || familyOf(card.kind) === "alert" ? <p className={styles.muted}>{meta.ask}</p> : null}
      </section>
      {card.if_not ? (
        <section className={styles.dossierSection}>
          <h4>不做会怎样</h4>
          <p>{card.if_not}</p>
        </section>
      ) : null}
      {card.decision_reason ? (
        <section className={styles.dossierSection}>
          <h4>你当时说的</h4>
          <p>{card.decision_reason}</p>
        </section>
      ) : null}
      {dossierId !== null && onOpenDossier ? (
        <button className={styles.linkButton} onClick={() => onOpenDossier(dossierId)} type="button">
          看档案 →
        </button>
      ) : null}
      <DecideBar busy={busy} canCommand={canCommand} card={card} onDecided={onBack} run={run} />
      <button className={styles.linkButton} onClick={() => setShowRaw((value) => !value)} type="button">
        {showRaw ? "收起原始证据" : "原始证据"}
      </button>
      {showRaw ? <pre className={styles.rawEvidence}>{JSON.stringify(card.evidence, null, 2)}</pre> : null}
    </div>
  );
}

/** 收件筐:按家族分组的纸片 + 最近定下的;点开一张就在这块面板里铺成卷宗。 */
export function Inbox({
  office,
  canCommand,
  busy,
  run,
  onOpenDossier,
}: {
  office: OfficeRead;
  canCommand: boolean;
  busy: boolean;
  run: Runner;
  onOpenDossier?: (id: number) => void;
}) {
  const [focusRef, setFocusRef] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const focused = focusRef ? [...office.pending_cards, ...office.recent_cards].find((card) => card.ref === focusRef) ?? null : null;
  if (focused) {
    return <CardDossier busy={busy} canCommand={canCommand} card={focused} onBack={() => setFocusRef(null)} onOpenDossier={onOpenDossier} run={run} />;
  }
  const groups = groupCards(office.pending_cards);
  return (
    <div className={styles.inbox}>
      {groups.length === 0 ? <p className={styles.muted}>收件筐是空的，暂时没有要批的。</p> : null}
      {groups.map(({ meta, cards }) => (
        <section className={styles.inboxGroup} data-family={meta.family} key={meta.family}>
          <button className={styles.groupTab} onClick={() => setCollapsed((value) => ({ ...value, [meta.family]: !value[meta.family] }))} type="button">
            <span>
              {meta.icon} {meta.label}
            </span>
            <span className={styles.groupCount}>{cards.length}</span>
            <small>{meta.needsDecision ? "要你批" : "只看,不用批"}</small>
            <span className={styles.caret}>{collapsed[meta.family] ? "▸" : "▾"}</span>
          </button>
          {collapsed[meta.family]
            ? null
            : cards.map((card) => <CardSheet busy={busy} canCommand={canCommand} card={card} key={card.ref} onOpen={() => setFocusRef(card.ref)} run={run} />)}
        </section>
      ))}
      {!canCommand && office.pending_cards.length > 0 ? <p className={styles.muted}>只有老板能批这些卡。</p> : null}
      {office.recent_cards.length > 0 ? (
        <section className={styles.inboxGroup} data-family="done">
          <div className={styles.groupTab} data-static="true">
            <span>🗂️ 最近定下的</span>
            <span className={styles.groupCount}>{office.recent_cards.length}</span>
          </div>
          {office.recent_cards.map((card) => (
            <CardSheet busy={busy} canCommand={false} card={card} key={card.ref} onOpen={() => setFocusRef(card.ref)} run={run} />
          ))}
        </section>
      ) : null}
    </div>
  );
}

/** 旧入口(场景里的收件筐面板还在逐张调它):一张纸片,点开在原地铺开卷宗。 */
export function CardItem({
  card,
  canCommand,
  busy,
  run,
  onOpenDossier,
}: {
  card: OfficeCard;
  canCommand: boolean;
  busy: boolean;
  run: Runner;
  onOpenDossier?: (id: number) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  if (expanded) {
    return <CardDossier busy={busy} canCommand={canCommand} card={card} onBack={() => setExpanded(false)} onOpenDossier={onOpenDossier} run={run} />;
  }
  return <CardSheet busy={busy} canCommand={canCommand} card={card} onOpen={() => setExpanded(true)} run={run} />;
}

/** 选品卡:图 + 进价/起订/月销 + 美国同类价 + 风险,批之前一眼看得到;原页去 1688 看。 */
function CandidateCardBody({ card }: { card: OfficeCard }) {
  const view = candidateCardView(card.evidence);
  if (!view) return null;
  return (
    <div className={styles.cardBody}>
      <div className={styles.candidateRow}>
        <div>
          <strong className={styles.preLine}>{view.titleZh}</strong>
          {view.category ? <small className={styles.muted}>{view.category}</small> : null}
          <ul className={styles.bulletList}>
            <li>
              进价 {view.priceCny === null ? "—" : `¥${view.priceCny}`}
              {view.goodsUsd !== null ? `(≈${usd(view.goodsUsd)})` : ""},起订 {view.moq ?? "—"},月销 {view.monthlySales ?? "—"}
            </li>
            <li>{view.competitors}</li>
            {view.reason ? <li>{view.reason}</li> : null}
          </ul>
        </div>
      </div>
      {view.score ? (
        <table className={styles.scoreTable}>
          <thead>
            <tr>
              <th>维度</th>
              <th>分</th>
              <th>依据</th>
            </tr>
          </thead>
          <tbody>
            {view.score.dims.map((dim) => (
              <tr key={dim.key} className={dim.missing ? styles.scoreMissing : undefined}>
                <td>{dim.label}</td>
                <td>
                  {dim.pts}/{dim.max}
                </td>
                <td>{dim.why}</td>
              </tr>
            ))}
            <tr>
              <td>合计</td>
              <td>
                {view.score.total}/{view.score.max}
              </td>
              <td>
                {view.score.weightClass ? `按${view.score.weightClass}估运费;` : ""}
                {view.score.amazon};{view.score.keepa}
                {view.score.missing.length > 0 ? `;没拿到:${view.score.missing.join("、")}` : ""}
              </td>
            </tr>
          </tbody>
        </table>
      ) : null}
      {view.risks.length > 0 ? (
        <ul className={styles.questionList}>
          {view.risks.map((risk) => (
            <li key={risk}>风险:{risk}</li>
          ))}
        </ul>
      ) : null}
      {view.sourceUrl ? (
        <a className={styles.linkButton} href={view.sourceUrl} rel="noopener noreferrer" target="_blank">
          去 1688 看原页 →
        </a>
      ) : null}
    </div>
  );
}

/** 价格卡:一行一个规格的价目表 + 要老板定的事。不藏在「展开」里,批之前一眼看得到。 */
function PriceCardBody({ evidence }: { evidence: unknown }) {
  const view = priceCardView(evidence);
  if (!view) return null;
  return (
    <div className={styles.cardBody}>
      <table className={styles.priceTable}>
        <thead>
          <tr>
            <th>规格</th>
            <th>进价</th>
            <th>货</th>
            <th>运费</th>
            <th>到手成本</th>
            <th>建议售价</th>
            <th>毛利</th>
          </tr>
        </thead>
        <tbody>
          {view.rows.map((row) => (
            <tr data-include={row.include ? "yes" : "no"} key={`${row.name}-${row.nameZh}`}>
              <td>
                {row.name}
                {row.nameZh && row.nameZh !== row.name ? <small>{row.nameZh}</small> : null}
                {row.note ? <small className={styles.rowNote}>{row.note}</small> : null}
              </td>
              <td>{row.costCny === null ? "—" : `¥${row.costCny}`}</td>
              <td>{usd(row.goodsUsd)}</td>
              <td>
                {usd(row.shipUsd)}
                {row.kg !== null ? <small>按 {row.kg} 公斤</small> : null}
              </td>
              <td>{usd(row.landedUsd)}</td>
              <td>{row.include ? usd(row.priceUsd) : "不卖"}</td>
              <td>{row.include ? `${usd(row.profitUsd)}(${pct(row.margin)})` : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {view.shippingRule ? <p className={styles.muted}>{view.shippingRule}</p> : null}
      {view.summary ? <p className={styles.muted}>{view.summary}</p> : null}
      <p className={styles.muted}>
        {view.competitors}
        {view.shippingClass ? `;运费模板 ${view.shippingClass}${view.battery ? "(含电池)" : ""}` : ""}
      </p>
      {view.questions.length > 0 ? (
        <ul className={styles.questionList}>
          {view.questions.map((question) => (
            <li key={question}>要你定:{question}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** 审核卡:英文标题和卖点、要保存的每张图(缩略图)、品牌审查、合规要看的、没用的说法。 */
function ReviewCardBody({ evidence }: { evidence: unknown }) {
  const view = reviewCardView(evidence);
  if (!view) return null;
  return (
    <div className={styles.cardBody}>
      {view.h1 ? <strong className={styles.reviewTitle}>{view.h1}</strong> : null}
      {view.headline ? <p className={styles.muted}>{view.headline}</p> : null}
      {view.bullets.length > 0 ? (
        <ul className={styles.bulletList}>
          {view.bullets.map((bullet) => (
            <li key={bullet}>{bullet}</li>
          ))}
        </ul>
      ) : null}
      {view.images.length > 0 ? (
        <div className={styles.thumbGrid}>
          {view.images.map((image) => (
            <figure key={image.assetId}>
              <a href={image.thumb.replace(/\/thumbnail$/, "/file")} rel="noreferrer" target="_blank">
                <img alt={`第 ${image.position} 张`} loading="lazy" src={image.thumb} />
              </a>
              <figcaption>
                {image.position} · {image.role}
              </figcaption>
            </figure>
          ))}
        </div>
      ) : null}
      <p className={view.auditClean ? styles.muted : styles.warnLine}>{view.auditClean ? "品牌审查:干净" : "品牌审查要你看:"}</p>
      {view.auditFindings.length > 0 ? (
        <ul className={styles.questionList}>
          {view.auditFindings.map((finding) => (
            <li key={finding}>{finding}</li>
          ))}
        </ul>
      ) : null}
      {view.concerns.length > 0 ? (
        <ul className={styles.questionList}>
          {view.concerns.map((concern) => (
            <li key={concern}>合规:{concern}</li>
          ))}
        </ul>
      ) : null}
      {view.held.length > 0 ? <p className={styles.muted}>没写进卖点的认证说法(有证书再放):{view.held.join(";")}</p> : null}
      {view.hype.length > 0 ? <p className={styles.muted}>卖家的宣传语我没用:{view.hype.join("、")}</p> : null}
      {view.flagged.length > 0 ? <p className={styles.muted}>档案里还没定的:{view.flagged.join("、")}</p> : null}
      {view.prices.length > 0 ? <p className={styles.muted}>价格:{view.prices.join("、")}</p> : null}
    </div>
  );
}

/** 文案卡(10-27):全文摆出来——标题、钩子、短描述、卖点、段落、收尾、FAQ、SEO;前面是她的中文摘要和改了什么、拿不准什么。 */
function CopyCardBody({ evidence }: { evidence: unknown }) {
  const view = copyCardView(evidence);
  if (!view) return null;
  return (
    <div className={styles.cardBody}>
      {view.summaryZh ? <p className={styles.preLine}>{view.summaryZh}</p> : null}
      {view.notes.length > 0 ? (
        <ul className={styles.bulletList}>
          {view.notes.map((note) => (
            <li key={note}>我改了:{note}</li>
          ))}
        </ul>
      ) : null}
      {view.adjusted.length > 0 ? (
        <ul className={styles.bulletList}>
          {view.adjusted.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : null}
      {view.unsure.length > 0 ? (
        <ul className={styles.questionList}>
          {view.unsure.map((item) => (
            <li key={item}>要你定:{item}</li>
          ))}
        </ul>
      ) : null}
      {view.historyUnclear ? <p className={styles.warnLine}>你上次说的这部分我对不上:{view.historyUnclear}</p> : null}
      <div className={styles.copyPage} lang="en">
        {view.h1 ? <strong className={styles.reviewTitle}>{view.h1}</strong> : null}
        {view.headline ? <p className={styles.copyHeadline}>{view.headline}</p> : null}
        {view.subheadline ? <p className={styles.muted}>{view.subheadline}</p> : null}
        {view.shortDescription ? <p>{view.shortDescription}</p> : null}
        {view.bullets.length > 0 ? (
          <ul className={styles.bulletList}>
            {view.bullets.map((bullet) => (
              <li key={bullet}>{bullet}</li>
            ))}
          </ul>
        ) : null}
        {view.sections.map((section, index) => (
          <section key={`${index}-${section.heading}`}>
            {section.heading ? <h4>{section.heading}</h4> : null}
            {section.body ? <p>{section.body}</p> : null}
          </section>
        ))}
        {view.conversion ? <p>{view.conversion}</p> : null}
        {view.faq.length > 0 ? (
          <dl className={styles.copyFaq}>
            {view.faq.map((item) => (
              <div key={item.question}>
                <dt>{item.question}</dt>
                <dd>{item.answer}</dd>
              </div>
            ))}
          </dl>
        ) : null}
        {view.seoTitle || view.metaDescription || view.urlSlug ? (
          <p className={styles.muted}>
            SEO:{view.seoTitle}
            {view.metaDescription ? ` · ${view.metaDescription}` : ""}
            {view.urlSlug ? ` · /${view.urlSlug}` : ""}
          </p>
        ) : null}
      </div>
      {view.held.length > 0 ? <p className={styles.muted}>没写进卖点的认证说法(有证书再放):{view.held.join(";")}</p> : null}
      {view.hype.length > 0 ? <p className={styles.muted}>卖家的宣传语我没用:{view.hype.join("、")}</p> : null}
      {view.flagged.length > 0 ? <p className={styles.muted}>档案里还没定的:{view.flagged.join("、")}</p> : null}
      {view.missingInputs.length > 0 ? <p className={styles.muted}>K 没依据所以没写的:{view.missingInputs.join(";")}</p> : null}
      {view.briefPaused ? <p className={styles.muted}>作图指令按你的安排先不动,文案批了她停在这等。</p> : null}
    </div>
  );
}

/** 竞品拆解卡(10-27):读了哪几家、买家最在乎什么、我们有无、四簇关键词、缺的事实。给老板看,不用批。 */
function MarketCardBody({ evidence }: { evidence: unknown }) {
  const view = marketCardView(evidence);
  if (!view) return null;
  return (
    <div className={styles.cardBody}>
      {view.note ? <p className={styles.preLine}>{view.note}</p> : null}
      {view.priorities.length > 0 ? (
        <ol className={styles.bulletList}>
          {view.priorities.map((p) => (
            <li key={p.what}>
              <strong>{p.what}</strong>
              {p.why ? ` — ${p.why}` : ""}
            </li>
          ))}
        </ol>
      ) : null}
      {view.has.length > 0 ? <p className={styles.muted}>我们有、可以讲:{view.has.join("、")}</p> : null}
      {view.missing.length > 0 ? <p className={styles.warnLine}>买家在乎但我们档案里没有:{view.missing.join("、")}</p> : null}
      {view.gaps.length > 0 ? (
        <ul className={styles.questionList}>
          {view.gaps.map((gap) => (
            <li key={gap}>要你或工厂补:{gap}</li>
          ))}
        </ul>
      ) : null}
      {view.pages.length > 0 ? (
        <table className={styles.scoreTable}>
          <thead>
            <tr>
              <th>店</th>
              <th>价</th>
              <th>卖点/问答/图</th>
              <th>他们主打</th>
            </tr>
          </thead>
          <tbody>
            {view.pages.map((p) => (
              <tr key={p.domain} className={p.ok ? undefined : styles.scoreMissing}>
                <td>{p.domain}</td>
                <td>{p.price === null ? "—" : usd(p.price)}</td>
                <td>{p.ok ? `${p.bullets}/${p.faq}/${p.images ?? "?"}` : p.error || "没读到"}</td>
                <td lang="en">{p.highlight}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {view.keywords.map((cluster) => (
        <p key={cluster.label} className={styles.muted}>
          {cluster.label}:<span lang="en">{cluster.items.join(" · ")}</span>
        </p>
      ))}
      {view.competitors.length > 0 ? <p className={styles.muted}>竞品:{view.competitors.join("、")}</p> : null}
      {view.priceBand ? <p className={styles.muted}>同类价格带 {view.priceBand}(搜「{view.query}」)</p> : null}
    </div>
  );
}

export function PauseButton({ office, busy, run }: { office: OfficeRead; busy: boolean; run: Runner }) {
  return (
    <button
      disabled={busy}
      onClick={() => void run(office.paused ? "恢复失败" : "暂停失败", () => controlOffice(office.paused ? "resume" : "pause"))}
      type="button"
    >
      {office.paused ? "让她接着干" : "先停一停"}
    </button>
  );
}

export function InstructForm({ busy, run }: { busy: boolean; run: Runner }) {
  const [instruction, setInstruction] = useState("");
  return (
    <form
      className={styles.row}
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        const text = instruction.trim();
        if (!text) return;
        void run("交代失败", () => instructOffice(text)).then((ok) => ok && setInstruction(""));
      }}
    >
      <input aria-label="交代一句" onChange={(event) => setInstruction(event.target.value)} placeholder="交代一句…" value={instruction} />
      <button disabled={busy || !instruction.trim()} type="submit">
        交代
      </button>
    </form>
  );
}

export function GoalForm({ busy, run }: { busy: boolean; run: Runner }) {
  const [goalText, setGoalText] = useState("");
  const [metric, setMetric] = useState("");
  const [target, setTarget] = useState("");
  return (
    <form
      className={styles.row}
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        const text = goalText.trim();
        if (text.length < 2) return;
        const numericTarget = target.trim() ? Number(target) : undefined;
        void run("加目标失败", () =>
          addGoal(text, metric.trim() || undefined, Number.isFinite(numericTarget) ? numericTarget : undefined),
        ).then((ok) => {
          if (ok) {
            setGoalText("");
            setMetric("");
            setTarget("");
          }
        });
      }}
    >
      <input aria-label="新目标" onChange={(event) => setGoalText(event.target.value)} placeholder="新目标，如：店里做到 30 个品" value={goalText} />
      <select aria-label="跟踪哪个数（可选）" className={styles.narrow} onChange={(event) => setMetric(event.target.value)} value={metric}>
        {GOAL_METRICS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <input aria-label="目标值（可选）" className={styles.narrow} inputMode="decimal" onChange={(event) => setTarget(event.target.value)} placeholder="数值" value={target} />
      <button disabled={busy || goalText.trim().length < 2} type="submit">
        加目标
      </button>
    </form>
  );
}

export function OwnerControls({ office, busy, run }: { office: OfficeRead; busy: boolean; run: Runner }) {
  return (
    <section className={`${styles.section} ${styles.owner}`}>
      <div className={styles.inlineActions}>
        <PauseButton busy={busy} office={office} run={run} />
      </div>
      <InstructForm busy={busy} run={run} />
      <GoalForm busy={busy} run={run} />
    </section>
  );
}

export function GoalList({ goals, canCommand, busy, run }: { goals: OfficeGoal[]; canCommand: boolean; busy: boolean; run: Runner }) {
  return (
    <>
      {goals.length === 0 ? <p className={styles.muted}>还没有目标。</p> : null}
      <ul className={styles.list}>
        {goals.map((goal) => (
          <li key={goal.id}>
            <span>
              {goal.text}
              {goal.status === "paused" ? <em className={styles.tag}>暂停</em> : null}
            </span>
            {canCommand ? (
              <span className={styles.inlineActions}>
                <button
                  disabled={busy}
                  onClick={() => void run("调整目标失败", () => patchGoal(goal.id, { status: goal.status === "paused" ? "active" : "paused" }))}
                  type="button"
                >
                  {goal.status === "paused" ? "恢复" : "暂停"}
                </button>
                <button disabled={busy} onClick={() => void run("调整目标失败", () => patchGoal(goal.id, { status: "done" }))} type="button">
                  完成
                </button>
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </>
  );
}
