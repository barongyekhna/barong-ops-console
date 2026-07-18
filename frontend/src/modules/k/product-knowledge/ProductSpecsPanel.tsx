"use client";

import {
  AlertTriangle,
  Clipboard,
  LoaderCircle,
  Plus,
  Save,
  Sparkles,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  getCategorySpecTemplate,
  parseProductSpecsPaste,
  updateProduct,
} from "./api";
import { CategorySpecTemplateEditor } from "./CategorySpecTemplateEditor";
import styles from "./ProductKnowledge.module.css";
import {
  applyPasteResultToDrafts,
  buildOperatorStructuredSpecs,
  hasProductSpecDraftValue,
  missingRequiredDraftKeys,
  newManualSpecDraft,
  productSpecDraftsFromStored,
  updateProductSpecDraftValue,
  type ProductSpecDraft,
} from "./spec-template";
import type {
  CategorySpecTemplate,
  ProductKnowledgeDetail,
  SpecPasteParseResponse,
} from "./types";

type ProductSpecsPanelProps = {
  onProductUpdated: (product: ProductKnowledgeDetail) => void;
  product: ProductKnowledgeDetail;
};

function structuredSpecSource(product: ProductKnowledgeDetail) {
  const source = product.structured_specs_json?.source;
  return source && typeof source === "object" && !Array.isArray(source)
    ? String((source as Record<string, unknown>).platform ?? "")
    : "";
}

