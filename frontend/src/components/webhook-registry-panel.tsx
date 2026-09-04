"use client";

import { LoaderCircle, Plus, Trash2, Webhook } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import {
  createWebhookRegistryEntry,
  deleteWebhookRegistryEntry,
  listWebhookRegistry,
  type WebhookRegistryEntry,
} from "@/lib/webhook-registry-api";

const EMPTY_FORM = {
  series: "P",
  workflow_name: "",
  webhook_url: "",
  respond_url: "",
};

export function WebhookRegistryPanel() {
  const [entries, setEntries] = useState<WebhookRegistryEntry[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const data = await listWebhookRegistry();
      setEntries(data.entries);
      setError(null);
    } catch (loadError) {
      setError(
        loadError instanceof Error ? loadError.message : "登记簿加载失败。",
      );
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleCreate(event: React.FormEvent) {
    event.preventDefault();
    setIsSaving(true);
    setError(null);
    try {
      await createWebhookRegistryEntry({
        series: form.series,
        workflow_name: form.workflow_name,
        webhook_url: form.webhook_url,
        respond_url: form.respond_url || undefined,
      });
      setForm(EMPTY_FORM);
      await load();
    } catch (saveError) {
      setError(
        saveError instanceof Error ? saveError.message : "登记失败，请重试。",
      );
    } finally {
      setIsSaving(false);
    }
  }

  async function handleDelete(id: number) {
    try {
      await deleteWebhookRegistryEntry(id);
      await load();
    } catch (deleteError) {
      setError(
        deleteError instanceof Error ? deleteError.message : "删除失败。",
      );
    }
  }

  return (
    <div className="webhook-test-band" style={{ marginBottom: 18 }}>
      <div className="ops-panel-heading">
        <div>
          <h3>Webhook 登记簿</h3>
          <p>
            各系列在用的 n8n webhook 备案（只记录，不参与真实调用 ——
            调用仍走各系列自己的配置）。
          </p>
        </div>
        <Webhook aria-hidden="true" size={18} />
      </div>

      {error ? (
        <p role="alert" style={{ color: "var(--color-error)", margin: "6px 0" }}>
          {error}
        </p>
      ) : null}

      {isLoading ? (
        <p style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <LoaderCircle aria-hidden="true" className="spin" size={15} />
          正在加载登记簿…
        </p>
      ) : entries.length === 0 ? (
        <p>暂无登记。用下方表单把在用的 webhook 记录进来。</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.84rem" }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left", padding: "6px 10px" }}>系列</th>
                <th style={{ textAlign: "left", padding: "6px 10px" }}>n8n 工作流</th>
                <th style={{ textAlign: "left", padding: "6px 10px" }}>Webhook URL</th>
                <th style={{ textAlign: "left", padding: "6px 10px" }}>回传（respond）URL</th>
                <th aria-label="操作" />
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <tr key={entry.id}>
                  <td style={{ padding: "6px 10px", fontWeight: 700 }}>{entry.series}</td>
                  <td style={{ padding: "6px 10px" }}>{entry.workflow_name}</td>
                  <td style={{ padding: "6px 10px", fontFamily: "monospace", fontSize: "0.78rem", wordBreak: "break-all" }}>
                    {entry.webhook_url}
                  </td>
                  <td style={{ padding: "6px 10px", fontFamily: "monospace", fontSize: "0.78rem", wordBreak: "break-all" }}>
                    {entry.respond_url || "—"}
                  </td>
                  <td style={{ padding: "6px 10px" }}>
                    <button
                      aria-label="删除登记"
                      className="secondary-button"
                      onClick={() => void handleDelete(entry.id)}
                      type="button"
                    >
                      <Trash2 aria-hidden="true" size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <form className="api-key-binding-form" onSubmit={handleCreate}>
        <label className="field-group">
          <span>来源系列</span>
          <span className="input-shell">
            <input
              maxLength={32}
              onChange={(event) => setForm({ ...form, series: event.target.value })}
              placeholder="P / GMC / SEO…"
              required
              value={form.series}
            />
          </span>
        </label>
        <label className="field-group">
          <span>n8n 工作流名称</span>
          <span className="input-shell">
            <input
              maxLength={255}
              onChange={(event) =>
                setForm({ ...form, workflow_name: event.target.value })
              }
              placeholder="barong控制台-P系列-上架WooCommerce"
              required
              value={form.workflow_name}
            />
          </span>
        </label>
        <label className="field-group">
          <span>Webhook URL</span>
          <span className="input-shell">
            <input
              maxLength={1024}
              onChange={(event) =>
                setForm({ ...form, webhook_url: event.target.value })
              }
              placeholder="工作流的触发地址"
              required
              value={form.webhook_url}
            />
          </span>
        </label>
        <label className="field-group">
          <span>回传（respond）URL</span>
          <span className="input-shell">
            <input
              maxLength={1024}
              onChange={(event) =>
                setForm({ ...form, respond_url: event.target.value })
              }
              placeholder="http://console_backend:8000/…（可选）"
              value={form.respond_url}
            />
          </span>
        </label>
        <button className="primary-button" disabled={isSaving} type="submit">
          {isSaving ? (
            <LoaderCircle aria-hidden="true" className="spin" size={15} />
          ) : (
            <Plus aria-hidden="true" size={15} />
          )}
          登记
        </button>
      </form>
    </div>
  );
}
