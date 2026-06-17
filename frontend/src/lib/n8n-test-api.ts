import { apiRequest } from "@/lib/api";

export type N8nTestSnapshot = {
  test_mode: true;
  job: {
    job_id: string;
    run_type: "n8n_test_bridge";
    status: string;
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

export function latestN8nTest() {
  return apiRequest<N8nTestSnapshot>("/n8n-test/latest", {
    method: "GET",
  });
}
