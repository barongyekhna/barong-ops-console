"use client";

export type ApiKeyType =
  | "custom"
  | "serp"
  | "openai"
  | "chatgpt"
  | "claude_opus"
  | "deepseek"
  | "n8n"
  | "keepa"
  | "alibaba1688"
  | "rainforest"
  | "google_ads";

export type ApiKeyTypeOption = {
  type: ApiKeyType;
  label: string;
  description: string;
  defaultUrl: string;
  defaultAlias: string;
  runtimeStatus?: "pending_basic_review";
};

export const KEY_TYPE_OPTIONS: ApiKeyTypeOption[] = [
  {
    type: "deepseek",
    label: "DeepSeek",
    description: "DeepSeek AI API",
    defaultUrl: "https://api.deepseek.com",
    defaultAlias: "deepseek",
  },
  {
    type: "openai",
    label: "OpenAI",
    description: "OpenAI-compatible AI API for K, I, and R-A modules",
    defaultUrl: "https://api.openai.com/v1",
    defaultAlias: "chatgpt",
  },
  {
    type: "serp",
    label: "Serper",
    description: "Google search and supplier discovery API",
    defaultUrl: "https://google.serper.dev",
    defaultAlias: "serp",
  },
  {
    type: "keepa",
    label: "Keepa API",
    description: "Amazon market intelligence data API",
    defaultUrl: "https://api.keepa.com",
    defaultAlias: "keepa",
  },
  {
    type: "alibaba1688",
    label: "1688 官方 API",
    description: "1688 开放平台 AppKey / AppSecret / Access Token",
    defaultUrl: "https://open.1688.com",
    defaultAlias: "alibaba1688",
  },
  {
    type: "rainforest",
    label: "Rainforest API",
    description: "亚马逊页一实时数据(R-A 竞争指标:评论墙 / 品牌份额 / 新品占比)",
    defaultUrl: "https://api.rainforestapi.com",
    defaultAlias: "rainforest",
  },
  {
    type: "google_ads",
    label: "Google Ads API",
    description: "Google Ads Keyword Planner 搜索量 / CPC / SEO 需求信号；Basic 审核通过前仅绑定不启用",
    defaultUrl: "https://googleads.googleapis.com",
    defaultAlias: "google_ads",
    runtimeStatus: "pending_basic_review",
  },
  {
    type: "custom",
    label: "自定义",
    description: "Custom backend-injected API key",
    defaultUrl: "",
    defaultAlias: "default",
  },
];

const LOOKUP_KEY_TYPE_OPTIONS: ApiKeyTypeOption[] = [
  ...KEY_TYPE_OPTIONS,
  {
    type: "chatgpt",
    label: "ChatGPT / 4sapi",
    description: "ChatGPT-compatible AI API for K, I, and R-A modules",
    defaultUrl: "https://api.openai.com/v1",
    defaultAlias: "chatgpt",
  },
  {
    type: "claude_opus",
    label: "Claude Opus",
    description: "Anthropic Claude API",
    defaultUrl: "https://api.anthropic.com",
    defaultAlias: "claude_opus",
  },
  {
    type: "n8n",
    label: "n8n Webhook",
    description: "n8n webhook execution key",
    defaultUrl: "",
    defaultAlias: "n8n",
  },
];

export function keyTypeOption(type: string | null | undefined) {
  return (
    LOOKUP_KEY_TYPE_OPTIONS.find((option) => option.type === type) ??
    KEY_TYPE_OPTIONS[KEY_TYPE_OPTIONS.length - 1]
  );
}

export function keyTypeLabel(type: string | null | undefined) {
  return keyTypeOption(type).label;
}
