import type { Metadata } from "next";

import { C19Workspace } from "@/modules/c19/C19Workspace";

export const metadata: Metadata = {
  title: "C19 通讯与朋友圈",
};

export default function C19Page() {
  return <C19Workspace />;
}