function fieldLabel(drafts: ProductSpecDraft[], key: string) {
  const draft = drafts.find((item) => item.key === key);
  return draft?.labelZh || key;
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export function ProductSpecsPanel({
  onProductUpdated,
  product,
}: ProductSpecsPanelProps) {
  const [template, setTemplate] = useState<CategorySpecTemplate | null>(null);
  const [templateLoading, setTemplateLoading] = useState(false);
  const [templateError, setTemplateError] = useState("");
  const [drafts, setDrafts] = useState<ProductSpecDraft[]>([]);
  const [pasteText, setPasteText] = useState("");
  const [parseResult, setParseResult] = useState<SpecPasteParseResponse | null>(
    null,
  );
  const [parseError, setParseError] = useState("");
  const [isParsing, setIsParsing] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [saveNotice, setSaveNotice] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const parseRequestRef = useRef(0);
  const activeProductIdRef = useRef(product.id);
  const activeCategoryRef = useRef({
    id: product.category_id ?? null,
    tree: product.category_tree ?? null,
  });
  activeProductIdRef.current = product.id;
  activeCategoryRef.current = {
    id: product.category_id ?? null,
    tree: product.category_tree ?? null,
  };

  const categoryId = product.category_id ?? null;
  const categoryTree = product.category_tree ?? null;
  const supplierReadOnly = structuredSpecSource(product) === "1688";
  const approvedTemplate = template?.status === "approved" ? template : null;
  const structuredSpecsFingerprint = useMemo(
    () => JSON.stringify(product.structured_specs_json ?? null),
    [product.structured_specs_json],
  );

  useEffect(() => {
    let cancelled = false;
    setTemplate(null);
    setTemplateError("");
    setPasteText("");
    setParseResult(null);
    setParseError("");
    setSaveError("");
    setSaveNotice("");
    parseRequestRef.current += 1;
    setIsParsing(false);
    setIsSaving(false);

    if (!categoryId || !categoryTree) {
      setTemplateLoading(false);
      return () => {
        cancelled = true;
      };
    }

    setTemplateLoading(true);
    void getCategorySpecTemplate(categoryTree, categoryId)
      .then((loaded) => {
        if (!cancelled) {
          setTemplate(loaded);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setTemplateError(errorMessage(error, "类目规格模板加载失败。"));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setTemplateLoading(false);
        }
      });

    return () => {
      cancelled = true;
      parseRequestRef.current += 1;
    };
  }, [categoryId, categoryTree, product.id]);

  useEffect(() => {
    setDrafts(
      productSpecDraftsFromStored(
        approvedTemplate,
        product.structured_specs_json,
      ),
    );
    setSaveError("");
  }, [approvedTemplate, product.id, structuredSpecsFingerprint]);

  const localMissingRequired = useMemo(
    () => missingRequiredDraftKeys(drafts),
    [drafts],
  );
  const displayedMissingRequired =
    approvedTemplate
      ? localMissingRequired
      : product.specs_incomplete
        ? product.missing_required_specs ?? []
        : [];

  function updateDraft(index: number, update: Partial<ProductSpecDraft>) {
    setDrafts((current) =>
      current.map((draft, draftIndex) =>
        draftIndex === index ? { ...draft, ...update } : draft,
      ),
    );
    setSaveError("");
    setSaveNotice("");
  }

  function updateDraftValue(index: number, value: string) {
    setDrafts((current) =>
      current.map((draft, draftIndex) =>
        draftIndex === index
          ? updateProductSpecDraftValue(draft, value)
          : draft,
      ),
    );
    setSaveError("");
    setSaveNotice("");
  }

  async function parsePaste() {
    const rawText = pasteText.trim();
    if (!rawText || !approvedTemplate) {
      return;
    }
    const requestId = ++parseRequestRef.current;
    const productId = product.id;
    setIsParsing(true);
    setParseError("");
    setParseResult(null);
    try {
      const result = await parseProductSpecsPaste(product.id, rawText);
      if (
        parseRequestRef.current !== requestId ||
        activeProductIdRef.current !== productId
      ) {
        return;
      }
      setDrafts((current) => applyPasteResultToDrafts(current, result));
      setParseResult(result);
    } catch (error) {
      if (parseRequestRef.current === requestId) {
        setParseError(errorMessage(error, "1688 规格解析失败。"));
      }
    } finally {
      if (parseRequestRef.current === requestId) {
        setIsParsing(false);
      }
    }
  }

  async function saveSpecs() {
    if (supplierReadOnly) {
      setSaveError("供应商证据规格为只读，不能用人工值覆盖。");
      return;
    }
    const productId = product.id;
    setIsSaving(true);
    setSaveError("");
    setSaveNotice("");
    try {
      const structuredSpecs = buildOperatorStructuredSpecs(drafts);
      const updated = await updateProduct(productId, {
        structured_specs_json: structuredSpecs,
      });
      if (activeProductIdRef.current !== productId) {
        return;
      }
      onProductUpdated(updated);
      setParseResult(null);
      setSaveNotice(
        updated.specs_incomplete
          ? "规格已保存，但模板必填项仍未齐；上架门禁会保持阻断。"
          : "规格已保存。",
      );
    } catch (error) {
      if (activeProductIdRef.current === productId) {
        setSaveError(errorMessage(error, "规格保存失败。"));
      }
    } finally {
      if (activeProductIdRef.current === productId) {
        setIsSaving(false);
      }
    }
  }

  function renderValueControl(draft: ProductSpecDraft, index: number) {
    if (draft.key === "dimensions" && draft.target === "standard") {
      return (
        <input
          disabled={supplierReadOnly}
          onChange={(event) => updateDraftValue(index, event.target.value)}
          placeholder={`长 × 宽 × 高${draft.unit ? `（${draft.unit}）` : ""}`}
          type="text"
          value={draft.inputValue}
        />
      );
    }
    if (draft.valueType === "boolean") {
      return (
        <select
          disabled={supplierReadOnly}
          onChange={(event) => updateDraftValue(index, event.target.value)}
          value={draft.inputValue}
        >
          <option value="">未知 / 未填写</option>
          <option value="true">是</option>
          <option value="false">否</option>
        </select>
      );
    }
    if (draft.valueType === "enum") {
      return (
        <select
          disabled={supplierReadOnly}
          onChange={(event) => updateDraftValue(index, event.target.value)}
          value={draft.inputValue}
        >
          <option value="">未知 / 未填写</option>
          {draft.enumOptions.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      );
    }
    return (
      <input
        disabled={supplierReadOnly}
        onChange={(event) => updateDraftValue(index, event.target.value)}
        placeholder={draft.hintZh || "未知项保持为空"}
        step={draft.valueType === "number" ? "any" : undefined}
        type={draft.valueType === "number" ? "number" : "text"}
        value={draft.inputValue}
      />
    );
  }

  return (
    <section className={styles.workflowSection} aria-labelledby="k-fact-specs">
      <div className={styles.sellingPointsHeading}>
        <div>
          <span className={styles.eyebrow}>规格</span>
          <h4 id="k-fact-specs">类目事实规格</h4>
        </div>
        {!supplierReadOnly ? (
          <button
            className="secondary-button"
            onClick={() =>
              setDrafts((current) => [...current, newManualSpecDraft(current)])
            }
            type="button"
          >
            <Plus aria-hidden="true" size={15} />
            添加额外规格
          </button>
        ) : null}
      </div>

      <p className={styles.keywordAiNotice}>
        只保存可核验事实；解析拆不出的字段会保持为空。
        {supplierReadOnly ? " 当前为 1688 供应商证据，只读展示。" : ""}
      </p>

      {!categoryId || !categoryTree ? (
        <div className={styles.specWarning}>
          <AlertTriangle aria-hidden="true" size={16} />
          <span>产品尚未绑定叶子类目，暂时无法加载类目规格模板。</span>
        </div>
      ) : templateLoading ? (
        <div className={styles.specInlineState}>
          <LoaderCircle aria-hidden="true" className="spin" size={16} />
          正在加载类目规格模板…
        </div>
      ) : templateError ? null : (
        <CategorySpecTemplateEditor
          categoryId={categoryId}
          categoryLabel={product.category_path ?? categoryId}
          categoryTree={categoryTree}
          onTemplateChange={(nextTemplate) => {
            const activeCategory = activeCategoryRef.current;
            if (
              nextTemplate.category_id !== activeCategory.id ||
              nextTemplate.category_tree !== activeCategory.tree
            ) {
              return;
            }
            setTemplate(nextTemplate);
            parseRequestRef.current += 1;
            setIsParsing(false);
            setParseResult(null);
            setParseError("");
          }}
          template={template}
        />
      )}

      {templateError ? (
        <p className={styles.sellingPointsError}>{templateError}</p>
      ) : null}

      {approvedTemplate && !supplierReadOnly ? (
        <div className={styles.specPastePanel}>
          <div className={styles.specPasteHeading}>
            <div>
              <Clipboard aria-hidden="true" size={16} />
              <strong>粘贴 1688 规格</strong>
            </div>
            <span>支持表格文本、键值行或杂乱段落</span>
          </div>
          <textarea
            onChange={(event) => {
              parseRequestRef.current += 1;
              setIsParsing(false);
              setPasteText(event.target.value);
              setParseError("");
              setParseResult(null);
            }}
            placeholder="从 1688 详情页复制规格表并粘贴到这里…"
            value={pasteText}
          />
          <div className={styles.specPasteActions}>
            <span>AI 只按已批准模板匹配，不会直接写库。</span>
            <button
              className="secondary-button"
              disabled={isParsing || !pasteText.trim()}
              onClick={() => void parsePaste()}
              type="button"
            >
              {isParsing ? (
                <LoaderCircle aria-hidden="true" className="spin" size={15} />
              ) : (
                <Sparkles aria-hidden="true" size={15} />
              )}
              解析
            </button>
          </div>
          {parseError ? <p className={styles.sellingPointsError}>{parseError}</p> : null}
          {parseResult ? (
            <div className={styles.specParseSummary}>
              <span data-kind="matched">
                已匹配 {Object.keys(parseResult.matched).length} 项
              </span>
              <span data-kind={parseResult.missing_required.length ? "missing" : "ok"}>
                必填缺失 {parseResult.missing_required.length} 项
              </span>
              <span data-kind={parseResult.unmatched_lines.length ? "unmatched" : "ok"}>
                未匹配 {parseResult.unmatched_lines.length} 行
              </span>
            </div>
          ) : null}
          {parseResult?.unmatched_lines.length ? (
            <details className={styles.specUnmatchedLines}>
              <summary>查看未匹配原文</summary>
              <ul>
                {parseResult.unmatched_lines.slice(0, 20).map((line, index) => (
                  <li key={`${index}-${line}`}>{line}</li>
                ))}
              </ul>
              {parseResult.unmatched_lines.length > 20 ? (
                <p>另有 {parseResult.unmatched_lines.length - 20} 行未展开。</p>
              ) : null}
            </details>
          ) : null}
        </div>
      ) : null}

      {drafts.length === 0 ? (
        <p className={styles.sellingPointsEmpty}>
          暂无事实规格；未知字段保持为空，也不会自动补齐。
        </p>
      ) : (
        <div className={styles.productSpecList}>
          {drafts.map((draft, index) => {
            const missing = draft.required && !hasProductSpecDraftValue(draft);
            return (
              <div
                className={styles.productSpecCard}
                data-missing={missing || undefined}
                data-origin={draft.origin}
                key={`${draft.target}-${draft.key}`}
              >
                <div className={styles.productSpecHeading}>
                  <div>
                    <strong>
                      {draft.labelZh || "额外规格"}
                      {draft.required ? <em aria-label="必填"> *</em> : null}
                    </strong>
                    <span>
                      {draft.labelEn || "自定义事实"} · spec:{draft.key}
                    </span>
                  </div>
                  <div className={styles.productSpecBadges}>
                    {draft.origin === "ai" ? <span data-kind="ai">AI 已匹配</span> : null}
                    {draft.unit ? <span data-kind="unit">{draft.unit}</span> : null}
                    <span data-kind="target">{draft.target}</span>
                  </div>
                </div>

                {draft.fromTemplate ? (
                  <label className={styles.field}>
                    <span>{draft.hintZh || "真实值"}</span>
                    {renderValueControl(draft, index)}
                  </label>
                ) : (
                  <div className={styles.productSpecExtraGrid}>
                    <label className={styles.field}>
                      <span>规格名</span>
                      <input
                        disabled={supplierReadOnly}
                        onChange={(event) => {
                          const label = event.target.value;
                          updateDraft(index, {
                            dirty: true,
                            labelZh: label,
                            origin: "manual",
                            sourceLabel:
                              draft.origin === "ai" && draft.sourceLabel
                                ? draft.sourceLabel
                                : label,
                          });
                        }}
                        value={draft.labelZh}
                      />
                    </label>
                    <label className={styles.field}>
                      <span>真实值</span>
                      {renderValueControl(draft, index)}
                    </label>
                    <label className={styles.field}>
                      <span>单位</span>
                      <input
                        disabled={supplierReadOnly}
                        onChange={(event) =>
                          updateDraft(index, {
                            dirty: true,
                            origin: "manual",
                            unit: event.target.value,
                          })
                        }
                        value={draft.unit}
                      />
                    </label>
                    {!supplierReadOnly ? (
                      <button
                        className="secondary-button"
                        onClick={() =>
                          setDrafts((current) =>
                            current.filter((_, draftIndex) => draftIndex !== index),
                          )
                        }
                        type="button"
                      >
                        <Trash2 aria-hidden="true" size={14} />
                        删除
                      </button>
                    ) : null}
                  </div>
                )}

                {draft.sourceLabel && draft.rawValue ? (
                  <p className={styles.specEvidenceLine}>
                    原始证据：{draft.sourceLabel} = {draft.rawValue}
                  </p>
                ) : null}
              </div>
            );
          })}
        </div>
      )}

      {displayedMissingRequired.length > 0 ? (
        <div className={styles.specWarning}>
          <AlertTriangle aria-hidden="true" size={16} />
          <span>
            必填未齐：
            {displayedMissingRequired
              .map((key) => fieldLabel(drafts, key))
              .join("、")}
            。允许保存，但会阻断 K→P 上架。
          </span>
        </div>
      ) : null}
      {saveError ? <p className={styles.sellingPointsError}>{saveError}</p> : null}
      {saveNotice ? <p className={styles.specSaveNotice}>{saveNotice}</p> : null}

      {!supplierReadOnly ? (
        <div className={styles.sectionFooter}>
          <span data-complete={displayedMissingRequired.length === 0 || undefined}>
            {displayedMissingRequired.length > 0
              ? "保存后仍会标记规格未完成"
              : "模板必填项已齐或当前类目无生效模板"}
          </span>
          <button
            className="primary-button"
            disabled={isSaving}
            onClick={() => void saveSpecs()}
            type="button"
          >
            {isSaving ? (
              <LoaderCircle aria-hidden="true" className="spin" size={16} />
            ) : (
              <Save aria-hidden="true" size={16} />
            )}
            保存规格
          </button>
        </div>
      ) : null}
    </section>
  );
}
