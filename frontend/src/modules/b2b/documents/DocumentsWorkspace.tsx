"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import styles from "./Documents.module.css";
import {
  type B2BDocument,
  type BankingState,
  createDocument,
  downloadDocument,
  getBanking,
  getDocuments,
  saveBanking,
} from "./api";
import { type WholesaleItem, getWholesaleItems } from "../wholesale/api";

/** 一行:选中的产品 + 数量。 */
type Line = { item_id: string; qty: string };

export default function DocumentsWorkspace() {
  const [banking, setBanking] = useState<BankingState | null>(null);
  const [bankDraft, setBankDraft] = useState<Record<string, string>>({});
  const [documents, setDocuments] = useState<B2BDocument[]>([]);
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
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [bank, docs, catalogue] = await Promise.all([
      getBanking(),
      getDocuments(),
      getWholesaleItems({ status: "ready" }),
    ]);
    setBanking(bank);
    setBankDraft(bank.profile);
    setDocuments(docs);
    setItems(catalogue.items ?? []);
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
          <ul className={styles.docList}>
            {documents.map((doc) => (
              <li className={styles.docRow} key={doc.id}>
                <strong className={styles.docNumber}>{doc.number}</strong>
                <span className={styles.docBuyer}>{doc.buyer_company}</span>
                <span className={styles.muted}>
                  {doc.item_count} 个品 · {doc.currency} {doc.total}
                </span>
                <span className={styles.muted}>有效至 {doc.valid_until}</span>
                <button
                  className={styles.ghostButton}
                  onClick={() =>
                    void downloadDocument(doc.id, doc.number).catch((caught) =>
                      setError(
                        caught instanceof Error ? caught.message : String(caught),
                      ),
                    )
                  }
                  type="button"
                >
                  下载 PDF
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
