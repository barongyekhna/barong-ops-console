"use client";

import { useEffect, useState } from "react";

import { getCSSummary } from "./api";

const POLL_MS = 30_000;

export function useCsNewCount(enabled: boolean) {
  const [count, setCount] = useState(0);

  useEffect(() => {
    if (!enabled) {
      setCount(0);
      return;
    }

    let active = true;
    let controller: AbortController | null = null;
    const load = async () => {
      controller?.abort();
      controller = new AbortController();
      try {
        const summary = await getCSSummary(controller.signal);
        if (active) {
          setCount(summary.retail.new + summary.wholesale.new);
        }
      } catch {
        // The sidebar counter is best-effort; retain the last confirmed count.
      }
    };

    void load();
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => {
      active = false;
      controller?.abort();
      window.clearInterval(timer);
    };
  }, [enabled]);

  return count;
}
