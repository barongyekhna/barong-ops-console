import type { Metadata } from "next";

import { OperationLogsCenter } from "@/components/operation-logs-center";

export const metadata: Metadata = {
  title: "操作记录",
};

export default function OperationLogsPage() {
  return <OperationLogsCenter />;
}
