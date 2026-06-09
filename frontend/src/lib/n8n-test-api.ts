import { apiRequest } from "@/lib/api";
import { readAccessToken } from "@/lib/auth";

export type N8nTestSnapshot = {
  test_mode: true;
  job: {
    job_id: string;
    run_type: "n8n_test_bridge";
    status:
      | "pending"
      | "running"
      | "waiting_callback"
      | "failed"
      | "cancelled"
      | "completed_demo";
  };
  latest_event: {
    event_type: string;
    to_status: string | null;
  } | null;
  artifact: {
    title: string;
  } | null;
  review: {
    status: string;
  } | null;
  memory_event: {
    summary: string;
  } | null;
  error: {
    error_code: string;
    message: string;
  } | null;
  operation_log_count: number;
};

export function runN8nTest() {
  return apiRequest<N8nTestSnapshot>("/n8n-test/run", {
    accessToken: readAccessToken(),
    method: "POST",
  });
}

export function latestN8nTest() {
  return apiRequest<N8nTestSnapshot>("/n8n-test/latest", {
    accessToken: readAccessToken(),
    method: "GET",
  });
}
