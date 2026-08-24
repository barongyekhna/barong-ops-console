const UI_TEXT_LABELS: Record<string, string> = {
  "API Key Management": "API密钥管理",
  "Activity feed": "活动记录",
  "Active Modules": "可用模块",
  "Approval Audit": "审批审计",
  Approvals: "审批",
  Dashboard: "控制台",
  Errors: "异常记录",
  Executions: "执行记录",
  "Foundation Demo": "内部演示",
  "Live workspace updates": "工作台实时更新",
  "Memory Events": "运行记录",
  "Module Control": "模块控制",
  Modules: "模块",
  "Operation Logs": "操作记录",
  Organizations: "组织",
  "Pending Reviews": "待处理审核",
  Permissions: "权限管理",
  "Product Knowledge": "产品知识库",
  "Success Rate": "成功率",
  Users: "用户管理",
  "User Management": "用户管理",
};

const MODULE_DISPLAY_LABELS: Record<string, string> = {
  "admin.agents": "自动化助手",
  "admin.key_management": "API密钥管理",
  "admin.modules": "模块控制",
  "admin.organizations": "组织管理",
  "admin.permissions": "权限管理",
  "admin.settings": "设置",
  "admin.users": "用户管理",
  "business.approvals": "审批",
  "business.reviews": "审批审计",
  "core.dashboard": "控制台",
  "core.vpn": "VPN",
  "cs.customer_service": "客服中心",
  "experimental.foundation_demo": "内部演示",
  "i.image_system": "I系列图片系统",
  "integration.n8n_test_bridge": "外部流程测试桥",
  "k.product_knowledge": "K系列产品知识库",
  "p.upload": "P系列自动化上传",
  "r.analysis": "R-A 产品分析中心",
  "r.warehouse": "R-W 产品数据仓库",
  "system.errors": "异常记录",
  "system.memory_events": "运行记录",
  "system.operation_logs": "操作记录",
};

const K_PROVIDER_LABELS: Record<string, string> = {
  chatgpt: "ChatGPT",
  claude: "Claude",
  claude_opus: "Claude",
  deepseek: "DeepSeek",
  serp: "SERP",
};

const K_RAW_CODE_PATTERN = /\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+){1,}\b/;
const K_KEY_ERROR_CODES = new Set([
  "API_KEY_BINDING_MISSING",
  "API_KEY_INJECTION_FAILED",
]);
const K_TECHNICAL_MESSAGES = new Set([
  "not found",
  "not found.",
  "service unavailable",
  "service unavailable.",
]);

type KBackendErrorInput = {
  detail?: unknown;
  fallback?: string;
  message?: string | null;
  path?: string | null;
  status?: number | null;
};

function stringValue(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : null;
}

function collectKnownProviderAliases(values: unknown[]): string[] {
  const aliases = new Set<string>();

  for (const value of values) {
    if (Array.isArray(value)) {
      for (const nested of collectKnownProviderAliases(value)) {
        aliases.add(nested);
      }
      continue;
    }

    const normalized = stringValue(value).toLowerCase();
    if (!normalized) {
      continue;
    }

    if (normalized.includes("claude_opus")) {
      aliases.add("claude_opus");
    } else if (normalized.includes("chatgpt")) {
      aliases.add("chatgpt");
    } else if (normalized.includes("deepseek")) {
      aliases.add("deepseek");
    } else if (normalized.includes("serp")) {
      aliases.add("serp");
    }
  }

  return [...aliases];
}

function providerAliasesFromPath(path: string) {
  const normalized = path.toLowerCase();

  if (normalized.includes("/serp/") || normalized.includes("keyword-research")) {
    return ["serp"];
  }
  if (
    normalized.includes("/enrich/deepseek") ||
    normalized.includes("/selling-points/")
  ) {
    return ["deepseek"];
  }
  if (normalized.includes("/workflow/start")) {
    return ["serp", "chatgpt", "claude_opus", "deepseek"];
  }

  return [];
}

