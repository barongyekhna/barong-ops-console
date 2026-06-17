import type { Metadata } from "next";

import { C17ObservabilityCenter } from "@/components/c17-observability-center";

export const metadata: Metadata = {
  title: "Operation Logs",
};

export default function OperationLogsPage() {
  return <C17ObservabilityCenter />;
}
