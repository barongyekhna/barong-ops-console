"use client";

import { AlertTriangle, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api";
import {
  generateSellingPoints,
  getSellingPoints,
} from "@/modules/k14/selling-points/api";
import type { ProductSellingPoints } from "@/modules/k14/selling-points/types";

import type { ProductReviewRecord } from "../services/k12Api";

type SellingPointsPanelProps = {
  review: ProductReviewRecord;
};

export function SellingPointsPanel({ review }: SellingPointsPanelProps) {
  const [sellingPoints, setSellingPoints] =
    useState<ProductSellingPoints | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let isMounted = true;

    async function loadSellingPoints() {
      setIsLoading(true);
      setError("");

      try {
        const cached = await getSellingPoints(review.product_id);

        if (isMounted) {
          setSellingPoints(cached);
        }
      } catch (caught) {
        try {
          if (!(caught instanceof ApiError) || caught.status !== 404) {
            throw caught;
          }

          const generated = await generateSellingPoints(
            toSellingPointsProductPayload(review),
          );

          if (isMounted) {
            setSellingPoints(generated);
          }
        } catch (fallbackError) {
          if (isMounted) {
            setSellingPoints(null);
            setError(
              fallbackError instanceof Error
                ? fallbackError.message
                : "Selling points are unavailable in mock API mode.",
            );
          }
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    }

    void loadSellingPoints();

    return () => {
      isMounted = false;
    };
  }, [review]);

  return (
    <section
      className="k12-review-panel k12-selling-points-panel"
      aria-labelledby="k12-selling-points"
    >
      <header className="k12-review-panel-heading">
        <div>
          <span className="eyebrow">K14 Selling Points</span>
          <h3 id="k12-selling-points">AI Generated Selling Points</h3>
        </div>
        {sellingPoints ? (
          <strong className="k12-review-status-badge">
            {Math.round(sellingPoints.confidence_score * 100)}%
          </strong>
        ) : null}
      </header>

      {isLoading ? (
        <div className="k12-selling-points-state">
          <Loader2 aria-hidden="true" className="spin" size={18} />
          Loading selling points
        </div>
      ) : null}

      {!isLoading && error ? (
        <div className="k12-selling-points-state k12-selling-points-error">
          <AlertTriangle aria-hidden="true" size={18} />
          <span>{error}</span>
        </div>
      ) : null}

      {!isLoading && sellingPoints ? (
        <SellingPointsReadOnlyView sellingPoints={sellingPoints} />
      ) : null}
    </section>
  );
}

function SellingPointsReadOnlyView({
  sellingPoints,
}: {
  sellingPoints: ProductSellingPoints;
}) {
  return (
    <div className="k12-selling-points-content">
      <dl className="k12-review-item-summary">
        <div>
          <dt>Title</dt>
          <dd>{sellingPoints.title}</dd>
        </div>
        <div>
          <dt>Source</dt>
          <dd>{sellingPoints.source}</dd>
        </div>
        <div>
          <dt>Language</dt>
          <dd>{sellingPoints.language}</dd>
        </div>
        <div>
          <dt>Confidence</dt>
          <dd>{sellingPoints.confidence_score.toFixed(2)}</dd>
        </div>
      </dl>

      <ul className="k12-selling-points-list" aria-label="Selling point bullets">
        {sellingPoints.bullets.map((bullet, index) => (
          <li key={`${bullet.category}-${index}-${bullet.text}`}>
            <span>{bullet.category}</span>
            <strong>{bullet.text}</strong>
            <em>{bullet.importance_score}</em>
          </li>
        ))}
      </ul>

      <ReadonlyTagGroup label="SEO Keywords" values={sellingPoints.seo_keywords} />
      <ReadonlyList label="SEO Bullets" values={sellingPoints.seo_bullets} />
      <ReadonlyTagGroup label="Market Tags" values={sellingPoints.market_tags} />
    </div>
  );
}

function ReadonlyTagGroup({ label, values }: { label: string; values: string[] }) {
  if (values.length === 0) {
    return null;
  }

  return (
    <div className="k12-selling-points-tags">
      <span>{label}</span>
      <div>
        {values.map((value) => (
          <strong key={value}>{value}</strong>
        ))}
      </div>
    </div>
  );
}

function ReadonlyList({ label, values }: { label: string; values: string[] }) {
  if (values.length === 0) {
    return null;
  }

  return (
    <div className="k12-selling-points-readonly-list">
      <span>{label}</span>
      <ul>
        {values.map((value) => (
          <li key={value}>{value}</li>
        ))}
      </ul>
    </div>
  );
}

function toSellingPointsProductPayload(
  review: ProductReviewRecord,
): Record<string, unknown> {
  return {
    id: review.product_id,
    product_id: review.product_id,
    title: review.ai_canonical.title,
    product_name_en: review.ai_canonical.title,
    description: review.ai_canonical.description,
    raw_input: review.raw_input.original_input_text,
    raw_input_text: review.raw_input.original_input_text,
    language: review.raw_input.original_language,
    raw_input_language: review.raw_input.original_language,
    features: review.ai_canonical.features,
    bullet_points: review.raw_input.original_json.bullet_points,
    keywords: review.ai_canonical.keywords,
    specs: review.ai_canonical.specs,
    dimensions: review.ai_canonical.dimensions,
    original_json: review.raw_input.original_json,
    market_tags: ["general"],
  };
}