function providerAliasesFromDetail(detail: unknown, path: string) {
  const record = objectValue(detail);
  const details = objectValue(record?.details);
  const aliases = collectKnownProviderAliases([
    record?.missing,
    record?.provider,
    record?.key_alias,
    record?.required_key_alias,
    record?.step,
    details?.missing,
    details?.provider,
    details?.key_alias,
    details?.required_key_alias,
    details?.step,
  ]);

  return aliases.length > 0 ? aliases : providerAliasesFromPath(path);
}

function kApiKeyMessage(aliases: string[]) {
  const labels = (aliases.length > 0
    ? aliases
    : ["serp", "chatgpt", "claude_opus", "deepseek"]
  ).map((alias) => K_PROVIDER_LABELS[alias] ?? alias);
  const uniqueLabels = [...new Set(labels)];

  return `API Key 未生效，请检查密钥管理中的 ${uniqueLabels.join(" / ")} 绑定。`;
}

export function translateKBackendError({
  detail,
  fallback = "K 流程请求未完成，请稍后重试。",
  message,
  path,
  status,
}: KBackendErrorInput) {
  const record = objectValue(detail);
  const code = stringValue(record?.code);
  const reason = stringValue(record?.reason);
  const rawMessage = stringValue(message || record?.message);
  const normalizedMessage = rawMessage.toLowerCase();
  const normalizedPath = stringValue(path);

  if (
    code === "SERP_RESULT_REQUIRED_FOR_RETRY" ||
    normalizedMessage.includes("serp result is required before retrying")
  ) {
    return "关键词调研尚未开始，请先启动关键词调研。";
  }

  if (
    code === "CHATGPT_RESULT_REQUIRED_FOR_RETRY" ||
    normalizedMessage.includes("chatgpt result is required before retrying")
  ) {
    return "ChatGPT 初筛尚未完成，请先完成关键词调研后再重试。";
  }

  if (
    code === "CLAUDE_RESULT_REQUIRED_FOR_RETRY" ||
    normalizedMessage.includes("claude result is required before retrying")
  ) {
    return "Claude 终筛尚未完成，请先完成 ChatGPT 初筛后再重试。";
  }

  if (
    K_KEY_ERROR_CODES.has(code) ||
    reason === "missing_key" ||
    reason === "key_resolution_failed" ||
    normalizedMessage.includes("api key binding") ||
    normalizedMessage.includes("usable api key binding") ||
    normalizedMessage.includes("api key could not be resolved")
  ) {
    return kApiKeyMessage(providerAliasesFromDetail(record, normalizedPath));
  }

  if (code === "K_WORKFLOW_START_UNAVAILABLE") {
    return "关键词调研启动暂未完成，请刷新流程状态后重试。";
  }

  if (code === "WORKFLOW_ROLLED_BACK") {
    return "流程已回退，请刷新流程状态后从当前步骤继续。";
  }

  if (code === "RISK_REVIEW_REQUIRED") {
    return "请先完成风险词人工审核。";
  }

  if (code === "PRODUCT_CONTEXT_MISSING") {
    return "未找到产品上下文，请先选择有效产品。";
  }

  if (code === "PRODUCT_CONTEXT_INCOMPLETE") {
    return "产品信息不完整，无法启动 SERP 搜索，请补齐产品关键词和目标市场。";
  }

  if (code === "SERP_ORGANIC_RESULTS_MISSING") {
    return "SERP 返回结果不完整，请稍后重新启动关键词调研。";
  }

  if (status === 503 && normalizedMessage.includes("k module execution")) {
    return kApiKeyMessage(providerAliasesFromDetail(record, normalizedPath));
  }

  if (status === 503 && normalizedPath.includes("/workflow/start")) {
    return "关键词调研启动暂未完成，请刷新流程状态后重试。";
  }

  if (
    rawMessage &&
    !K_RAW_CODE_PATTERN.test(rawMessage) &&
    !K_TECHNICAL_MESSAGES.has(normalizedMessage)
  ) {
    return rawMessage;
  }

  return fallback;
}

