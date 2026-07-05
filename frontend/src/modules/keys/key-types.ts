"use client";

export type ApiKeyType =
  | "custom"
  | "serp"
  | "openai"
  | "chatgpt"
  | "claude_opus"
  | "deepseek"
  | "n8n"
  | "keepa";

export type ApiKeyTypeOption = {
  type: ApiKeyType;
  label: string;
  description: string;
  defaultUrl: string;
  defaultAlias: string;
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
    description: "OpenAI-compatible AI API",
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
    description: "ChatGPT-compatible AI API",
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
