"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { AmzOverview } from "./AmzOverview";
import { AmzWorkspace } from "./AmzWorkspace";
import { ImagesPanel } from "./ImagesPanel";
import styles from "./AmzOverview.module.css";

/** 默认是总览(设计稿);`?tab=manage` 是 A0 的管理面:店铺一表 / 授权 / 种子台账。 */
export function AmzPage() {
  const params = useSearchParams();
  const raw = params.get("tab");
  const tab = raw === "manage" ? "manage" : raw === "images" ? "images" : "overview";
  return (
    <>
      <div className={styles.filters} role="tablist" aria-label="页面">
        <Link aria-selected={tab === "overview"} className={`${styles.chip} ${tab === "overview" ? styles.chipOn : ""}`} href="/amz" role="tab">
          总览
        </Link>
        <Link aria-selected={tab === "images"} className={`${styles.chip} ${tab === "images" ? styles.chipOn : ""}`} href="/amz?tab=images" role="tab">
          图片 · 殷熊的 brief
        </Link>
        <Link aria-selected={tab === "manage"} className={`${styles.chip} ${tab === "manage" ? styles.chipOn : ""}`} href="/amz?tab=manage" role="tab">
          管理 · 店铺 / 授权 / 种子
        </Link>
      </div>
      {tab === "manage" ? <AmzWorkspace /> : tab === "images" ? <ImagesPanel briefId={params.get("brief")} suggestionId={params.get("suggestion")} /> : <AmzOverview />}
    </>
  );
}
