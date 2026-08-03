/** 内容台的统一文章形状。与后端 backend/app/modules/content_desk/dto.py 对镜。 */

/** DeepSeek 解读的七项。**这个类型就是契约**——后端不砍键、前端不藏项。
 *  SEO 面板现在只渲染 risks，把另外四项藏了；测试拿这个列表防复发。 */
export type Analysis = {
  translation: string | null;
  geo_role: string | null;
  why_written_this_way: string | null;
  strengths: string[] | null;
  risks: string[] | null;
  model: string | null;
  skill_version: string | null;
};

export type BrandViolation = { surface: string; term: string; evidence?: string };
export type UngroundedNumber = { surface: string; number: string };
export type BadDerivation = { value: string; from: string; reason: string };

export type BrandAudit = {
  clean: boolean;
  audited: boolean;
  site_brand: string | null;
  brand_violations: BrandViolation[];
  cjk_surfaces: string[];
  ungrounded_numbers: UngroundedNumber[];
  bad_derivations: BadDerivation[];
  ignored_findings: string[];
};

export type Section = { heading?: string; body?: string };
export type AnswerBlock = { question?: string; answer?: string };

export type ArticlePermissions = {
  can_review: boolean | null;
  can_revise: boolean | null;
  can_publish: boolean | null;
  blocked_reason?: string | null;
};

export type Article = {
  source: "geo" | "seo";
  source_label: string;
  id: string;
  kind: string;
  kind_label: string;
  title: string;
  parent_id: string | null;
  parent_label: string | null;
  /** 两个键恒存在。SEO 的 answer_blocks 是 []，前端只写一套渲染。 */
  body: { sections: Section[]; answer_blocks: AnswerBlock[] };
  seo_meta: { title?: string; meta_description?: string; url_slug?: string };
  analysis: Analysis | null;
  brand_audit: BrandAudit;
  revision: {
    round?: number;
    addressed?: string[];
    unaddressed?: { critique?: string; reason?: string; missing_fact?: string }[];
  } | null;
  review_status: string | null;
  generation_status: string | null;
  wp_post_id: number | null;
  wp_status: string | null;
  published_url: string | null;
  published_at: string | null;
  created_at: string | null;
  skill_version: string | null;
  provider: string | null;
  revise_mode: "sync" | "queued";
  extra: Record<string, unknown>;
  permissions: ArticlePermissions;
};

export type Step = {
  key: string;
  title: string;
  who: string;
  value: string;
  here: boolean;
  done: boolean;
};

export type Todo = {
  step: string;
  count: number;
  lead: string;
  note: string;
  action: "review" | "publish" | "engines";
  /** 挡路的（审/发/生成失败）才抢导轨；选题类是建议，出现在清单里但不抢。 */
  blocking?: boolean;
};

export type MachineLane = {
  key: string;
  label: string;
  ok: boolean;
  text: string;
};

export type Overview = {
  steps: Step[];
  todos: Todo[];
  machine: MachineLane[];
  counts: Record<string, number>;
};

/** 一个发布单元。**titles 必须显示出来**——GEO 一单是整簇，
 *  不列出来就会「点一篇发四篇」还不吭声。 */
export type PublishUnit = {
  source: string;
  unit_id: string;
  label: string;
  titles: string[];
  blockers: string[];
};

export type InFlight = {
  source: string;
  unit_id: string;
  job_id: string;
  status: string;
  /** 派单时刻。转圈不给时间 = 没有边界的承诺。 */
  since: string | null;
};

/** 已经发到站上的文章。**草稿 ≠ 读者能看到** —— n8n 刻意落草稿等人工发布。 */
export type Landed = {
  source: string;
  id: string;
  title: string;
  wp_post_id: number | null;
  wp_status: string | null;
  url: string | null;
};

export type PublishState = {
  units: PublishUnit[];
  in_flight: InFlight[];
  drafts: Landed[];
  live: Landed[];
};

export type SeoCandidate = {
  id: string;
  keyword: string;
  audience: string;
  destination: string;
  score: number | null;
  searches: number | null;
  attackability: number | null;
  terrain: string | null;
  category_path: string | null;
  supported: string[];
  missing: string[];
};

export type Cluster = {
  id: string;
  title: string;
  topic: string | null;
  category_path: string | null;
  product_count: number;
  /** 已挑几条买家问句。 */
  picked_count: number;
  /** 已经挖出来躺在库里的候选。**这就是深耕的存货**。 */
  mined_count: number;
};

export type TopicState = {
  seo_candidates: SeoCandidate[];
  clusters: Cluster[];
  awaiting_generation: { id: string; keyword: string; audience: string }[];
};

export type QuestionCandidate = {
  question: string;
  intent?: string;
  source?: string;
  terrain?: { attackability?: number; terrain?: string } | null;
};

export type ClusterQuestions = {
  cluster: { id: string; title: string };
  candidates: QuestionCandidate[];
  picked: { question: string; intent?: string }[];
};