// 通讯(C19)后端错误码 → 给人看的中文。后端 detail 一律英文/工程话,
// 这里按稳定的 code 翻成人话;拿不到 code 的(identity_social_router 走 str(exc))
// 靠 api.ts 的通用英文兜底,绝不把原始英文/异常文本呈现给用户。
const C19_ERROR_MESSAGES: Record<string, string> = {
  c19_access_denied: "当前账号无权进行此操作。",
  c19_conversation_unavailable: "该会话暂时打不开，请稍后再试。",
  c19_invalid_cursor: "聊天记录有更新，请刷新后再试。",
  c19_message_deleted: "原消息已被删除，无法继续。",
  c19_message_idempotency_conflict: "这条消息似乎已经发送，请刷新后查看。",
  c19_message_position_conflict: "消息顺序有更新，请刷新后再试。",
  c19_message_rejected: "消息没能发出去，请稍后重试。",
  c19_moment_audience_invalid: "请选择有效的可见范围。",
  c19_moment_deleted: "这条动态已不可用。",
  c19_moment_unavailable: "这条动态已不可用。",
  c19_moment_idempotency_conflict: "这条动态似乎已经发布，请刷新后查看。",
  c19_moment_rejected: "动态没能发布，请稍后重试。",
  c19_moment_store_error: "动态服务暂时不可用，请稍后再试。",
  c19_moment_store_invalid_response: "动态服务暂时不可用，请稍后再试。",
  c19_moment_store_unavailable: "动态服务暂时不可用，请稍后再试。",
  c19_asset_binding_conflict: "这张图片已绑定到其它消息，请重新选择。",
  c19_asset_idempotency_conflict: "这张图片似乎已经发送，请刷新后查看。",
  c19_asset_quota_exceeded: "今天的图片发送次数已用完，请明天再试。",
  c19_asset_store_error: "图片服务暂时不可用，请稍后再试。",
  c19_asset_store_invalid_response: "图片服务暂时不可用，请稍后再试。",
  c19_asset_store_unavailable: "图片服务暂时不可用，请稍后再试。",
  c19_asset_transfer_denied: "无权转存这张图片。",
  c19_asset_transfer_unavailable: "图片转存暂时不可用，请稍后再试。",
  c19_asset_unavailable: "这张图片暂时无法访问。",
  c19_rate_limit_contention: "系统有点忙，请稍后再试。",
  c19_rate_limit_unavailable: "系统有点忙，请稍后再试。",
  c19_rate_limited: "操作太频繁，请稍后再试。",
  c19_record_store_error: "聊天服务暂时不可用，请稍后再试。",
  c19_record_store_invalid_response: "聊天服务暂时不可用，请稍后再试。",
  c19_record_store_unavailable: "聊天服务暂时不可用，请稍后再试。",
};

type C19BackendErrorInput = {
  detail?: unknown;
  fallback?: string;
  message?: string | null;
  status?: number | null;
};

export function translateC19BackendError({
  detail,
  fallback = "通讯服务暂时不可用，请稍后再试。",
  message,
  status,
}: C19BackendErrorInput) {
  const record = objectValue(detail);
  const code = stringValue(record?.code);
  if (code && C19_ERROR_MESSAGES[code]) {
    return C19_ERROR_MESSAGES[code];
  }

  const rawMessage = stringValue(message || record?.message);
  // 已是中文(含 CJK)且不是原始码 → 直接用;否则(英文/工程话/异常文本)一律兜底。
  if (rawMessage && /[一-鿿]/.test(rawMessage)) {
    return rawMessage;
  }

  if (status === 429) {
    return "操作太频繁，请稍后再试。";
  }
  return fallback;
}

export function translateUiText(value: string | null | undefined) {
  const text = value?.trim() ?? "";
  if (!text) {
    return "";
  }
  return UI_TEXT_LABELS[text] ?? text;
}

export function getModuleDisplayName(
  moduleKey: string | null | undefined,
  fallback?: string | null,
) {
  const normalizedKey = moduleKey?.trim() ?? "";
  if (normalizedKey && MODULE_DISPLAY_LABELS[normalizedKey]) {
    return MODULE_DISPLAY_LABELS[normalizedKey];
  }

  const translatedFallback = translateUiText(fallback);
  return translatedFallback || normalizedKey || "未命名模块";
}
