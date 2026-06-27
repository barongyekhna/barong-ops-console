"use client";

import { Database, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

import {
  createKeyword,
  deleteKeyword,
  getKeywordsByProduct,
  updateKeyword,
} from "./api";
import { KeywordInput } from "./KeywordInput";
import styles from "./KeywordPanel.module.css";
import { KeywordTable } from "./KeywordTable";
import type {
  CreateKeywordPayload,
  KeywordEntry,
  UpdateKeywordPayload,
} from "./types";

const defaultProductId = "k-series-product-knowledge-001";

export function KeywordPanel() {
  const [entries, setEntries] = useState<KeywordEntry[]>([]);
  const [productId, setProductId] = useState(defaultProductId);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [isSavingEditor, setIsSavingEditor] = useState(false);
  const [isDeletingId, setIsDeletingId] = useState<string | null>(null);
  const [message, setMessage] = useState("就绪。");
  const [error, setError] = useState("");

  useEffect(() => {
    void loadKeywords(defaultProductId);
  }, []);

  async function loadKeywords(nextProductId = productId) {
    const normalizedProductId = nextProductId.trim();

    if (!normalizedProductId) {
      setEntries([]);
      setError("必须填写产品ID。");
      setMessage("");
      return;
    }

    setIsLoading(true);
    setError("");

    try {
      const response = await getKeywordsByProduct(normalizedProductId);
      setEntries(response.keyword_entries);
      setMessage(`已加载 ${response.keyword_entries.length} 条关键词。`);
    } catch (caught) {
      setEntries([]);
      setError(
        caught instanceof Error ? caught.message : "关键词加载失败。",
      );
      setMessage("");
    } finally {
      setIsLoading(false);
    }
  }

  async function handleCreate(payload: CreateKeywordPayload) {
    setIsCreating(true);
    setError("");

    try {
      const response = await createKeyword(payload);
      setProductId(response.keyword_entry.product_id);
      setEntries((currentEntries) =>
        upsertEntry(currentEntries, response.keyword_entry),
      );
      setMessage("关键词已创建。");
      return true;
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "关键词创建失败。",
      );
      setMessage("");
      return false;
    } finally {
      setIsCreating(false);
    }
  }

  async function handleEditorSave(
    keywordId: string,
    payload: UpdateKeywordPayload,
  ) {
    setIsSavingEditor(true);
    setError("");

    try {
      const response = await updateKeyword(keywordId, payload);
      setEntries((currentEntries) =>
        upsertEntry(currentEntries, response.keyword_entry),
      );
      setEditingId(null);
      setMessage("关键词已更新。");
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "关键词更新失败。",
      );
      setMessage("");
    } finally {
      setIsSavingEditor(false);
    }
  }

  async function handleArchive(keywordId: string) {
    setIsDeletingId(keywordId);
    setError("");

    try {
      const response = await deleteKeyword(keywordId);
      setEntries((currentEntries) =>
        upsertEntry(currentEntries, response.keyword_entry),
      );
      setMessage("关键词已归档。");
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "关键词归档失败。",
      );
      setMessage("");
    } finally {
      setIsDeletingId(null);
    }
  }

  return (
    <section className={styles.panel} aria-labelledby="k19-keyword-panel">
      <div className={styles.heading}>
        <div className={styles.headingTitle}>
          <Database aria-hidden="true" size={20} />
          <div>
            <span className="section-index">K19</span>
            <h3 id="k19-keyword-panel">关键词控制</h3>
          </div>
        </div>
        <div className={styles.summary}>
          <strong>{entries.length}</strong>
          <span>条记录</span>
        </div>
      </div>

      <KeywordInput
        isSaving={isCreating}
        onCreate={handleCreate}
        productId={productId}
      />

      <KeywordTable
        editingId={editingId}
        entries={entries}
        isDeletingId={isDeletingId}
        isLoading={isLoading}
        isSavingEditor={isSavingEditor}
        onArchive={handleArchive}
        onEdit={setEditingId}
        onEditorCancel={() => setEditingId(null)}
        onEditorSave={handleEditorSave}
        onProductIdChange={setProductId}
        onRefresh={() => loadKeywords()}
        productId={productId}
      />

      <p className={`${styles.message} ${error ? styles.error : ""}`}>
        {isLoading ? (
          <>
            <Loader2 aria-hidden="true" className="spin" size={14} />
            正在加载关键词。
          </>
        ) : (
          error || message
        )}
      </p>
    </section>
  );
}

function upsertEntry(entries: KeywordEntry[], nextEntry: KeywordEntry) {
  const existingIndex = entries.findIndex((entry) => entry.id === nextEntry.id);

  if (existingIndex === -1) {
    return [nextEntry, ...entries];
  }

  return entries.map((entry, index) =>
    index === existingIndex ? nextEntry : entry,
  );
}
