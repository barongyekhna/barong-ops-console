"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import styles from "./Documents.module.css";
import {
  type B2BDocument,
  type BankingState,
  type SampleCredit,
  STAGES,
  addSampleCredit,
  createDocument,
  createShippingDoc,
  downloadDocument,
  getBanking,
  getDocuments,
  getSampleCredits,
  saveBanking,
  setDocumentStage,
} from "./api";
import { type WholesaleItem, getWholesaleItems } from "../wholesale/api";

/** 一行:选中的产品 + 数量。 */
type Line = { item_id: string; qty: string };

export default function DocumentsWorkspace() {
  const [banking, setBanking] = useState<BankingState | null>(null);
  const [bankDraft, setBankDraft] = useState<Record<string, string>>({});
  const [documents, setDocuments] = useState<B2BDocument[]>([]);
  const [credits, setCredits] = useState<SampleCredit[]>([]);
  const [creditDraft, setCreditDraft] = useState({ buyer_email: "", amount: "", note: "" });
  const [items, setItems] = useState<WholesaleItem[]>([]);
  const [buyer, setBuyer] = useState({
    buyer_company: "",
    buyer_contact: "",
    buyer_email: "",
    buyer_address: "",
    ship_to: "",
    freight: "",
    notes: "",
  });
  const [lines, setLines] = useState<Line[]>([]);
  const [busy, setBusy] = useState(false);
  // 默认只看未完成的：你真正要盯的是那几单，已完成的不该占地方。
  const [onlyOpen, setOnlyOpen] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [bank, docs, catalogue, sampleCredits] = await Promise.all([
      getBanking(),
      getDocuments(),
      getWholesaleItems({ status: "ready" }),
      getSampleCredits(),
    ]);
    setBanking(bank);
    setBankDraft(bank.profile);
    setDocuments(docs);
    setItems(catalogue.items ?? []);
    setCredits(sampleCredits);
  }, []);

  useEffect(() => {
    void load().catch((caught) =>
      setError(caught instanceof Error ? caught.message : String(caught)),
    );
  }, [load]);

  const withBusy = async (run: () => Promise<string>) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      setNotice(await run());
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  // 一单三张纸（PI + 商业发票 + 装箱单）。**平铺列表到第四单就是 12 行乱序**，
  // 得靠单号日期自己拼哪三张是一单的。CI/PL 里存了来自哪张 PI，用它归堆。
  const { orders, orphans } = useMemo(() => {
    const byPi = new Map<
      string,
      { pi: B2BDocument; papers: B2BDocument[] }
    >();
    for (const doc of documents) {
      if (doc.doc_type === "proforma_invoice") {
        const existing = byPi.get(doc.id);
        byPi.set(doc.id, { pi: doc, papers: existing?.papers ?? [] });
      }
    }
    const orphans: B2BDocument[] = [];
    for (const doc of documents) {
      if (doc.doc_type === "proforma_invoice") continue;
      const bucket = byPi.get(doc.source_document_id ?? "");
      if (bucket) {
        bucket.papers.push(doc);
      } else {
        // 源单被删了的 CI/PL。**不能静默丢掉**——那是已经发给买家、
        // 报过关的凭证，从界面上消失比留着难看得多。
        orphans.push(doc);
      }
    }
    const grouped = [...byPi.values()];
    grouped.forEach((order) =>
      order.papers.sort((a, b) => a.number.localeCompare(b.number)),
    );
    const visible = onlyOpen
      ? grouped.filter((order) => order.pi.stage !== "closed")
      : grouped;
    return { orders: visible, orphans };
  }, [documents, onlyOpen]);

  const closedCount = useMemo(
    () =>
      documents.filter(
        (doc) => doc.doc_type === "proforma_invoice" && doc.stage === "closed",
      ).length,
    [documents],
  );

  const download = (doc: B2BDocument) =>
    downloadDocument(doc.id, doc.number).catch((caught) =>
      setError(caught instanceof Error ? caught.message : String(caught)),
    );

  const total = useMemo(() => {
    return lines.reduce((sum, line) => {
      const item = items.find((candidate) => candidate.id === line.item_id);
      const price = Number(item?.wholesale_price ?? "");
      const qty = Number(line.qty);
      if (!Number.isFinite(price) || !Number.isFinite(qty)) return sum;
      return sum + price * qty;
    }, 0);
  }, [lines, items]);

  const blocked = banking?.missing_required.length ?? 0;

  return (
    <div className={styles.workspace}>
      {error ? <p className={styles.error}>{error}</p> : null}
      {notice ? <p className={styles.notice}>{notice}</p> : null}

      {/* ── 收款信息：买家照着这几行去银行汇款，所以没填全不许开单 ── */}
      <section className={styles.panel}>
        <header className={styles.panelHead}>
          <h2>收款信息</h2>
        </header>
        <p className={styles.hint}>
          填一次，以后每张形式发票都自动带上。
          <strong>买家就是照着这几行去银行汇款的</strong>
          ，所以没填全就开不了单——一张没有收款信息的发票是废纸。
        </p>
        {blocked ? (
          <p className={styles.warn}>
            还差：{banking?.missing_required.join("、")}
          </p>
        ) : (
          <p className={styles.ok}>已填全，可以开单。</p>
        )}
        <div className={styles.bankGrid}>
          {(banking?.fields ?? []).map((field) => (
            <label className={styles.field} key={field.key}>
              <span>
                {field.label}
                {field.required ? <em className={styles.req}>*</em> : null}
              </span>
              <input
                className={styles.input}
                onChange={(event) =>
                  setBankDraft((current) => ({
                    ...current,
                    [field.key]: event.target.value,
                  }))
                }
                value={bankDraft[field.key] ?? ""}
              />
            </label>
          ))}
        </div>
        <button
          className={styles.primaryButton}
          disabled={busy}
          onClick={() =>
            void withBusy(async () => {
              await saveBanking(bankDraft);
              return "收款信息已保存。";
            })
          }
          type="button"
        >
          保存收款信息
        </button>
      </section>

      {/* ── 样品费台账：我们已经在四处承诺"全额抵扣首单"，靠脑子记到第三个
             客户就开始虚。记一笔，开单时自动扣。 ── */}
      <section className={styles.panel}>
        <header className={styles.panelHead}>
          <h2>样品费台账</h2>
        </header>
        <p className={styles.hint}>
          我们在产品页小窗、批发页、图册、开发信<strong>四个地方</strong>都写了
          「样品费全额抵扣首单」。谁付过样品费记在这里，
          <strong>开形式发票时按邮箱自动扣掉</strong>，你不用记。
        </p>
        <div className={styles.buyerGrid}>
          {(
            [
              ["buyer_email", "买家邮箱 *（按完整邮箱认人）"],
              ["amount", "样品费金额 *"],
              ["note", "备注（买了什么样品）"],
            ] as const
          ).map(([key, label]) => (
            <label className={styles.field} key={key}>
              <span>{label}</span>
              <input
                className={styles.input}
                onChange={(event) =>
                  setCreditDraft((current) => ({
                    ...current,
                    [key]: event.target.value,
                  }))
                }
                value={creditDraft[key]}
              />
            </label>
          ))}
        </div>
        <button
          className={styles.primaryButton}
          disabled={
            busy ||
            !creditDraft.buyer_email.trim() ||
            !(Number(creditDraft.amount) > 0)
          }
          onClick={() =>
            void withBusy(async () => {
              await addSampleCredit({
                buyer_email: creditDraft.buyer_email.trim(),
                amount: Number(creditDraft.amount),
                note: creditDraft.note.trim() || null,
              });
              setCreditDraft({ buyer_email: "", amount: "", note: "" });
              return "已记一笔样品费，开单时自动抵扣。";
            })
          }
          type="button"
        >
          记一笔样品费
        </button>
        {credits.length ? (
          <ul className={styles.docList}>
            {credits.map((credit) => (
              <li className={styles.docRow} key={credit.id}>
                <span className={styles.docBuyer}>{credit.buyer_email}</span>
                <span className={styles.muted}>
                  {credit.currency} {credit.amount} · {credit.paid_on}
                </span>
                <span className={styles.muted}>
                  {credit.consumed ? "已抵扣" : "待抵扣"}
                </span>
                {credit.note ? (
                  <span className={styles.muted}>{credit.note}</span>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className={styles.empty}>还没记过样品费。</p>
        )}
      </section>

      {/* ── 开一张形式发票 ── */}
      <section className={styles.panel}>
        <header className={styles.panelHead}>
          <h2>开形式发票（PI）</h2>
        </header>
        <p className={styles.hint}>
          客户说「我要了」之后，把这张发给他，他拿着去银行汇定金。
          单号会印在上面，让他汇款时写在附言里，你才对得上账。
        </p>
        <div className={styles.buyerGrid}>
          {(
            [
              ["buyer_company", "买方公司名 *"],
              ["buyer_contact", "联系人"],
              ["buyer_email", "邮箱"],
              ["buyer_address", "公司地址"],
              ["ship_to", "送货地址（和公司地址不同才填）"],
              ["freight", "运费（留空 = 单独另报）"],
            ] as const
          ).map(([key, label]) => (
            <label className={styles.field} key={key}>
              <span>{label}</span>
              <input
                className={styles.input}
                onChange={(event) =>
                  setBuyer((current) => ({ ...current, [key]: event.target.value }))
                }
                value={buyer[key]}
              />
            </label>
          ))}
        </div>

        <div className={styles.linesHead}>
          <strong>买什么</strong>
          <button
            className={styles.ghostButton}
            disabled={!items.length}
            onClick={() =>
              setLines((current) => [
                ...current,
                { item_id: items[0]?.id ?? "", qty: "" },
              ])
            }
            type="button"
          >
            + 添加一行
          </button>
        </div>
        {!items.length ? (
          <p className={styles.warn}>
            批发目录里还没有「可出图册」的产品——先把批发价、箱规、起订量、交期填全。
          </p>
        ) : null}
        <ul className={styles.lineList}>
          {lines.map((line, index) => (
            <li className={styles.lineRow} key={index}>
              <select
                className={styles.select}
                onChange={(event) =>
                  setLines((current) =>
                    current.map((row, cursor) =>
                      cursor === index
                        ? { ...row, item_id: event.target.value }
                        : row,
                    ),
                  )
                }
                value={line.item_id}
              >
                {items.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.sku} — {item.product_name}
                  </option>
                ))}
              </select>
              <input
                className={styles.qtyInput}
                inputMode="numeric"
                onChange={(event) =>
                  setLines((current) =>
                    current.map((row, cursor) =>
                      cursor === index ? { ...row, qty: event.target.value } : row,
                    ),
                  )
                }
                placeholder="数量"
                value={line.qty}
              />
              <button
                className={styles.ghostButton}
                onClick={() =>
                  setLines((current) =>
                    current.filter((_, cursor) => cursor !== index),
                  )
                }
                type="button"
              >
                删除
              </button>
            </li>
          ))}
        </ul>
        {lines.length ? (
          <p className={styles.hint}>
            货款小计约 <strong>USD {total.toFixed(2)}</strong>
            （最终以发票为准；数量够了会自动用更低的阶梯价）
          </p>
        ) : null}
        <button
          className={styles.primaryButton}
          disabled={busy || !!blocked || !lines.length || !buyer.buyer_company.trim()}
          onClick={() =>
            void withBusy(async () => {
              const doc = await createDocument({
                buyer_company: buyer.buyer_company.trim(),
                buyer_contact: buyer.buyer_contact.trim() || null,
                buyer_email: buyer.buyer_email.trim() || null,
                buyer_address: buyer.buyer_address.trim() || null,
                ship_to: buyer.ship_to.trim() || null,
                freight: buyer.freight.trim() ? Number(buyer.freight) : null,
                notes: buyer.notes.trim() || null,
                lines: lines
                  .filter((line) => line.item_id && Number(line.qty) > 0)
                  .map((line) => ({
                    item_id: line.item_id,
                    qty: Number(line.qty),
                  })),
              });
              setLines([]);
              return `已开出 ${doc.number}，在下面下载。`;
            })
          }
          type="button"
        >
          生成形式发票
        </button>
      </section>

      {/* ── 已开的单据 ── */}
      <section className={styles.panel}>
        <header className={styles.panelHead}>
          <h2>已开单据</h2>
        </header>
        {!documents.length ? (
          <p className={styles.empty}>还没有开过单。</p>
        ) : (
          <>
            <label className={styles.filterLine}>
              <input
                checked={onlyOpen}
                onChange={(event) => setOnlyOpen(event.target.checked)}
                type="checkbox"
              />
              <span>
                只看未完成的
                {closedCount ? `（已完成的 ${closedCount} 单收起来了）` : ""}
              </span>
            </label>
            {!orders.length ? (
              <p className={styles.empty}>没有未完成的单了。</p>
            ) : null}
            <ul className={styles.orderList}>
              {orders.map((order) => (
                <li className={styles.order} key={order.pi.id}>
                  <div className={styles.orderHead}>
                    <strong className={styles.docNumber}>{order.pi.number}</strong>
                    <span className={styles.docBuyer}>{order.pi.buyer_company}</span>
                    <span className={styles.muted}>
                      {order.pi.item_count} 个品 · {order.pi.currency}{" "}
                      {order.pi.total}
                      {order.pi.sample_credit
                        ? `（已抵样品费 ${order.pi.sample_credit}）`
                        : ""}
                    </span>
                    <select
                      className={styles.select}
                      onChange={(event) =>
                        void withBusy(async () => {
                          await setDocumentStage(order.pi.id, event.target.value);
                          return `${order.pi.number} → ${
                            STAGES.find((s) => s.key === event.target.value)
                              ?.label ?? ""
                          }`;
                        })
                      }
                      value={order.pi.stage}
                    >
                      {STAGES.map((stage) => (
                        <option key={stage.key} value={stage.key}>
                          {stage.label}
                        </option>
                      ))}
                    </select>
                    <span className={styles.muted}>
                      有效至 {order.pi.valid_until}
                    </span>
                  </div>

                  {/* 这一单的三张纸收在一起 —— 平铺列表到第四单就是 12 行乱序 */}
                  <ul className={styles.paperList}>
                    <li className={styles.paperRow}>
                      <span className={styles.docType}>形式发票 PI</span>
                      <span className={styles.paperNumber}>{order.pi.number}</span>
                      <button
                        className={styles.ghostButton}
                        onClick={() => void download(order.pi)}
                        type="button"
                      >
                        下载
                      </button>
                    </li>
                    {order.papers.map((paper) => (
                      <li className={styles.paperRow} key={paper.id}>
                        <span className={styles.docType}>
                          {paper.doc_type_label}
                        </span>
                        <span className={styles.paperNumber}>{paper.number}</span>
                        <button
                          className={styles.ghostButton}
                          onClick={() => void download(paper)}
                          type="button"
                        >
                          下载
                        </button>
                      </li>
                    ))}
                  </ul>

                  <div className={styles.orderActions}>
                    {(
                      [
                        ["commercial_invoice", "出商业发票", "发货报关用。行项目原样继承这张 PI，金额必须和买家实付一致。"],
                        ["packing_list", "出装箱单", "箱数按箱规自动算；毛净重打包时才知道，留空会印 TBC。"],
                      ] as const
                    ).map(([kind, label, tip]) => {
                      const already = order.papers.some(
                        (paper) => paper.doc_type === kind,
                      );
                      return (
                        <button
                          className={styles.ghostButton}
                          disabled={busy}
                          key={kind}
                          onClick={() =>
                            void withBusy(async () => {
                              const made = await createShippingDoc(order.pi.id, {
                                doc_type: kind,
                              });
                              return `已出 ${made.number}`;
                            })
                          }
                          title={tip}
                          type="button"
                        >
                          {/* 已经出过就说「再出一张」——重开是正常操作（改了箱重、
                              换了银行），但要让人知道已经有一张了 */}
                          {already ? `再出一张${label.slice(1)}` : label}
                        </button>
                      );
                    })}
                  </div>
                </li>
              ))}
            </ul>
            {orphans.length ? (
              <div className={styles.orphanBox}>
                <p className={styles.warn}>
                  下面这些单据的形式发票已经不在了（被删过），但它们可能已经发给
                  买家、报过关，所以留在这里。
                </p>
                <ul className={styles.paperList}>
                  {orphans.map((paper) => (
                    <li className={styles.paperRow} key={paper.id}>
                      <span className={styles.docType}>
                        {paper.doc_type_label}
                      </span>
                      <span className={styles.paperNumber}>{paper.number}</span>
                      <span className={styles.muted}>
                        {paper.buyer_company}
                      </span>
                      <button
                        className={styles.ghostButton}
                        onClick={() => void download(paper)}
                        type="button"
                      >
                        下载
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </>
        )}
      </section>
    </div>
  );
}
