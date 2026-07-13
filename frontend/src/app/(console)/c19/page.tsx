import type { Metadata } from "next";

import { C19Workspace } from "@/modules/c19/C19Workspace";

export const metadata: Metadata = {
  title: "通讯",
};

export default function C19Page() {
  return <C19Workspace />;
}
