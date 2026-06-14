export type SERPTriggerState = "idle" | "loading" | "completed" | "failed";

export type SERPItem = {
  title: string;
  url: string;
  snippet: string;
  rank: number;
};

export type SERPResult = {
  id: string;
  product_id: string;
  market: string;
  query: string;
  organic_results: SERPItem[];
  competitor_links: string[];
  keywords: string[];
  source: string;
  created_at: string;
  updated_at: string;
};

export type SERPSearchRequest = {
  product_id: string;
  market: string;
  query: string;
};
