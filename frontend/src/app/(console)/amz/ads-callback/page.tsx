import type { Metadata } from "next";
import { Suspense } from "react";

import { AdsCallback } from "@/modules/amz/AdsCallback";

export const metadata: Metadata = {
  title: "广告授权",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function AmzAdsCallbackPage() {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <span className="section-index">A</span>
        <div>
          <h1>广告 API 授权</h1>
          <p>亚马逊把授权码送回来了,控制台正在换成令牌、拉广告 profile、存进密钥管理。这一页不用你操作。</p>
        </div>
      </section>
      <Suspense fallback={null}>
        <AdsCallback />
      </Suspense>
    </div>
  );
}
