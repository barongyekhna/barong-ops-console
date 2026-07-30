"use client";

import { useCallback, useEffect, useState } from "react";

import styles from "./Outreach.module.css";
import {
  type EmailDraft,
  type EmailTemplate,
  backfillEmails,
  generateDrafts,
  getDrafts,
  getTemplates,
  patchDraft,
  patchTemplate,
  seedTemplates,
} from "./api";

export function OutreachWorkspace() {
  const [drafts, setDrafts] = useState<EmailDraft[]>([]);
  const [templates, setTemplates] = useState<EmailTemplate[]>([]);
  const [openTemplate, setOpenTemplate] = useState<string | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [draftList, templateList] = await Promise.all([
        getDrafts("draft"),
        getTemplates(),
      ]);
      setDrafts(draftList);
      setTemplates(templateList);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const withBusy = async (fn: () => Promise<string>) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      setNotice(await fn());
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const doSeed = () =>
    withBusy(async () => {
      const result = await seedTemplates();
      return `已灌入 ${result.added} 条内置模板。`;
    });

  const doBackfill = () =>
    withBusy(async () => {
      const result = await backfillEmails({ limit: 25, only_fit: true });
      return result.message;
    });

  const doGenerate = () =>
    withBusy(async () => {
      const result = await generateDrafts({ kind: "first_touch", limit: 25 });
      return (
        result.message ||
        `生成 ${result.created} 封草稿，跳过 ${result.skipped} 家。`
      );
    });

  const doCopy = async (draft: EmailDraft) => {
    const text = `${draft.subject}\n\n${draft.body}`;
    try {
      await navigator.clipboard.writeText(text);
      setNotice(`已复制「${draft.store_name}」那封，去 Zoho 粘贴发送。`);
    } catch {
      setError("复制失败，手动选中复制吧。");
    }
  };

  const doMark = (draft: EmailDraft, status: "sent" | "skipped") =>
    withBusy(async () => {
      await patchDraft(draft.id, { status });
      return status === "sent"
        ? `已标记发出：${draft.store_name}`
        : `已跳过：${draft.store_name}`;
    });

  const doSaveTemplate = (template: EmailTemplate) =>
    withBusy(async () => {
      const body = edits[template.id];
      if (body === undefined) throw new Error("没有改动。");
      await patchTemplate(template.id, { body });
      return `已保存模板：${template.kind_label}`;
    });

  return (
    <div className={styles.workspace}>
      <section className={styles.explainer}>
        <h2>发信怎么运转</h2>
        <p>
          <strong>系统永远不会替你发信。</strong>它只把信写好放这儿，你过目、
          改、复制，去 Zoho 亲手发。验证期前 30 封的目的是
          <strong>测出哪句话有人回</strong>——没跑出有效模板之前，批量发只是
          批量浪费。
        </p>
        <p className={styles.gate}>
          ⚠ 首封信<strong>绝不带附件</strong>（带附件直接进垃圾箱），图册只在
          「要价格表」那封回复里发。模板里<strong>绝不许出现信用卡/PayPal</strong>
          ，保存时会被拦下。
        </p>
        <div className={styles.toolbar}>
          <button
            className={styles.ghostButton}
            disabled={busy}
            onClick={() => void doBackfill()}
            type="button"
          >
            1. 抓官网补邮箱（免费）
          </button>
          <button
            className={styles.primaryButton}
            disabled={busy}
            onClick={() => void doGenerate()}
            type="button"
          >
            2. 生成首封草稿
          </button>
          {templates.length === 0 ? (
            <button
              className={styles.ghostButton}
              disabled={busy}
              onClick={() => void doSeed()}
              type="button"
            >
              先灌入内置模板
            </button>
          ) : null}
        </div>
      </section>

      {error ? <p className={styles.error}>{error}</p> : null}
      {notice ? <p className={styles.notice}>{notice}</p> : null}

      <section className={styles.panel}>
        <h3>草稿箱（{drafts.length}）</h3>
        {loading ? (
          <p className={styles.empty}>加载中…</p>
        ) : !drafts.length ? (
          <p className={styles.empty}>
            还没有草稿。需要客户「已通过审核」并且「有邮箱」——先在候选客户里
            点通过，再点上面的补邮箱和生成草稿。
          </p>
        ) : (
          <ul className={styles.draftList}>
            {drafts.map((draft) => (
              <li className={styles.draft} key={draft.id}>
                <div className={styles.draftHead}>
                  <strong>{draft.store_name}</strong>
                  <span className={styles.muted}>{draft.to_email}</span>
                </div>
                <div className={styles.subject}>{draft.subject}</div>
                <pre className={styles.body}>{draft.body}</pre>
                <div className={styles.draftActions}>
                  <button
                    className={styles.primaryButton}
                    onClick={() => void doCopy(draft)}
                    type="button"
                  >
                    复制全文
                  </button>
                  <button
                    className={styles.ghostButton}
                    disabled={busy}
                    onClick={() => void doMark(draft, "sent")}
                    type="button"
                  >
                    已发出
                  </button>
                  <button
                    className={styles.ghostButton}
                    disabled={busy}
                    onClick={() => void doMark(draft, "skipped")}
                    type="button"
                  >
                    跳过
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className={styles.panel}>
        <h3>模板库（{templates.length}）</h3>
        <p className={styles.hint}>
          只有<strong>首封开发信</strong>随店型变；跟进信和 5 个回复模板全店型
          共用——以后店型涨到 24 个，也还是这几个模板。
        </p>
        {!templates.length ? (
          <p className={styles.empty}>还没有模板，点上面「先灌入内置模板」。</p>
        ) : (
          <ul className={styles.templateList}>
            {templates.map((template) => (
              <li className={styles.template} key={template.id}>
                <button
                  className={styles.templateHead}
                  onClick={() =>
                    setOpenTemplate(
                      openTemplate === template.id ? null : template.id,
                    )
                  }
                  type="button"
                >
                  <span>{template.kind_label}</span>
                  <span className={styles.muted}>
                    {template.language === "es" ? "西班牙语" : "英文"}
                    {template.store_type ? ` · ${template.store_type}` : " · 通用"}
                  </span>
                </button>
                {openTemplate === template.id ? (
                  <div className={styles.templateBody}>
                    <div className={styles.subject}>{template.subject}</div>
                    <textarea
                      className={styles.textarea}
                      onChange={(event) =>
                        setEdits((prev) => ({
                          ...prev,
                          [template.id]: event.target.value,
                        }))
                      }
                      rows={12}
                      value={edits[template.id] ?? template.body}
                    />
                    <button
                      className={styles.primaryButton}
                      disabled={busy || edits[template.id] === undefined}
                      onClick={() => void doSaveTemplate(template)}
                      type="button"
                    >
                      保存
                    </button>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
