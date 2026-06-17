"use client";

import { LoaderCircle, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { CapabilityEmptyState } from "@/components/capability-empty-state";
import { EmptyState } from "@/components/empty-state";
import { ApiError } from "@/lib/api";
import {
  capabilityRecordListRequest,
  type CapabilityRecordListResponse,
} from "@/lib/capability-records-api";

type DisplayField = {
  key: string;
  label: string;
};

type CapabilityRecordListProps = {
  endpoint: string;
  emptyDescription: string;
  emptyTitle: string;
  fields: DisplayField[];
  requiredPermission?: string;
  title: string;
};

function displayValue(value: unknown) {
  if (value === null || value === undefined || value === "") {
    return "Not set";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

export function CapabilityRecordList({
  endpoint,
  emptyDescription,
  emptyTitle,
  fields,
  requiredPermission = "Read permission for this capability.",
  title,
}: CapabilityRecordListProps) {
  const [result, setResult] = useState<CapabilityRecordListResponse | null>(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError("");
    try {
      setResult(await capabilityRecordListRequest(endpoint));
    } catch (requestError) {
      setResult(null);
      setError(
        requestError instanceof ApiError
          ? requestError.message
          : "The backend record API is unavailable.",
      );
    } finally {
      setIsLoading(false);
    }
  }, [endpoint]);

  useEffect(() => {
    void load();
  }, [load]);

  if (isLoading) {
    return (
      <section className="list-state" aria-label={`Loading ${title}`}>
        <LoaderCircle className="spin" aria-hidden="true" size={22} />
        <span>Loading backend records</span>
      </section>
    );
  }

  if (error) {
    return (
      <CapabilityEmptyState
        action={
          <button className="primary-button" onClick={() => void load()}>
            <RotateCcw aria-hidden="true" size={17} />
            Retry
          </button>
        }
        reason={error}
        required_execution_mode="Read-only backend API must be reachable."
        required_module_state="Module route and backend binding must be available."
        required_org_state="Active organization context must be accepted by the backend."
        required_permission={requiredPermission}
        state="backend_unavailable"
        title={`${title} API request failed`}
        unlock_condition={`Restore ${endpoint} and retry the request.`}
      />
    );
  }

  if (!result?.items.length) {
    return (
      <EmptyState
        dataSource={endpoint}
        description={emptyDescription}
        requiredPermission={requiredPermission}
        title={emptyTitle}
      />
    );
  }

  return (
    <section className="record-list" aria-label={title}>
      <div className="record-list-heading">
        <h2>{title}</h2>
        <span>{result.count} records on this page</span>
      </div>
      <div className="record-card-grid">
        {result.items.map((item, index) => (
          <article
            className="record-card"
            key={String(item.id ?? `${endpoint}-${index}`)}
          >
            {fields.map((field) => (
              <div className="record-field" key={field.key}>
                <span>{field.label}</span>
                <strong>{displayValue(item[field.key])}</strong>
              </div>
            ))}
          </article>
        ))}
      </div>
    </section>
  );
}
