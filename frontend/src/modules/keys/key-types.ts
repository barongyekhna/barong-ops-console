"use client";

export type ApiKeyType =
  | "custom"
  | "serp"
  | "openai"
  | "chatgpt"
  | "claude_opus"
  | "anthropic"
  | "deepseek"
  | "n8n"
  | "keepa"
  | "alibaba1688"
  | "rainforest"
  | "google_ads"
  | "amazon_sp_api"
  | "amazon_ads_api"
  | "google_search_console"
  | "track17";

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
    type: "anthropic",
    label: "Anthropic(Claude 官方)",
    description: "Claude 官方 API(Haiku 快活 / Opus 终审);在 Claude Console 建 key,作用范围选单个工作区",
    defaultUrl: "https://api.anthropic.com",
    defaultAlias: "anthropic",
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
    type: "amazon_sp_api",
    label: "Amazon SP-API(私有应用)",
    description: "一家公司一把。粘贴一行 JSON:{client_id, client_secret, refresh_token, region(na|eu|fe)};别名 sp_api,绑到该公司 × 亚马逊运营",
    defaultUrl: "https://sellingpartnerapi-na.amazon.com",
    defaultAlias: "sp_api",
  },
  {
    type: "amazon_ads_api",
    label: "Amazon Ads API",
    description: "一店一把。粘贴一行 JSON:{client_id, client_secret, refresh_token, region, profile_ids:[…]};别名 ads:<店铺码>,如 ads:01us",
    defaultUrl: "https://advertising-api.amazon.com",
    defaultAlias: "ads",
  },
  {
    type: "google_search_console",
    label: "Google Search Console(服务账号)",
    description: "苏青禾读独立站的搜索表现(每个词的展现 / 点击 / 排名)做搜索缺口。粘服务账号的 JSON 钥匙整段;别名 gsc,绑到贸易公司。只读。",
    defaultUrl: "https://searchconsole.googleapis.com",
    defaultAlias: "gsc",
  },
  {
    type: "track17",
    label: "17TRACK",
    description: "17TRACK 物流轨迹注册与查询 API",
    defaultUrl: "https://api.17track.net",
    defaultAlias: "track17",
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
    label: "Claude Opus(4sapi 中转,已退役)",
    description: "旧的 4sapi 中转 Claude 钥匙;文字调用已改走 Anthropic 官方",
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
