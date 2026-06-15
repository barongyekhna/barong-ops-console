import { apiRequest } from "@/lib/api";

export type FoundationDemoSnapshot = {
  job: {
    job_id: string;
    job_type: "foundation_demo";
    status: string;
  };
  events_count: number;
  artifact: {
    title: string;
  } | null;
  review: {
    status: string;
  } | null;
  memory_event: {
    summary: string;
  } | null;
  operation_log_count: number;
};

export function runFoundationDemo() {
  return apiRequest<FoundationDemoSnapshot>("/foundation-demo/run", {
    method: "POST",
  });
}

export function latestFoundationDemo() {
  return apiRequest<FoundationDemoSnapshot>("/foundation-demo/latest", {
    method: "GET",
  });
}
