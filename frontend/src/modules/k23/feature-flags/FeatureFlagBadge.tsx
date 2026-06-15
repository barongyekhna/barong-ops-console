"use client";

import { Power, PowerOff } from "lucide-react";

import styles from "./FeatureFlagPanel.module.css";

type FeatureFlagBadgeProps = {
  enabled: boolean;
};

export function FeatureFlagBadge({ enabled }: FeatureFlagBadgeProps) {
  const Icon = enabled ? Power : PowerOff;
  const label = enabled ? "enabled" : "disabled";

  return (
    <span className={`${styles.statusBadge} ${styles[label]}`}>
      <Icon aria-hidden="true" size={14} />
      {label}
    </span>
  );
}
