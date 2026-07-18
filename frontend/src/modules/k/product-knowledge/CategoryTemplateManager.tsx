"use client";

import {
  ArrowLeft,
  CheckCircle2,
  FolderTree,
  LoaderCircle,
  Search,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { DashboardScene } from "@/components/dashboard-scene";

import {
  getCategorySpecTemplate,
  searchCategories,
  type CategoryTreeItem,
} from "./api";
import { CategorySpecTemplateEditor } from "./CategorySpecTemplateEditor";
import styles from "./ProductKnowledge.module.css";
import type { CategorySpecTemplate, KCategoryTree } from "./types";

export function CategoryTemplateManager() {
  const [tree, setTree] = useState<KCategoryTree>("google");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<CategoryTreeItem[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [selected, setSelected] = useState<CategoryTreeItem | null>(null);
  const [template, setTemplate] = useState<CategorySpecTemplate | null>(null);
  const [templateLoading, setTemplateLoading] = useState(false);
  const [templateError, setTemplateError] = useState("");
  const templateRequestRef = useRef(0);
  const activeSelectionRef = useRef<{
    categoryId: string;
    tree: KCategoryTree;
  } | null>(null);

  useEffect(() => {
    const term = query.trim();
    if (!term) {
      setResults([]);
      setSearching(false);
      setSearchError("");
      return;
    }

    let cancelled = false;
    const handle = window.setTimeout(() => {
      setSearching(true);
      setSearchError("");
      void searchCategories(tree, term, 50)
        .then((items) => {
          if (!cancelled) {
            setResults(items);
          }
        })
        .catch((error) => {
          if (!cancelled) {
            setResults([]);
            setSearchError(
              error instanceof Error ? error.message : "类目搜索失败。",
            );
          }
        })
        .finally(() => {
          if (!cancelled) {
            setSearching(false);
          }
        });
    }, 300);

    return () => {
      cancelled = true;
      window.clearTimeout(handle);
    };
  }, [query, tree]);

  function selectTree(nextTree: KCategoryTree) {
    templateRequestRef.current += 1;
    activeSelectionRef.current = null;
    setTree(nextTree);
    setSelected(null);
    setTemplate(null);
    setTemplateError("");
    setTemplateLoading(false);
    setResults([]);
  }

  async function selectCategory(item: CategoryTreeItem) {
    if (!item.is_leaf) {
      return;
    }
    const requestedTree = tree;
    const requestId = ++templateRequestRef.current;
    activeSelectionRef.current = {
      categoryId: item.id,
      tree: requestedTree,
    };
    setSelected(item);
    setTemplate(null);
    setTemplateLoading(true);
    setTemplateError("");
    try {
      const loaded = await getCategorySpecTemplate(requestedTree, item.id);
      if (templateRequestRef.current === requestId) {
        setTemplate(loaded);
      }
    } catch (error) {
      if (templateRequestRef.current === requestId) {
        setTemplateError(
          error instanceof Error ? error.message : "类目规格模板加载失败。",
        );
      }
    } finally {
      if (templateRequestRef.current === requestId) {
        setTemplateLoading(false);
      }
    }
  }

  function acceptTemplate(nextTemplate: CategorySpecTemplate) {
    const active = activeSelectionRef.current;
    if (
      active &&
      nextTemplate.category_id === active.categoryId &&
      nextTemplate.category_tree === active.tree
    ) {
      setTemplate(nextTemplate);
      setTemplateError("");
    }
  }

  return (
    <section
      aria-label="K 类目规格模板管理"
      className={`${styles.workspace} mm-page k-page`}
    >
      <DashboardScene />
      <div className={styles.kCommandBar}>
        <div>
          <span className={styles.eyebrow}>K 系列 · 类目管理</span>
          <h2>类目规格模板</h2>
          <p>按 Google / Amazon 叶子类目维护一份人工批准的规格字段模板。</p>
        </div>
        <div className={styles.kCommandActions}>
          <a className="secondary-button" href="/products">
            <ArrowLeft aria-hidden="true" size={15} />
            返回产品知识库
          </a>
        </div>
      </div>

      <div className={styles.categoryTemplateLayout}>
        <section className={styles.categorySearchPanel} aria-label="选择叶子类目">
          <div className={styles.categorySearchHeading}>
            <div>
              <FolderTree aria-hidden="true" size={17} />
              <strong>选择叶子类目</strong>
            </div>
            <div className={styles.categoryTreeToggle}>
              <button
                aria-pressed={tree === "google"}
                onClick={() => selectTree("google")}
                type="button"
              >
                Google
              </button>
              <button
                aria-pressed={tree === "amazon"}
                onClick={() => selectTree("amazon")}
                type="button"
              >
                Amazon
              </button>
            </div>
          </div>

          <label className={styles.categorySearchInput}>
            <Search aria-hidden="true" size={15} />
            <input
              autoFocus
              onChange={(event) => setQuery(event.target.value)}
              placeholder={`搜索 ${tree === "google" ? "Google" : "Amazon"} 类目名称或路径…`}
              type="search"
              value={query}
            />
            {searching ? (
              <LoaderCircle aria-hidden="true" className="spin" size={15} />
            ) : null}
          </label>

          {searchError ? (
            <p className={styles.sellingPointsError}>{searchError}</p>
          ) : null}
          {!query.trim() ? (
            <p className={styles.categorySearchHint}>
              输入关键词后，从结果中选择标记为“叶”的节点。
            </p>
          ) : !searching && results.length === 0 ? (
            <p className={styles.categorySearchHint}>没有匹配类目。</p>
          ) : (
            <ul className={styles.categorySearchResults}>
              {results.map((item) => (
                <li
                  data-selected={selected?.id === item.id || undefined}
                  key={item.id}
                >
                  <button
                    disabled={!item.is_leaf}
                    onClick={() => void selectCategory(item)}
                    title={
                      item.is_leaf ? item.full_path : "模板只能挂在叶子类目"
                    }
                    type="button"
                  >
                    <span>{item.full_path}</span>
                    <em data-leaf={item.is_leaf || undefined}>
                      {item.is_leaf ? "叶" : `L${item.level}`}
                    </em>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className={styles.categoryTemplatePanel} aria-label="模板详情">
          {!selected ? (
            <div className={styles.categoryTemplateEmpty}>
              <FolderTree aria-hidden="true" size={28} />
              <strong>尚未选择叶子类目</strong>
              <span>选择后可查看、AI 起草、审定或编辑该类目的规格模板。</span>
            </div>
          ) : (
            <>
              <div className={styles.categorySelectedHeading}>
                <div>
                  <CheckCircle2 aria-hidden="true" size={16} />
                  <strong>{selected.name}</strong>
                </div>
                <span>{selected.full_path}</span>
              </div>
              {templateLoading ? (
                <div className={styles.specInlineState}>
                  <LoaderCircle aria-hidden="true" className="spin" size={16} />
                  正在加载模板…
                </div>
              ) : templateError ? null : (
                <CategorySpecTemplateEditor
                  categoryId={selected.id}
                  categoryLabel={selected.full_path}
                  categoryTree={tree}
                  onTemplateChange={acceptTemplate}
                  template={template}
                />
              )}
              {templateError ? (
                <p className={styles.sellingPointsError}>{templateError}</p>
              ) : null}
            </>
          )}
        </section>
      </div>
    </section>
  );
}
