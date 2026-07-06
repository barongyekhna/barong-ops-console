import type { Metadata } from "next";

import { ImageSystemWorkspace } from "@/modules/i/image-system/ImageSystemWorkspace";

export const metadata: Metadata = {
  title: "I系列图片系统",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function ImageSystemPage() {
  return <ImageSystemWorkspace />;
}
