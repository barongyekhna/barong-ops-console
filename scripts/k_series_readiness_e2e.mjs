import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";

const BASE_URL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:3100";
const USERNAME = process.env.E2E_USERNAME;
const PASSWORD = process.env.E2E_PASSWORD;
const DB_CONTAINER = process.env.E2E_DB_CONTAINER ?? "";
const REPORT_PATH = process.env.E2E_REPORT_PATH ?? "k_readiness_e2e_report.json";

if (!USERNAME || !PASSWORD) {
  throw new Error("E2E_USERNAME and E2E_PASSWORD are required.");
}

const PNG_1X1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=",
  "base64",
);

const report = {
  generated_at: new Date().toISOString(),
  base_url: BASE_URL,
  steps: [],
  product: null,
  deletion: null,
  db_after_delete: null,
  final_status: "failed",
};

let sessionToken = "";
let product = null;

function record(name, status, detail = {}) {
  report.steps.push({
    name,
    status,
    detail,
    at: new Date().toISOString(),
  });
}

async function request(path, options = {}) {
  const headers = new Headers(options.headers ?? {});
  headers.set("Accept", "application/json");
  if (sessionToken) {
    headers.set("X-Session-Token", sessionToken);
  }
  const response = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers,
  });
  const contentType = response.headers.get("content-type") ?? "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    const error = new Error(`HTTP ${response.status} for ${path}`);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }

  return { payload, response };
}

async function jsonRequest(path, method, body) {
  return request(path, {
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json" },
    method,
  });
}

function riskKeywordTerm(item) {
  if (typeof item === "string") {
    return item;
  }
  if (item && typeof item === "object") {
    return String(item.term ?? item.keyword ?? item.text ?? "").trim();
  }
  return "";
}

function assertReadyState(readiness, expected, label) {
  if (readiness.ready !== expected) {
    throw new Error(`${label} readiness expected ${expected}, got ${readiness.ready}`);
  }
}

async function expectSaveBlocked(productId, label) {
  try {
    await jsonRequest(`/api/backend/k/products/${productId}`, "PATCH", {
      review_status: "approved",
    });
  } catch (error) {
    if (error.status === 409) {
      record(label, "passed", { status: 409, code: error.payload?.detail?.code });
      return;
    }
    throw error;
  }
  throw new Error(`${label} expected save to be blocked.`);
}

function dbCountsAfterDelete(productId) {
  if (!DB_CONTAINER) {
    return null;
  }
  if (!/^[0-9a-f-]{36}$/i.test(productId)) {
    throw new Error("Refusing DB check for invalid product id.");
  }

  const sql = `
select json_build_object(
  'products', (select count(*) from k_product_knowledge_products where id = '${productId}'::uuid),
  'variants', (select count(*) from k_product_knowledge_variants where product_id = '${productId}'::uuid),
  'keywords', (select count(*) from k_product_knowledge_keywords where product_id = '${productId}'::uuid),
  'risk_terms', (select count(*) from k_product_knowledge_risk_terms where product_id = '${productId}'::uuid),
  'media_assets', (select count(*) from k_product_knowledge_media_assets where product_id = '${productId}'::uuid),
  'ai_events', (select count(*) from k_product_knowledge_ai_events where product_id = '${productId}'::uuid),
  'workflow_executions', (select count(*) from k_product_knowledge_workflow_executions where product_id = '${productId}'::uuid),
  'research_runs', (select count(*) from k_product_knowledge_research_runs where product_id = '${productId}'::uuid),
  'attributes', (select count(*) from k_product_knowledge_attributes where product_id = '${productId}'::uuid),
  'review_items', (select count(*) from k_product_knowledge_review_items where product_id = '${productId}'::uuid),
  'versions', (select count(*) from k_product_knowledge_versions where product_id = '${productId}'::uuid),
  'translations', (select count(*) from k_product_knowledge_translations where product_id = '${productId}'::uuid)
);`;
  const compactSql = sql.replace(/\s+/g, " ").trim();
  const output = execFileSync(
    "docker",
    [
      "exec",
      DB_CONTAINER,
      "sh",
      "-lc",
      `psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc ${JSON.stringify(compactSql)}`,
    ],
    { encoding: "utf8" },
  ).trim();
  return JSON.parse(output);
}

async function cleanup() {
  if (!product) {
    return;
  }
  try {
    await jsonRequest(
      `/api/backend/k/products/${product.id}`,
      "DELETE",
      { product_key: product.product_key },
    );
  } catch {
    // Best-effort cleanup; the main flow records delete verification explicitly.
  }
}

