"use client";

import { CheckCircle2, LoaderCircle, Pencil, Plus, Save, Sparkles, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";

import {
  draftCategorySpecTemplate,
  putCategorySpecTemplate,
} from "./api";
import styles from "./ProductKnowledge.module.css";
import {
  newCategorySpecField,
  STANDARD_SPEC_KEYS,
  templateFieldValidationErrors,
} from "./spec-template";
import type {
  CategorySpecField,
  CategorySpecTemplate,
  KCategoryTree,
} from "./types";

type CategorySpecTemplateEditorProps = {
  categoryId: string;
  categoryLabel?: string | null;
  categoryTree: KCategoryTree;
  onTemplateChange: (template: CategorySpecTemplate) => void;
  template: CategorySpecTemplate | null;
};

function cloneFields(fields: CategorySpecField[]) {
  return fields.map((field) => ({
    ...field,
    enum_options: field.enum_options ? [...field.enum_options] : null,
    value_type: field.key === "dimensions" ? "text" : field.value_type,
  }));
}

function enumOptionsFromInput(value: string) {
  const options = value
    .split(/[\n,，]/u)
    .map((option) => option.trim())
    .filter(Boolean);
  return options.length > 0 ? [...new Set(options)] : [];
}

export function CategorySpecTemplateEditor({
  categoryId,
  categoryLabel,
  categoryTree,
  onTemplateChange,
  template,
}: CategorySpecTemplateEditorProps) {
  const [fields, setFields] = useState<CategorySpecField[]>([]);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState<"draft" | "save" | "approve" | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    setFields(cloneFields(template?.fields ?? []));
    setEditing(template?.status === "draft");
    setError("");
    setNotice("");
  }, [categoryId, categoryTree, template]);

  function updateField(index: number, patch: Partial<CategorySpecField>) {
    setFields((current) =>
      current.map((field, fieldIndex) =>
        fieldIndex === index ? { ...field, ...patch } : field,
      ),
    );
    setError("");
    setNotice("");
  }

  async function createDraft() {
    setBusy("draft");
    setError("");
    setNotice("");
    try {
      const drafted = await draftCategorySpecTemplate(categoryTree, categoryId);
      onTemplateChange(drafted);
      setNotice("AI 草稿已生成。请逐项核对，批准前不会影响产品门禁。");
    } catch (draftError) {
      setError(
        draftError instanceof Error ? draftError.message : "规格模板起草失败。",
      );
    } finally {
      setBusy(null);
    }
  }

  async function saveTemplate(status: CategorySpecTemplate["status"]) {
    const errors = templateFieldValidationErrors(fields);
    if (errors.length > 0) {
      setError(errors[0]);
      return;
    }
    setBusy(status === "approved" ? "approve" : "save");
    setError("");
    setNotice("");
    try {
      const saved = await putCategorySpecTemplate(categoryTree, categoryId, {
        fields,
        status,
      });
      onTemplateChange(saved);
      setEditing(saved.status === "draft");
      setNotice(
        saved.status === "approved"
          ? "模板已批准并生效。"
          : "模板草稿已保存，尚未参与必填门禁。",
      );
    } catch (saveError) {
      setError(
        saveError instanceof Error ? saveError.message : "规格模板保存失败。",
      );
    } finally {
      setBusy(null);
    }
  }

  if (!template) {
    return (
      <div className={styles.templateEmptyState}>
        <div>
          <strong>该类目还没有规格模板</strong>
          <span>
            {categoryLabel || `${categoryTree}:${categoryId}`} · AI 只会起草，需人工批准后才生效。
          </span>
        </div>
        <button
          className="secondary-button"
          disabled={busy !== null}
          onClick={() => void createDraft()}
          type="button"
        >
          {busy === "draft" ? (
            <LoaderCircle aria-hidden="true" className="spin" size={15} />
          ) : (
            <Sparkles aria-hidden="true" size={15} />
          )}
          AI 起草模板
        </button>
        {error ? <p className={styles.sellingPointsError}>{error}</p> : null}
      </div>
    );
  }

  if (template.status === "approved" && !editing) {
    return (
      <div className={styles.templateApprovedSummary}>
        <div>
          <span className={styles.templateStatusBadge} data-status="approved">
            <CheckCircle2 aria-hidden="true" size={13} />
            已批准
          </span>
          <strong>{template.fields.length} 个类目规格字段</strong>
          {notice ? <small>{notice}</small> : null}
        </div>
        <button
          className="secondary-button"
          onClick={() => setEditing(true)}
          type="button"
        >
          <Pencil aria-hidden="true" size={14} />
          编辑模板
        </button>
      </div>
    );
  }

  return (
    <div className={styles.templateEditor}>
      <div className={styles.templateEditorHeading}>
        <div>
          <span className={styles.templateStatusBadge} data-status={template.status}>
            {template.status === "draft" ? "AI 草稿 · 未生效" : "编辑已批准模板"}
          </span>
          <strong>{categoryLabel || `${categoryTree}:${categoryId}`}</strong>
        </div>
        <button
          className="secondary-button"
          onClick={() =>
            setFields((current) => [...current, newCategorySpecField(current)])
          }
          type="button"
        >
          <Plus aria-hidden="true" size={14} />
          添加字段
        </button>
      </div>

      <p className={styles.keywordAiNotice}>
        key 必须是 snake_case；英文标签为买家展示红线。标准键只能写入 standard。
      </p>

      <div className={styles.templateFieldList}>
        {fields.map((field, index) => (
          <div className={styles.templateFieldCard} key={`${field.key}-${index}`}>
            <div className={styles.templateFieldGrid}>
              <label className={styles.field}>
                <span>稳定 key</span>
                <input
                  onChange={(event) => {
                    const key = event.target.value.trim().toLowerCase();
                    updateField(index, {
                      key,
                      target: STANDARD_SPEC_KEYS.has(key)
                        ? "standard"
                        : field.target === "standard"
                          ? "additional"
                          : field.target,
                      value_type:
                        key === "dimensions" ? "text" : field.value_type,
                    });
                  }}
                  value={field.key}
                />
              </label>
              <label className={styles.field}>
                <span>落库层</span>
                <select
                  disabled={STANDARD_SPEC_KEYS.has(field.key)}
                  onChange={(event) =>
                    updateField(index, {
                      target: event.target.value as CategorySpecField["target"],
                    })
                  }
                  value={field.target}
                >
                  <option value="additional">additional</option>
                  <option value="standard">standard</option>
                </select>
              </label>
              <label className={styles.field}>
                <span>中文标签</span>
                <input
                  onChange={(event) =>
                    updateField(index, { label_zh: event.target.value })
                  }
                  value={field.label_zh}
                />
              </label>
              <label className={styles.field}>
                <span>英文标签</span>
                <input
                  lang="en"
                  onChange={(event) =>
                    updateField(index, { label_en: event.target.value })
                  }
                  value={field.label_en}
                />
              </label>
              <label className={styles.field}>
                <span>值类型</span>
                <select
                  disabled={field.key === "dimensions"}
                  onChange={(event) => {
                    const valueType = event.target
                      .value as CategorySpecField["value_type"];
                    updateField(index, {
                      enum_options: valueType === "enum" ? [] : null,
                      value_type: valueType,
                    });
                  }}
                  value={field.value_type}
                >
                  <option value="number">number</option>
                  <option value="text">text</option>
                  <option value="enum">enum</option>
                  <option value="boolean">boolean</option>
                </select>
              </label>
              <label className={styles.field}>
                <span>单位</span>
                <input
                  onChange={(event) =>
                    updateField(index, { unit: event.target.value || null })
                  }
                  value={field.unit ?? ""}
                />
              </label>
              {field.value_type === "enum" ? (
                <label className={`${styles.field} ${styles.templateWideField}`}>
                  <span>枚举选项（逗号或换行分隔）</span>
                  <textarea
                    onChange={(event) =>
                      updateField(index, {
                        enum_options: enumOptionsFromInput(event.target.value),
                      })
                    }
                    value={(field.enum_options ?? []).join("\n")}
                  />
                </label>
              ) : null}
              <label className={`${styles.field} ${styles.templateWideField}`}>
                <span>中文提示</span>
                <input
                  onChange={(event) =>
                    updateField(index, { hint_zh: event.target.value || null })
                  }
                  value={field.hint_zh ?? ""}
                />
              </label>
            </div>
            <div className={styles.templateFieldActions}>
              <label>
                <input
                  checked={field.required}
                  onChange={(event) =>
                    updateField(index, { required: event.target.checked })
                  }
                  type="checkbox"
                />{" "}
                必填
              </label>
              <button
                className="secondary-button"
                disabled={fields.length <= 1}
                onClick={() =>
                  setFields((current) =>
                    current.filter((_, fieldIndex) => fieldIndex !== index),
                  )
                }
                type="button"
              >
                <Trash2 aria-hidden="true" size={14} />
                删除
              </button>
            </div>
          </div>
        ))}
      </div>

      {error ? <p className={styles.sellingPointsError}>{error}</p> : null}
      {notice ? <p className={styles.templateNotice}>{notice}</p> : null}

      <div className={styles.templateEditorFooter}>
        {template.status === "approved" ? (
          <button
            className="secondary-button"
            disabled={busy !== null}
            onClick={() => {
              setFields(cloneFields(template.fields));
              setEditing(false);
              setError("");
            }}
            type="button"
          >
            <X aria-hidden="true" size={14} />
            取消
          </button>
        ) : (
          <button
            className="secondary-button"
            disabled={busy !== null}
            onClick={() => void saveTemplate("draft")}
            type="button"
          >
            {busy === "save" ? (
              <LoaderCircle aria-hidden="true" className="spin" size={14} />
            ) : (
              <Save aria-hidden="true" size={14} />
            )}
            保存草稿
          </button>
        )}
        <button
          className="primary-button"
          disabled={busy !== null}
          onClick={() => void saveTemplate("approved")}
          type="button"
        >
          {busy === "approve" ? (
            <LoaderCircle aria-hidden="true" className="spin" size={14} />
          ) : (
            <CheckCircle2 aria-hidden="true" size={14} />
          )}
          {template.status === "approved" ? "保存修改" : "批准并启用"}
        </button>
      </div>
    </div>
  );
}
