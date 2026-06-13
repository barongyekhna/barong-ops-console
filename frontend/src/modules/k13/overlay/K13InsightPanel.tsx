"use client";

import {
  AlertTriangle,
  Gauge,
  Lightbulb,
  Search,
} from "lucide-react";
import type { ReactNode } from "react";
import { useMemo } from "react";

import type {
  ProductHealthLevel,
  ProductRiskFlag,
  ProductRiskInput,
  ProductSuggestionItem,
  RiskSeverity,
} from "../types";
import { getK13Insights } from "./getK13Insights";
import styles from "./K13InsightPanel.module.css";

type RiskLevel = "low" | "medium" | "high";
type ScoreTone = RiskLevel | "neutral";

type SuggestionGroup = {
  title: string;
  items: ProductSuggestionItem[];
};

export function K13InsightPanel({ product }: { product: ProductRiskInput }) {
  const insights = useMemo(() => getK13Insights(product), [product]);
  const riskLevel = getRiskLevel(insights.risk.risk_score);

  return (
    <section className={styles.insightLayer} aria-labelledby="k13-insight-title">
      <header className={styles.layerHeader}>
        <div>
          <span className={styles.eyebrow}>K13D Overlay Layer</span>
          <h3 id="k13-insight-title">AI Insight Panel</h3>
        </div>
        <span className={getRiskBadgeClass(riskLevel)}>
          {riskLevel.toUpperCase()} RISK
        </span>
      </header>

      <div className={styles.moduleGrid}>
        <RiskPanel
          complianceScore={insights.risk.compliance_score}
          flags={insights.risk.flags}
          riskLevel={riskLevel}
          riskScore={insights.risk.risk_score}
        />
        <SuggestionPanel
          bulletSuggestions={insights.suggestions.bullet_suggestions}
          descriptionSuggestions={insights.suggestions.description_suggestions}
          seoKeywords={insights.suggestions.seo_keywords}
          titleSuggestions={insights.suggestions.title_suggestions}
        />
        <ScoreDashboard
          complianceScore={insights.score.compliance_score}
          conversionScore={insights.score.conversion_score}
          healthLevel={insights.score.health_level}
          overallScore={insights.score.overall_score}
          riskScore={insights.score.risk_score}
          seoScore={insights.score.seo_score}
        />
      </div>
    </section>
  );
}

function RiskPanel({
  complianceScore,
  flags,
  riskLevel,
  riskScore,
}: {
  complianceScore: number;
  flags: ProductRiskFlag[];
  riskLevel: RiskLevel;
  riskScore: number;
}) {
  return (
    <section className={styles.module} aria-labelledby="k13-risk-title">
      <ModuleHeading
        icon={<AlertTriangle aria-hidden="true" size={17} />}
        label="K13A"
        title="Risk Panel"
        titleId="k13-risk-title"
      />

      <div className={styles.scorePair}>
        <ScoreTile
          label="risk_score"
          tone={riskLevel}
          value={formatScore(riskScore)}
        />
        <ScoreTile
          label="compliance_score"
          tone={getComplianceTone(complianceScore)}
          value={formatScore(complianceScore)}
        />
      </div>

      <div className={styles.subsection}>
        <div className={styles.subsectionHeader}>
          <strong>flags[]</strong>
          <span>{flags.length}</span>
        </div>

        {flags.length > 0 ? (
          <ul className={styles.flagList}>
            {flags.map((flag, index) => (
              <li
                className={styles.flagItem}
                key={`${flag.field}-${flag.type}-${flag.severity}-${index}`}
              >
                <div className={styles.flagMeta}>
                  <span className={getSeverityBadgeClass(flag.severity)}>
                    {flag.severity}
                  </span>
                  <span>{flag.field}</span>
                  <span>{flag.type}</span>
                </div>
                <p>{flag.message}</p>
              </li>
            ))}
          </ul>
        ) : (
          <p className={styles.emptyState}>No risk flags detected.</p>
        )}
      </div>
    </section>
  );
}

function SuggestionPanel({
  bulletSuggestions,
  descriptionSuggestions,
  seoKeywords,
  titleSuggestions,
}: {
  bulletSuggestions: ProductSuggestionItem[];
  descriptionSuggestions: ProductSuggestionItem[];
  seoKeywords: string[];
  titleSuggestions: ProductSuggestionItem[];
}) {
  const groups: SuggestionGroup[] = [
    { title: "title_suggestions", items: titleSuggestions },
    { title: "description_suggestions", items: descriptionSuggestions },
    { title: "bullet_suggestions", items: bulletSuggestions },
  ];

  return (
    <section className={styles.module} aria-labelledby="k13-suggestion-title">
      <ModuleHeading
        icon={<Lightbulb aria-hidden="true" size={17} />}
        label="K13B"
        title="Suggestion Panel"
        titleId="k13-suggestion-title"
      />

      <div className={styles.suggestionStack}>
        {groups.map((group) => (
          <SuggestionGroup key={group.title} {...group} />
        ))}
      </div>

      <div className={styles.keywordBlock}>
        <div className={styles.subsectionHeader}>
          <strong>seo_keywords</strong>
          <Search aria-hidden="true" size={14} />
        </div>
        {seoKeywords.length > 0 ? (
          <div className={styles.keywordList}>
            {seoKeywords.map((keyword) => (
              <span className={styles.keywordChip} key={keyword}>
                {keyword}
              </span>
            ))}
          </div>
        ) : (
          <p className={styles.emptyState}>No SEO keywords generated.</p>
        )}
      </div>
    </section>
  );
}

