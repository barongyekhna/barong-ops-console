"use client";

import { Boxes, LoaderCircle, RotateCcw } from "lucide-react";
import { useMemo, useState } from "react";

import { CapabilityEmptyStateEngine } from "@/components/capability-empty-state";
import { useFrontendCapabilityState } from "@/components/capability-state-provider";
import { useModuleAccess } from "@/components/module-access-provider";

const MODULE_PAGE_LIMIT = 10;
const MODULE_DESCRIPTIONS: Record<string, string> = {
  "admin.agents": "查看已接入的自动化助手。",
  "admin.modules": "查看当前工作台已开放的功能区。",
  "admin.organizations": "管理组织和组织管理员。",
  "admin.permissions": "管理账号访问范围。",
  "admin.settings": "查看系统设置状态。",
  "admin.users": "管理工作台账号和角色。",
  "business.approvals": "处理待审批事项。",
  "business.reviews": "查看审批行为和审核记录。",
  "core.dashboard": "查看工作台首页。",
  "system.errors": "查看系统异常记录。",
  "system.memory_events": "查看运行记录。",
  "system.operation_logs": "查看操作记录。",
};

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

function moduleDescription(moduleKey: string) {
  return MODULE_DESCRIPTIONS[moduleKey] ?? "查看该功能区当前状态。";
}

function moduleReadinessText(value: string) {
  if (value === "allowed") {
    return "可正常使用";
  }
  if (value === "forbidden") {
    return "需要开通权限";
  }
  if (value === "hidden") {
    return "暂未开放";
  }
  if (value === "adapter_pending") {
    return "配置中";
  }
  return "暂不可用";
}

export function ModuleRegistryProductView() {
  const {
    executionState,
    isLoading: isCapabilityLoading,
    items,
    orgContext,
  } = useFrontendCapabilityState();
  const moduleAccess = useModuleAccess();
  const [offset, setOffset] = useState(0);
  const isLoading = isCapabilityLoading || moduleAccess.isLoading;
  const refresh = moduleAccess.refresh;
  const registryError = moduleAccess.registryError;
  const registryUnavailable = moduleAccess.registryUnavailable;
  const productItems = useMemo(
    () =>
      items.filter(
        (item) => item.route_bound && item.sidebar_state !== "hidden",
      ),
    [items],
  );
  const visibleCount = productItems.filter((item) => item.org_visibility === "visible").length;
  const hiddenCount = productItems.filter((item) => item.state === "hidden").length;
  const partialCount = productItems.filter(
    (item) =>
      item.state === "partial" ||
      item.state === "adapter_pending" ||
      item.state === "mock" ||
      item.state === "no_execution" ||
      item.state === "backend_unavailable",
  ).length;
  const allowedCount = productItems.filter((item) => item.state === "allowed").length;
  const pagedItems = productItems.slice(offset, offset + MODULE_PAGE_LIMIT);

  if (!isLoading && registryUnavailable && productItems.length === 0) {
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
          <strong>{productItems.length}</strong>
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
          <span>已登记</span>
          <strong>{moduleAccess.moduleAccessUnknown ? "确认中" : "已同步"}</strong>
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

      {pagedItems.length === 0 && !isLoading ? (
        <div className="ops-empty-state" role="status">
          <strong>暂无数据</strong>
          <span>当前没有可显示的功能区。</span>
        </div>
      ) : (
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
              {pagedItems.map((item) => (
                <tr key={item.module_key}>
                  <td>
                    <strong>{item.label}</strong>
                    <small>{moduleDescription(item.module_key)}</small>
                  </td>
                  <td>
                    <span className={`capability-state-pill ${item.state}`}>
                      {humanState(item.state)}
                    </span>
                    <small>{moduleReadinessText(item.state)}</small>
                  </td>
                  <td>
                    <strong>{humanVisibility(item.org_visibility)}</strong>
                    <span>按当前账号和组织范围显示</span>
                  </td>
                  <td>
                    <strong>{moduleReadinessText(item.state)}</strong>
                    <span>不显示内部配置字段</span>
                  </td>
                  <td>
                    <strong>{humanExecutionMode(item.execution_mode)}</strong>
                    <span>按系统状态自动判断</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="review-pager">
        <button
          className="secondary-button"
          disabled={isLoading || offset === 0}
          onClick={() => setOffset(Math.max(0, offset - MODULE_PAGE_LIMIT))}
          type="button"
        >
          上一页
        </button>
        <span>{Math.floor(offset / MODULE_PAGE_LIMIT) + 1}</span>
        <button
          className="secondary-button"
          disabled={isLoading || offset + MODULE_PAGE_LIMIT >= productItems.length}
          onClick={() => setOffset(offset + MODULE_PAGE_LIMIT)}
          type="button"
        >
          下一页
        </button>
      </div>
    </section>
  );
}