try {
  const login = await jsonRequest("/api/backend/auth/login", "POST", {
    username: USERNAME,
    password: PASSWORD,
  });
  sessionToken = login.payload.session_token;
  if (!sessionToken) {
    throw new Error("Login did not return a session token.");
  }
  record("login", "passed", {
    role: login.payload.user?.role,
    username: login.payload.user?.username,
  });

  const suffix = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`.toUpperCase();
  const create = await jsonRequest("/api/backend/k/products", "POST", {
    parent_sku: `K-E2E-${suffix}`,
    product_name_en: `K Readiness E2E ${suffix}`,
    product_type: "variable_product",
    raw_input_text:
      "Stainless steel centrifugal pump for industrial water transfer, corrosion resistant housing, stable flow, B2B procurement use.",
    main_keyword: "stainless steel centrifugal pump",
    target_market: "US",
    target_locale: "en",
    source_system: "k_readiness_e2e",
    source_record_id: `K-READINESS-E2E-${suffix}`,
    brand_name: "Barong E2E",
    variants: [
      { color: "silver", size: "M", function: "standard", quantity: 10 },
      { color: "black", size: "L", function: "heavy duty", quantity: 5 },
    ],
  });
  product = create.payload;
  report.product = {
    id: product.id,
    product_key: product.product_key,
    variant_count: product.variants?.length ?? 0,
  };
  record("create_product", "passed", report.product);

  await expectSaveBlocked(product.id, "save_blocked_before_sections");

  const workflowStart = await jsonRequest(
    `/api/backend/k/products/${product.id}/workflow/start`,
    "POST",
    {
      target_market: "US",
      main_keyword: "stainless steel centrifugal pump",
      serp_query: "stainless steel centrifugal pump",
      seed_keywords: [],
      competitors: [],
    },
  );
  const workflow = workflowStart.payload;
  const riskKeywords = workflow.claude_filter_result_json?.risk_keywords ?? [];
  const decisions = riskKeywords
    .map(riskKeywordTerm)
    .filter(Boolean)
    .map((term) => ({ term, decision: "approve", reason: null }));
  record("workflow_start", "passed", {
    workflow_id: workflow.id,
    status: workflow.status,
    current_step: workflow.current_step,
    risk_keywords: decisions.length,
  });

  const canUseWorkflowKeywordReview = Boolean(
    workflow.id &&
      (workflow.current_step === "risk_term_manual_review" ||
        workflow.current_step === "risk_term_review_manual" ||
        workflow.risk_approval_log_json?.approved === true),
  );
  if (canUseWorkflowKeywordReview) {
    const keywordReview = await jsonRequest(
      `/api/backend/k/products/${product.id}/workflow/risk-review`,
      "POST",
      {
        execution_id: workflow.id,
        decisions,
        confirm_no_risk_terms: decisions.length === 0,
      },
    );
    record("submit_keywords", "passed", {
      mode: "workflow",
      status: keywordReview.payload.status,
      current_step: keywordReview.payload.current_step,
      keyword_digest_present: Boolean(
        keywordReview.payload.risk_approval_log_json?.keyword_digest,
      ),
    });
  } else {
    await jsonRequest(`/api/backend/k/products/${product.id}/keywords`, "PATCH", {
      items: [
        {
          keyword_text: "stainless steel centrifugal pump",
          keyword_type: "primary",
          language_code: "en",
          market: "US",
          search_intent: "commercial",
          source: "e2e_manual",
          status: "approved",
          confidence: 1,
          reason: "E2E fallback because staging AI provider binding is unavailable.",
        },
        {
          keyword_text: "industrial water transfer pump",
          keyword_type: "secondary",
          language_code: "en",
          market: "US",
          search_intent: "commercial",
          source: "e2e_manual",
          status: "approved",
          confidence: 1,
          reason: "E2E fallback because staging AI provider binding is unavailable.",
        },
      ],
    });
    const keywordReview = await request(
      `/api/backend/k/products/${product.id}/keywords/submit`,
      { method: "POST" },
    );
    record("submit_keywords", "passed", {
      mode: "manual_snapshot",
      workflow_status: workflow.status,
      workflow_step: workflow.current_step,
      status: keywordReview.payload.status,
      keyword_count: keywordReview.payload.count,
    });
  }

  await expectSaveBlocked(product.id, "save_blocked_before_images_and_selling_points");

  let sellingPointsPayload;
  try {
    const sellingGenerated = await request(
      `/api/backend/k/products/${product.id}/selling-points/generate`,
      { method: "POST" },
    );
    sellingPointsPayload = sellingGenerated.payload;
    record("generate_selling_points", "passed", {
      mode: "provider",
      bullets: sellingGenerated.payload.bullets?.length ?? 0,
      source: sellingGenerated.payload.source,
    });
  } catch (error) {
    if (error.status !== 503) {
      throw error;
    }
    sellingPointsPayload = {
      bullets: [
        {
          category: "conversion",
          importance_score: 1,
          text: "Corrosion-resistant stainless steel construction supports demanding industrial water transfer.",
        },
        {
          category: "procurement",
          importance_score: 0.95,
          text: "Stable flow performance and variant options simplify B2B purchasing decisions.",
        },
      ],
      seo_keywords: [
        "stainless steel centrifugal pump",
        "industrial water transfer pump",
      ],
      market_tags: ["US", "B2B", "industrial"],
      confidence_score: 1,
      source: "manual_e2e",
      marketing_copy:
        "Industrial stainless steel centrifugal pump built for stable water transfer and procurement-ready selection.",
      translated_version:
        "Industrial stainless steel centrifugal pump built for stable water transfer and procurement-ready selection.",
      chinese_translation:
        "工业级不锈钢离心泵，适用于稳定输水和B2B采购选型。",
      target_language: "en",
      product_id: product.id,
    };
    record("generate_selling_points", "passed", {
      mode: "manual_fallback",
      reason: error.payload?.detail?.code ?? error.payload?.detail?.reason ?? "provider_unavailable",
      bullets: sellingPointsPayload.bullets.length,
    });
  }
  const sellingApproved = await jsonRequest(
    `/api/backend/k/products/${product.id}/selling-points/approve`,
    "POST",
    {
      ...sellingPointsPayload,
      source: "manual_review",
    },
  );
  record("submit_selling_points", "passed", {
    bullets: sellingApproved.payload.bullets?.length ?? 0,
    source: sellingApproved.payload.source,
  });

  await expectSaveBlocked(product.id, "save_blocked_before_images");

  const variantSku = product.variants?.[0]?.variant_sku;
  if (!variantSku) {
    throw new Error("Created product did not include a variant SKU.");
  }
  for (let index = 0; index < 5; index += 1) {
    const form = new FormData();
    form.set("variant_sku", variantSku);
    form.set("asset_role", "main");
    form.set(
      "file",
      new Blob([PNG_1X1], { type: "image/png" }),
      `k-readiness-e2e-${index}.png`,
    );
    const uploaded = await request(
      `/api/backend/k/products/${product.id}/media/upload`,
      {
        body: form,
        method: "POST",
      },
    );
    if (!uploaded.payload.id) {
      throw new Error("Image upload did not return an asset id.");
    }
  }
  record("upload_images", "passed", { count: 5, variant_sku: variantSku });

  await expectSaveBlocked(product.id, "save_blocked_after_image_upload_before_submit");

  const imageSubmit = await request(
    `/api/backend/k/products/${product.id}/images/submit`,
    { method: "POST" },
  );
  record("submit_images", "passed", {
    submitted: imageSubmit.payload.submitted,
    count: imageSubmit.payload.count,
  });

  const readiness = await request(
    `/api/backend/k/products/${product.id}/readiness`,
    { method: "GET" },
  );
  assertReadyState(readiness.payload, true, "final");
  record("readiness_all_submitted", "passed", {
    keywords: readiness.payload.keywords.status,
    images: readiness.payload.images.status,
    selling_points: readiness.payload.selling_points.status,
  });

  const saved = await jsonRequest(
    `/api/backend/k/products/${product.id}`,
    "PATCH",
    { review_status: "approved" },
  );
  record("save_product_info", "passed", {
    review_status: saved.payload.review_status,
  });

  const sellingReloaded = await request(
    `/api/backend/k/products/${product.id}/selling-points`,
    { method: "GET" },
  );
  record("selling_points_reload_visible", "passed", {
    bullets: sellingReloaded.payload.bullets?.length ?? 0,
    source: sellingReloaded.payload.source,
  });

  const deleted = await jsonRequest(
    `/api/backend/k/products/${product.id}`,
    "DELETE",
    { product_key: product.product_key },
  );
  report.deletion = deleted.payload;
  record("delete_product", "passed", {
    deleted_counts: deleted.payload.deleted_counts,
  });

  try {
    await request(`/api/backend/k/products/${product.id}`, { method: "GET" });
    throw new Error("Deleted product was still readable.");
  } catch (error) {
    if (error.status !== 404) {
      throw error;
    }
  }
  record("get_after_delete", "passed", { status: 404 });

  const dbCounts = dbCountsAfterDelete(product.id);
  report.db_after_delete = dbCounts;
  if (dbCounts && Object.values(dbCounts).some((value) => Number(value) !== 0)) {
    throw new Error(`Database rows remain after delete: ${JSON.stringify(dbCounts)}`);
  }
  record("database_delete_verification", "passed", dbCounts ?? { skipped: true });

  product = null;
  report.final_status = "passed";
} catch (error) {
  record("failure", "failed", {
    message: error instanceof Error ? error.message : String(error),
    status: error?.status ?? null,
  });
  await cleanup();
  report.final_status = "failed";
  process.exitCode = 1;
} finally {
  writeFileSync(REPORT_PATH, `${JSON.stringify(report, null, 2)}\n`);
}
