import type { Metadata } from "next";

import { ImageSystemWorkspace } from "@/modules/i/image-system/ImageSystemWorkspace";

export const metadata: Metadata = {
  title: "I系列图片系统",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function ImageSystemPage() {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <span className="section-index">I</span>
        <h1>AI 作图模块</h1>
        <p>
          生成和编辑图片分开处理；直接进入时保存到 I 媒体库，从 K 进入时保存回对应产品变体。
        </p>
      </section>

      <ImageSystemWorkspace />
    </div>
  );
}
