"use client";

import { LoaderCircle, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/empty-state";
import { ApiError } from "@/lib/api";
import {
  foundationListRequest,
  type FoundationListResponse,
} from "@/lib/foundation-api";

type DisplayField = {
  key: string;
  label: string;
};

type FoundationListProps = {
  endpoint: string;
  emptyDescription: string;
  emptyTitle: string;
  fields: DisplayField[];
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

export function FoundationList({
  endpoint,
  emptyDescription,
  emptyTitle,
  fields,
  title,
}: FoundationListProps) {
  const [result, setResult] = useState<FoundationListResponse | null>(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError("");
    try {
      setResult(await foundationListRequest(endpoint));
    } catch (requestError) {
      setResult(null);
      setError(
        requestError instanceof ApiError
          ? requestError.message
          : "The foundation API is unavailable.",
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
        <span>Loading foundation records</span>
      </section>
    );
  }

  if (error) {
    return (
      <section className="list-state list-error" role="alert">
        <div>
          <h2>API request failed</h2>
          <p>{error}</p>
        </div>
        <button className="primary-button" onClick={() => void load()}>
          <RotateCcw aria-hidden="true" size={17} />
          Retry
        </button>
      </section>
    );
  }

  if (!result?.items.length) {
    return (
      <EmptyState
        description={emptyDescription}
        title={emptyTitle}
      />
    );
  }

  return (
    <section className="foundation-list" aria-label={title}>
      <div className="foundation-list-heading">
        <h2>{title}</h2>
        <span>{result.count} records on this page</span>
      </div>
      <div className="foundation-card-grid">
        {result.items.map((item, index) => (
          <article
            className="foundation-card"
            key={String(item.id ?? `${endpoint}-${index}`)}
          >
            {fields.map((field) => (
              <div className="foundation-field" key={field.key}>
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