function SuggestionGroup({ items, title }: SuggestionGroup) {
  return (
    <details className={styles.suggestionGroup} open={items.length > 0}>
      <summary className={styles.suggestionSummary}>
        <span>{title}</span>
        <span>{items.length}</span>
      </summary>

      {items.length > 0 ? (
        <div className={styles.suggestionCards}>
          {items.map((item, index) => (
            <article
              className={styles.suggestionCard}
              key={`${title}-${item.reason}-${item.impact_score}-${index}`}
            >
              <header className={styles.suggestionCardHeader}>
                <span className={styles.ideaMark} aria-hidden="true">
                  💡
                </span>
                <span className={styles.reasonLabel}>
                  Reason: {item.reason}
                </span>
                <span className={styles.impactBadge}>
                  impact_score {formatScore(item.impact_score)}
                </span>
              </header>
              <p>{item.suggestion}</p>
            </article>
          ))}
        </div>
      ) : (
        <p className={styles.emptyState}>No suggestions for this area.</p>
      )}
    </details>
  );
}

function ScoreDashboard({
  complianceScore,
  conversionScore,
  healthLevel,
  overallScore,
  riskScore,
  seoScore,
}: {
  complianceScore: number;
  conversionScore: number;
  healthLevel: ProductHealthLevel;
  overallScore: number;
  riskScore: number;
  seoScore: number;
}) {
  return (
    <section className={styles.module} aria-labelledby="k13-score-title">
      <ModuleHeading
        icon={<Gauge aria-hidden="true" size={17} />}
        label="K13C"
        title="Score Dashboard"
        titleId="k13-score-title"
      />

      <div className={styles.overallScore}>
        <div>
          <span>overall_score</span>
          <strong>{formatScore(overallScore)}</strong>
        </div>
        <span className={getHealthBadgeClass(healthLevel)}>
          health_level {healthLevel}
        </span>
      </div>

      <div className={styles.scoreList}>
        <ScoreMeter
          label="risk_score"
          tone={getRiskLevel(riskScore)}
          value={formatScore(riskScore)}
        />
        <ScoreMeter
          label="seo_score"
          tone={getPositiveScoreTone(seoScore)}
          value={formatScore(seoScore)}
        />
        <ScoreMeter
          label="conversion_score"
          tone={getPositiveScoreTone(conversionScore)}
          value={formatScore(conversionScore)}
        />
        <ScoreMeter
          label="compliance_score"
          tone={getComplianceTone(complianceScore)}
          value={formatScore(complianceScore)}
        />
      </div>
    </section>
  );
}

function ModuleHeading({
  icon,
  label,
  title,
  titleId,
}: {
  icon: ReactNode;
  label: string;
  title: string;
  titleId: string;
}) {
  return (
    <header className={styles.moduleHeading}>
      <div className={styles.moduleIcon}>{icon}</div>
      <div>
        <span>{label}</span>
        <h4 id={titleId}>{title}</h4>
      </div>
    </header>
  );
}

function ScoreTile({
  label,
  tone,
  value,
}: {
  label: string;
  tone: ScoreTone;
  value: number;
}) {
  return (
    <div className={styles.scoreTile}>
      <span>{label}</span>
      <strong className={getScoreValueClass(tone)}>{value}</strong>
    </div>
  );
}

function ScoreMeter({
  label,
  tone,
  value,
}: {
  label: string;
  tone: ScoreTone;
  value: number;
}) {
  return (
    <div className={styles.scoreMeter}>
      <div className={styles.scoreMeterHeader}>
        <span>{label}</span>
        <strong>{value}</strong>
      </div>
      <div className={styles.scoreTrack} aria-hidden="true">
        <div
          className={getScoreBarClass(tone)}
          style={{ width: `${clampScore(value)}%` }}
        />
      </div>
    </div>
  );
}

function getRiskLevel(score: number): RiskLevel {
  if (score >= 70) {
    return "high";
  }

  if (score >= 40) {
    return "medium";
  }

  return "low";
}

function getComplianceTone(score: number): RiskLevel {
  if (score < 50) {
    return "high";
  }

  if (score < 75) {
    return "medium";
  }

  return "low";
}

function getPositiveScoreTone(score: number): RiskLevel {
  if (score < 50) {
    return "high";
  }

  if (score < 75) {
    return "medium";
  }

  return "low";
}

function getRiskBadgeClass(level: RiskLevel) {
  return cx(styles.riskBadge, styles[`tone${capitalize(level)}`]);
}

function getSeverityBadgeClass(severity: RiskSeverity) {
  return cx(styles.severityBadge, styles[`tone${capitalize(severity)}`]);
}

function getHealthBadgeClass(level: ProductHealthLevel) {
  const tone =
    level === "critical" || level === "poor"
      ? "High"
      : level === "medium"
        ? "Medium"
        : "Low";

  return cx(styles.healthBadge, styles[`tone${tone}`]);
}

function getScoreValueClass(tone: ScoreTone) {
  return cx(styles.scoreValue, styles[`toneText${capitalize(tone)}`]);
}

function getScoreBarClass(tone: ScoreTone) {
  return cx(styles.scoreBar, styles[`toneBg${capitalize(tone)}`]);
}

function formatScore(score: number) {
  return Math.round(clampScore(score));
}

function clampScore(score: number) {
  if (!Number.isFinite(score)) {
    return 0;
  }

  return Math.min(100, Math.max(0, score));
}

function capitalize(value: string) {
  return `${value.charAt(0).toUpperCase()}${value.slice(1)}`;
}

function cx(...classNames: Array<string | false | undefined>) {
  return classNames.filter(Boolean).join(" ");
}
