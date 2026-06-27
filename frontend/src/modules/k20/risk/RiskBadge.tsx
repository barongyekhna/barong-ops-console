"use client";

import { AlertCircle, AlertTriangle, ShieldAlert, ShieldCheck } from "lucide-react";

import styles from "./RiskPanel.module.css";
import type { RiskLevel } from "./types";
import { riskLevelLabels } from "./types";

type RiskBadgeProps = {
  level: RiskLevel;
};

export function RiskBadge({ level }: RiskBadgeProps) {
  const Icon = iconByLevel[level];

  return (
    <span className={`${styles.riskBadge} ${styles[level]}`}>
      <Icon aria-hidden="true" size={14} />
      {riskLevelLabels[level]}
    </span>
  );
}

const iconByLevel = {
  low: ShieldCheck,
  medium: AlertCircle,
  high: AlertTriangle,
  critical: ShieldAlert,
} satisfies Record<RiskLevel, typeof ShieldCheck>;
