"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * 产品保护区画笔。
 *
 * 涂过的地方 = 锁死，AI 不许碰；没涂的 = 交给 AI 重绘。
 *
 * 2026-08-03 实测的关键结论（决定了这里的交互取向）：
 * - **刷少了**（产品露在保护区外）那部分会被当背景重画 —— 花洒头就这么变成
 *   银色金属圈，整张图作废；
 * - **刷胖了**（涂到产品外面）只是产品周围留一圈原背景残留，盯着才看得出。
 *
 * 两种错的代价差一个量级，所以文案和默认笔刷都往「宁可多刷」偏。
 */

const MIN_COVERAGE = 0.12; // 低于这个多半是漏了大块产品

export type MaskBrushHandle = {
  /** 导出 PNG（不透明处=保护区）。空白时返回 null。 */
  toPngBase64: () => string | null;
};

export function MaskBrush({
  imageUrl,
  initialMaskUrl,
  onDirtyChange,
  onReady,
}: {
  imageUrl: string;
  /** 已保存过的蒙版，回填后可在其上继续修改。 */
  initialMaskUrl?: string | null;
  onDirtyChange?: (dirty: boolean) => void;
  onReady?: (handle: MaskBrushHandle) => void;
}) {
  const imgRef = useRef<HTMLImageElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const painting = useRef(false);
  const lastPoint = useRef<{ x: number; y: number } | null>(null);
  const history = useRef<string[]>([]);

  const [mode, setMode] = useState<"paint" | "erase">("paint");
  const [size, setSize] = useState(34);
  const [coverage, setCoverage] = useState(0);

  const measure = useCallback(() => {
    const cv = canvasRef.current;
    if (!cv || !cv.width) return;
    const ctx = cv.getContext("2d", { willReadFrequently: true });
    if (!ctx) return;
    const { data } = ctx.getImageData(0, 0, cv.width, cv.height);
    let painted = 0;
    let sampled = 0;
    for (let i = 3; i < data.length; i += 40) {
      sampled += 1;
      if (data[i] > 8) painted += 1;
    }
    setCoverage(sampled ? painted / sampled : 0);
  }, []);

  const fit = useCallback(() => {
    const img = imgRef.current;
    const cv = canvasRef.current;
    if (!img || !cv) return;
    const w = img.clientWidth;
    const h = img.clientHeight;
    if (!w || !h) return;
    const ctx = cv.getContext("2d", { willReadFrequently: true });
    if (!ctx) return;
    // 尺寸变化会清空画布，先把已有笔迹抢救出来再放回去
    const snapshot =
      cv.width && cv.height ? cv.toDataURL() : null;
    cv.width = w;
    cv.height = h;
    if (snapshot) {
      const restore = new Image();
      restore.onload = () => {
        ctx.drawImage(restore, 0, 0, w, h);
        measure();
      };
      restore.src = snapshot;
    } else {
      measure();
    }
  }, [measure]);

  useEffect(() => {
    const img = imgRef.current;
    if (!img) return;
    if (img.complete) fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, [fit]);

  // 回填已保存的蒙版
  useEffect(() => {
    if (!initialMaskUrl) return;
    const cv = canvasRef.current;
    if (!cv) return;
    const prior = new Image();
    prior.crossOrigin = "anonymous";
    prior.onload = () => {
      const ctx = cv.getContext("2d", { willReadFrequently: true });
      if (!ctx || !cv.width) return;
      ctx.drawImage(prior, 0, 0, cv.width, cv.height);
      measure();
    };
    prior.src = initialMaskUrl;
  }, [initialMaskUrl, measure]);

  useEffect(() => {
    onReady?.({
      toPngBase64: () => {
        const cv = canvasRef.current;
        const img = imgRef.current;
        if (!cv || !cv.width || !img) return null;

        // 1) 放大回原图尺寸 —— 画布是按**显示尺寸**建的（~520px），而
        //    image edit 接口要求蒙版与原图逐像素同尺寸，尺寸不符直接 400。
        const outW = img.naturalWidth || cv.width;
        const outH = img.naturalHeight || cv.height;
        const out = document.createElement("canvas");
        out.width = outW;
        out.height = outH;
        const octx = out.getContext("2d", { willReadFrequently: true });
        if (!octx) return null;
        octx.drawImage(cv, 0, 0, outW, outH);

        // 2) alpha 二值化 —— 画笔是半透明的（看得见底图才好涂），但蒙版语义
        //    是「不透明=锁死、透明=交给模型」，留着中间值等于让保护区半生不熟。
        const image = octx.getImageData(0, 0, outW, outH);
        const { data } = image;
        let any = false;
        for (let i = 3; i < data.length; i += 4) {
          if (data[i] > 24) {
            data[i] = 255;
            any = true;
          } else {
            data[i] = 0;
          }
        }
        if (!any) return null;
        octx.putImageData(image, 0, 0);
        return out.toDataURL("image/png");
      },
    });
  }, [onReady]);

  function pointFrom(event: React.PointerEvent<HTMLCanvasElement>) {
    const cv = canvasRef.current;
    if (!cv) return { x: 0, y: 0 };
    const rect = cv.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  }

  function drawTo(point: { x: number; y: number }) {
    const cv = canvasRef.current;
    const ctx = cv?.getContext("2d", { willReadFrequently: true });
    if (!cv || !ctx) return;
    ctx.globalCompositeOperation =
      mode === "paint" ? "source-over" : "destination-out";
    ctx.strokeStyle = "rgba(159,211,86,.55)";
    ctx.fillStyle = "rgba(159,211,86,.55)";
    ctx.lineWidth = size;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    const from = lastPoint.current;
    if (from) {
      ctx.moveTo(from.x, from.y);
      ctx.lineTo(point.x, point.y);
      ctx.stroke();
    } else {
      ctx.arc(point.x, point.y, size / 2, 0, Math.PI * 2);
      ctx.fill();
    }
    lastPoint.current = point;
  }

  function snapshot() {
    const cv = canvasRef.current;
    if (!cv || !cv.width) return;
    history.current.push(cv.toDataURL());
    if (history.current.length > 12) history.current.shift();
  }

  function undo() {
    const prev = history.current.pop();
    const cv = canvasRef.current;
    const ctx = cv?.getContext("2d", { willReadFrequently: true });
    if (!cv || !ctx) return;
    if (!prev) {
      ctx.clearRect(0, 0, cv.width, cv.height);
      measure();
      return;
    }
    const restore = new Image();
    restore.onload = () => {
      ctx.globalCompositeOperation = "source-over";
      ctx.clearRect(0, 0, cv.width, cv.height);
      ctx.drawImage(restore, 0, 0, cv.width, cv.height);
      measure();
    };
    restore.src = prev;
  }

  function clearAll() {
    const cv = canvasRef.current;
    const ctx = cv?.getContext("2d", { willReadFrequently: true });
    if (!cv || !ctx) return;
    snapshot();
    ctx.clearRect(0, 0, cv.width, cv.height);
    measure();
    onDirtyChange?.(true);
  }

  const enough = coverage >= MIN_COVERAGE;

  return (
    <div className="k-maskbrush">
      <div className="k-maskbrush-bar">
        <button
          className={mode === "paint" ? "secondary-button is-on" : "secondary-button"}
          onClick={() => setMode("paint")}
          type="button"
        >
          涂抹
        </button>
        <button
          className={mode === "erase" ? "secondary-button is-on" : "secondary-button"}
          onClick={() => setMode("erase")}
          type="button"
        >
          擦除
        </button>
        <label className="k-maskbrush-size">
          笔刷
          <input
            aria-label="笔刷大小"
            max={70}
            min={10}
            onChange={(event) => setSize(Number(event.target.value))}
            type="range"
            value={size}
          />
        </label>
        <button className="secondary-button" onClick={undo} type="button">
          撤销
        </button>
        <button className="secondary-button" onClick={clearAll} type="button">
          清空
        </button>
        <span className={enough ? "k-maskbrush-cov is-ok" : "k-maskbrush-cov"}>
          已覆盖 {(coverage * 100).toFixed(1)}%
        </span>
      </div>

      <div className="k-maskbrush-stage">
        <div className="k-maskbrush-holder">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            alt="作图底图"
            onLoad={fit}
            ref={imgRef}
            src={imageUrl}
          />
          <canvas
            onPointerDown={(event) => {
              event.currentTarget.setPointerCapture(event.pointerId);
              snapshot();
              painting.current = true;
              lastPoint.current = null;
              drawTo(pointFrom(event));
              onDirtyChange?.(true);
            }}
            onPointerMove={(event) => {
              if (!painting.current) return;
              drawTo(pointFrom(event));
            }}
            onPointerUp={() => {
              painting.current = false;
              lastPoint.current = null;
              measure();
            }}
            onPointerCancel={() => {
              painting.current = false;
              lastPoint.current = null;
              measure();
            }}
            ref={canvasRef}
          />
        </div>
      </div>

      <p className="k-maskbrush-hint">
        把<strong>泵体、软管、花洒头全部涂满</strong>——
        宁可往外多刷一圈，也别让产品露在外面。露出来的部分 AI 会当背景重画，
        涂多了只是产品周围留一点原背景，几乎看不出来。
        {!enough ? <em>（通常要涂到 12% 以上）</em> : null}
      </p>
    </div>
  );
}
