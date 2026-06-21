"use client";

import { Boxes, LoaderCircle, RotateCcw } from "lucide-react";

import { CapabilityEmptyStateEngine } from "@/components/capability-empty-state";
import { useFrontendCapabilityState } from "@/components/capability-state-provider";
import { useModuleAccess } from "@/components/module-access-provider";

function humanState(value: string) {
  const labels: Record<string, string> = {
    adapter_pending: "配置中",
    allowed: "可用",
    backend_unavailable: "暂不可用",
    forbidden: "无权访问",
    hidden: "已隐藏",
    mock: "预览",
    no_execution: "待配置",
    partial: "部分可用",
  };
  return labels[value] ?? "暂不可用";
}

function humanVisibility(value: string) {
  const labels: Record<string, string> = {
    active: "正常",
    backend_unavailable: "暂不可用",
    hidden: "不可见",
    unknown: "确认中",
    unavailable: "暂不可见",
    visible: "可见",
  };
  return labels[value] ?? "确认中";
}

function humanExecutionMode(value: string) {
  const labels: Record<string, string> = {
    live: "已启用",
    mock: "预览",
    off: "未启用",
    shadow: "试运行",
  };
  return labels[value] ?? "确认中";
}

export function ModuleRegistryProductView() {
  const {
    executionState,
    isLoading: isCapabilityLoading,
    items,
    orgContext,
  } = useFrontendCapabilityState();
  const moduleAccess = useModuleAccess();
  const isLoading = isCapabilityLoading || moduleAccess.isLoading;
  const refresh = moduleAccess.refresh;
  const registryError = moduleAccess.registryError;
  const registryUnavailable = moduleAccess.registryUnavailable;
  const visibleCount = items.filter((item) => item.org_visibility === "visible").length;
  const hiddenCount = items.filter((item) => item.state === "hidden").length;
  const partialCount = items.filter(
    (item) =>
      item.state === "partial" ||
      item.state === "adapter_pending" ||
      item.state === "mock" ||
      item.state === "no_execution" ||
      item.state === "backend_unavailable",
  ).length;
  const allowedCount = items.filter((item) => item.state === "allowed").length;

  if (!isLoading && registryUnavailable && items.length === 0) {
    return (
      <CapabilityEmptyStateEngine
        action={
          <button className="primary-button" onClick={() => void refresh()}>
            <RotateCcw aria-hidden="true" size={17} />
            重试
          </button>
        }
        icon={Boxes}
        reason={registryError?.message ?? "功能区暂时不可用。"}
        required_execution_mode="查看功能区。"
        required_module_state="功能区可用。"
        required_org_state="组织状态正常。"
        required_permission="查看功能区。"
        state="missing_feature"
        title="功能区暂时不可用"
        unlock_condition="稍后重试。"
      />
    );
  }

  return (
    <section className="module-registry-workspace" aria-label="功能区">
      <div className="registry-command-bar">
        <div>
          <span className="eyebrow">功能区</span>
          <h2>工作台功能区</h2>
          <p>
            查看当前工作台可用功能、可见范围和操作准备情况。
          </p>
        </div>
        <button
          className="secondary-button"
          disabled={isLoading}
          onClick={() => void refresh()}
          type="button"
        >
          {isLoading ? (
            <LoaderCircle className="spin" aria-hidden="true" size={17} />
          ) : (
            <RotateCcw aria-hidden="true" size={17} />
          )}
          刷新
        </button>
      </div>

      <div className="capability-summary-grid">
        <div>
          <span>功能区</span>
          <strong>{items.length}</strong>
        </div>
        <div>
          <span>可用</span>
          <strong>{allowedCount}</strong>
        </div>
        <div>
          <span>配置中</span>
          <strong>{partialCount}</strong>
        </div>
        <div>
          <span>已隐藏</span>
          <strong>{hiddenCount}</strong>
        </div>
        <div>
          <span>组织可见</span>
          <strong>{visibleCount}</strong>
        </div>
        <div>
          <span>注册状态</span>
          <strong>
            {moduleAccess.moduleAccessUnknown
              ? "确认中"
              : moduleAccess.items.length}
          </strong>
        </div>
        <div>
          <span>组织状态</span>
          <strong>{humanVisibility(orgContext.state)}</strong>
        </div>
        <div>
          <span>操作状态</span>
          <strong>{humanExecutionMode(executionState.execution_mode)}</strong>
        </div>
      </div>

      {registryUnavailable ? (
        <p className="ops-warning">
          {registryError?.message ??
            "功能区详情暂时不可用，已保留可用导航。"}
        </p>
      ) : null}

      <div className="module-registry-table-scroll">
        <table className="module-registry-table">
          <thead>
            <tr>
              <th>功能区</th>
              <th>状态</th>
              <th>可见范围</th>
              <th>准备情况</th>
              <th>操作状态</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.module_key}>
                <td>
                  <strong>{item.label}</strong>
                  <small>{item.description || "暂无说明"}</small>
                </td>
                <td>
                  <span className={`capability-state-pill ${item.state}`}>
                    {humanState(item.state)}
                  </span>
                  <small>{item.reason}</small>
                </td>
                <td>
                  <strong>{humanVisibility(item.org_visibility)}</strong>
                  <span>{item.required_org_state}</span>
                </td>
                <td>
                  <strong>{humanState(item.state)}</strong>
                  <span>{item.required_module_state}</span>
                </td>
                <td>
                  <strong>{humanExecutionMode(item.execution_mode)}</strong>
                  <span>{item.blocked_reason}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
