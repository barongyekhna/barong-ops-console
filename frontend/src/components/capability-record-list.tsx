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
    return "未填写";
  }
  if (typeof value === "object") {
    return "已记录";
  }
  return String(value);
}

export function CapabilityRecordList({
  endpoint,
  emptyDescription,
  emptyTitle,
  fields,
  requiredPermission = "当前账号可访问。",
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
          ? "加载失败，请稍后重试。"
          : "加载失败，请稍后重试。",
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
      <section className="list-state" aria-label={`正在加载${title}`}>
        <LoaderCircle className="spin" aria-hidden="true" size={22} />
        <span>正在加载</span>
      </section>
    );
  }

  if (error) {
    return (
      <CapabilityEmptyState
        action={
          <button className="primary-button" onClick={() => void load()}>
            <RotateCcw aria-hidden="true" size={17} />
            重试
          </button>
        }
        reason={error}
        required_execution_mode="可查看。"
        required_module_state="功能区可用。"
        required_org_state="组织状态正常。"
        required_permission={requiredPermission}
        state="missing_feature"
        title="加载失败，请稍后重试"
        unlock_condition="稍后重试。"
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
        <span>本页 {result.count} 条记录</span>
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
