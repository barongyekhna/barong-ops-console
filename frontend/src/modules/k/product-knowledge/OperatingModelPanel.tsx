"use client";

import { LoaderCircle, Save } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { getProduct, updateOperatingModel, type OperatingModel } from "./api";
import styles from "./ProductKnowledge.module.css";

function formatError(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "保存失败，请重试。";
}

function toLines(values: string[]): string {
  return values.join("\n");
}

function fromLines(value: string): string[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

const EMPTY: OperatingModel = {
  buyer_personas: [],
  forbidden_depictions: [],
  hard_constraints: [],
  how_it_works: "",
};

/**
 * 「这个产品怎么工作」面板。
 *
 * 2026-08-03 熊猫花洒(潜水泵)教训：作图链路上原本没有任何一环知道产品的物理
 * 工作方式——作图 AI 只拿到文字规格、从没见过产品照片，于是把泵画在干燥地面上
 * 却在喷水。现在生成作图指令时会先看原厂参考图推导出这份「工作原理」，排图组、
 * 渲染 prompt、图片审查三处共用。
 *
 * 这里改完会置 edited_by_user=true —— 之后重新生成作图指令不会再被 AI 推导
 * 覆盖，人工纠正永远权威。
 */
export function OperatingModelPanel({
  productId,
  refreshKey = 0,
}: {
  productId: string;
  /** 上层数据变化(如作图指令生成完成)时 +1，触发重新拉取。 */
  refreshKey?: number;
}) {
  const [model, setModel] = useState<OperatingModel>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const product = await getProduct(productId);
      const brief = (
        product as {
          image_instruction_json?: { operating_model?: unknown } | null;
        }
      ).image_instruction_json;
      const raw = brief?.operating_model;
      if (raw && typeof raw === "object") {
        const value = raw as Partial<OperatingModel>;
        setModel({
          buyer_personas: Array.isArray(value.buyer_personas)
            ? value.buyer_personas.map(String)
            : [],
          derived_at: value.derived_at ?? null,
          edited_at: value.edited_at ?? null,
          edited_by_user: Boolean(value.edited_by_user),
          forbidden_depictions: Array.isArray(value.forbidden_depictions)
            ? value.forbidden_depictions.map(String)
            : [],
          hard_constraints: Array.isArray(value.hard_constraints)
            ? value.hard_constraints.map(String)
            : [],
          how_it_works:
            typeof value.how_it_works === "string" ? value.how_it_works : "",
        });
      } else {
        setModel(EMPTY);
      }
      setDirty(false);
    } catch (loadError) {
      setError(formatError(loadError));
    } finally {
      setLoading(false);
    }
  }, [productId]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  function patch(update: Partial<OperatingModel>) {
    setModel((current) => ({ ...current, ...update }));
    setDirty(true);
    setNotice("");
  }

  async function save() {
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const saved = await updateOperatingModel(productId, {
        buyer_personas: model.buyer_personas,
        forbidden_depictions: model.forbidden_depictions,
        hard_constraints: model.hard_constraints,
        how_it_works: model.how_it_works.trim(),
      });
      setModel(saved);
      setDirty(false);
      setNotice(
        "已保存。重新生成作图指令不会再覆盖它——下一轮排图组、渲染、图片审查都按这份来。",
      );
    } catch (saveError) {
      setError(formatError(saveError));
    } finally {
      setSaving(false);
    }
  }

  const isEmpty =
    !model.how_it_works &&
    model.hard_constraints.length === 0 &&
    model.forbidden_depictions.length === 0 &&
    model.buyer_personas.length === 0;

  return (
    <section
      aria-labelledby="k-operating-model"
      className={styles.sellingPointsSection}
    >
      <header className={styles.sellingPointsHeader}>
        <div>
          <h4 id="k-operating-model">这个产品怎么工作 · 作图物理约束</h4>
          <p className={styles.sellingPointsHint}>
            生成作图指令时，AI 会看原厂参考图推导出这份「工作原理」，
            排图组、渲染、图片审查三处共用。
            <strong>它错了整套图就会照着错的画</strong>（潜水泵被画在干地上还在喷水，
            就是因为没有这一层）。改完这里会锁定为人工版本，之后重新生成不再被覆盖。
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            className="secondary-button"
            disabled={loading || saving || !dirty}
            onClick={() => void save()}
            type="button"
          >
            {saving ? (
              <LoaderCircle aria-hidden="true" className="spin" size={15} />
            ) : (
              <Save aria-hidden="true" size={15} />
            )}
            保存
          </button>
        </div>
      </header>
      {loading ? (
        <p className={styles.sellingPointsHint}>加载中…</p>
      ) : (
        <div style={{ display: "grid", gap: 12 }}>
          {isEmpty ? (
            <p className={styles.sellingPointsHint}>
              还没有推导结果 —— 生成一次「作图指令」就会自动产出；
              普通产品（放着就能用、拿着就能用）本来就该是空的，不必硬填。
            </p>
          ) : null}
          {model.edited_by_user ? (
            <p className={styles.sellingPointsHint}>
              当前是<strong>人工版本</strong>，AI 不会再覆盖它。
            </p>
          ) : null}
          <label style={{ display: "grid", gap: 6 }}>
            <span className={styles.copyReviewColLabel}>
              怎么工作（人话，几句话说清）
            </span>
            <textarea
              onChange={(event) => patch({ how_it_works: event.target.value })}
              placeholder="例：这是一台潜水泵，整机放进水里才能抽水，没有吸水管；泵体出水口接软管直连花洒头。"
              rows={3}
              style={{ resize: "vertical", width: "100%" }}
              value={model.how_it_works}
            />
          </label>
          <label style={{ display: "grid", gap: 6 }}>
            <span className={styles.copyReviewColLabel}>
              硬性条件 · 一行一条（任何「正在工作」的图都必须满足）
            </span>
            <textarea
              onChange={(event) =>
                patch({ hard_constraints: fromLines(event.target.value) })
              }
              placeholder={"泵体必须完全浸没在水中才会出水\n画面里必须看得见水源"}
              rows={4}
              style={{ resize: "vertical", width: "100%" }}
              value={toLines(model.hard_constraints)}
            />
          </label>
          <label style={{ display: "grid", gap: 6 }}>
            <span className={styles.copyReviewColLabel}>
              绝不能出现的画面 · 一行一条
            </span>
            <textarea
              onChange={(event) =>
                patch({ forbidden_depictions: fromLines(event.target.value) })
              }
              placeholder={"泵搁在干燥地面上却在喷水\n画面里完全没有水源却在出水"}
              rows={4}
              style={{ resize: "vertical", width: "100%" }}
              value={toLines(model.forbidden_depictions)}
            />
          </label>
          <label style={{ display: "grid", gap: 6 }}>
            <span className={styles.copyReviewColLabel}>
              买家画像 · 一行一条（决定场景图拍谁、在哪拍）
            </span>
            <textarea
              onChange={(event) =>
                patch({ buyer_personas: fromLines(event.target.value) })
              }
              placeholder={
                "在院子里给孩子洗澡的家长\n给狗冲澡的宠物主\n露营回来冲装备的户外玩家"
              }
              rows={4}
              style={{ resize: "vertical", width: "100%" }}
              value={toLines(model.buyer_personas)}
            />
          </label>
          {notice ? <p className={styles.sellingPointsHint}>{notice}</p> : null}
          {error ? <p className={styles.sellingPointsError}>{error}</p> : null}
        </div>
      )}
    </section>
  );
}
