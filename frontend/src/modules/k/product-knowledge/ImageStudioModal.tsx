"use client";

import { LoaderCircle, Save } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { getImagePlates, savePlateMask, type ImagePlate } from "./api";
import { MaskBrush, type MaskBrushHandle } from "./MaskBrush";
import { OperatingModelPanel } from "./OperatingModelPanel";
import { RenderImagesPanel } from "./RenderImagesPanel";
import { OverlayModal } from "@/components/overlay-modal";

/**
 * 作图工作台。
 *
 * 2026-08-03 用户拍板：K 产品详情页已经够长，整套作图操作收进这个浮窗，
 * 详情页只留一个入口按钮。
 *
 * 三步对应换路后的新管线：先圈出产品（锁住实拍像素，AI 只画背景）→
 * 确认产品怎么工作（物理约束）→ 出图挑图。
 */

const POSE_LABEL: Record<string, string> = {
  in_use: "正在使用",
  product_only: "产品展示",
  accessories: "配件平铺",
  detail: "细节特写",
};

const POSE_NOTE: Record<string, string> = {
  in_use: "场景图会拿它当底板——软管展开、连着花洒头的姿态只能靠实拍",
  product_only: "白底主图、信息图的底板",
  accessories: "配件图的底板",
  detail: "细节特写图的底板",
};

type Step = "mask" | "howto" | "render";

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

export function ImageStudioModal({
  productId,
  hasBrief,
  onClose,
  onSaved,
}: {
  productId: string;
  hasBrief: boolean;
  onClose: () => void;
  onSaved?: () => void;
}) {
  const [step, setStep] = useState<Step>("mask");
  const [plates, setPlates] = useState<ImagePlate[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [handle, setHandle] = useState<MaskBrushHandle | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await getImagePlates(productId);
      setPlates(data.items);
      setActiveId((current) => current ?? data.items[0]?.asset_id ?? null);
    } catch (loadError) {
      setError(errorMessage(loadError, "读取底图失败。"));
    } finally {
      setLoading(false);
    }
  }, [productId]);

  useEffect(() => {
    void load();
  }, [load]);

  const active = useMemo(
    () => plates.find((plate) => plate.asset_id === activeId) ?? null,
    [plates, activeId],
  );

  async function saveMask() {
    if (!active || !handle) return;
    const png = handle.toPngBase64();
    if (!png) {
      setError("还没涂任何东西——先把产品刷一遍。");
      return;
    }
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await savePlateMask(productId, active.asset_id, png);
      setDirty(false);
      setNotice("已保存。这张底图的所有场景图都会用它锁住产品。");
      await load();
    } catch (saveError) {
      setError(errorMessage(saveError, "保存蒙版失败。"));
    } finally {
      setSaving(false);
    }
  }

  const maskedCount = plates.filter((plate) => plate.has_mask).length;

  return (
    <OverlayModal label="作图工作台" onClose={onClose} width="min(1120px, 100%)">
      <div className="k-studio">
        <header className="k-studio-head">
          <div>
            <span className="k-studio-eyebrow">作图工作台</span>
            <h2>一次性作图</h2>
          </div>
          <nav className="k-studio-steps">
            <button
              className={step === "mask" ? "is-on" : ""}
              onClick={() => setStep("mask")}
              type="button"
            >
              1 · 圈产品
              <em>{maskedCount}/{plates.length}</em>
            </button>
            <button
              className={step === "howto" ? "is-on" : ""}
              onClick={() => setStep("howto")}
              type="button"
            >
              2 · 怎么工作
            </button>
            <button
              className={step === "render" ? "is-on" : ""}
              onClick={() => setStep("render")}
              type="button"
            >
              3 · 出图
            </button>
          </nav>
        </header>

        {error ? <p className="k-studio-error">{error}</p> : null}
        {notice ? <p className="k-studio-notice">{notice}</p> : null}

        {step === "mask" ? (
          <div className="k-studio-body">
            {loading ? (
              <p className="k-studio-muted">读取底图中…</p>
            ) : plates.length === 0 ? (
              <p className="k-studio-muted">
                还没有可用底图。先跑一次「生成作图指令」——它会看参考图，
                判断哪几张能当底板。
              </p>
            ) : (
              <>
                <div className="k-studio-plates">
                  {plates.map((plate) => (
                    <button
                      className={
                        plate.asset_id === activeId
                          ? "k-studio-plate is-on"
                          : "k-studio-plate"
                      }
                      key={plate.asset_id}
                      onClick={() => {
                        setActiveId(plate.asset_id);
                        setDirty(false);
                        setNotice("");
                      }}
                      type="button"
                    >
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img alt="" loading="lazy" src={plate.thumbnail_url} />
                      <span className="k-studio-plate-meta">
                        <b>{POSE_LABEL[plate.pose] ?? plate.pose}</b>
                        <em className={plate.has_mask ? "is-done" : ""}>
                          {plate.has_mask ? "已圈" : "待圈"}
                        </em>
                      </span>
                    </button>
                  ))}
                </div>

                {active ? (
                  <>
                    <p className="k-studio-muted">
                      {POSE_NOTE[active.pose] ?? ""}
                    </p>
                    <MaskBrush
                      imageUrl={active.preview_url}
                      initialMaskUrl={
                        active.mask_asset_id
                          ? `/api/backend/k/media/${active.mask_asset_id}/file`
                          : null
                      }
                      key={active.asset_id}
                      onDirtyChange={setDirty}
                      onReady={setHandle}
                    />
                    <div className="k-studio-actions">
                      <button
                        className="secondary-button"
                        disabled={saving || !dirty}
                        onClick={() => void saveMask()}
                        type="button"
                      >
                        {saving ? (
                          <LoaderCircle aria-hidden="true" className="spin" size={15} />
                        ) : (
                          <Save aria-hidden="true" size={15} />
                        )}
                        保存这张的产品区
                      </button>
                      <button
                        className="secondary-button"
                        onClick={() => setStep("howto")}
                        type="button"
                      >
                        下一步
                      </button>
                    </div>
                  </>
                ) : null}
              </>
            )}
          </div>
        ) : null}

        {step === "howto" ? (
          <div className="k-studio-body">
            <OperatingModelPanel productId={productId} />
            <div className="k-studio-actions">
              <button
                className="secondary-button"
                onClick={() => setStep("render")}
                type="button"
              >
                下一步：出图
              </button>
            </div>
          </div>
        ) : null}

        {step === "render" ? (
          <div className="k-studio-body">
            {plates.length > 0 && maskedCount === 0 ? (
              <p className="k-studio-warn">
                还没有圈过任何底图。现在出图会让 AI 重画产品本体，
                可能出现变形、配件画错。建议先回第 1 步圈一遍。
              </p>
            ) : null}
            <RenderImagesPanel
              hasBrief={hasBrief}
              onSaved={onSaved}
              productId={productId}
            />
          </div>
        ) : null}
      </div>
    </OverlayModal>
  );
}
