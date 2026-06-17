import type { Metadata } from "next";

import { OperationLogsCenter } from "@/components/operation-logs-center";

export const metadata: Metadata = {
  title: "Logs",
};

export default function OperationLogsPage() {
  return <OperationLogsCenter />;
}
