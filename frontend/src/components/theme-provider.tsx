"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

export type ThemePref = "light" | "dark" | "system";

const STORAGE_KEY = "barong-theme";

/**
 * The app is dark by default (the forced-dark cockpit layer in globals.css).
 * We only ever ADD `data-theme="light"` on <html> to switch on the light layer;
 * "dark" and system-resolved-dark leave the attribute absent → forced dark.
 * This keeps the toggle additive and never disturbs the working dark theme.
 */
function prefersLight(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  return window.matchMedia("(prefers-color-scheme: light)").matches;
}

function resolveIsLight(pref: ThemePref): boolean {
  if (pref === "light") {
    return true;
  }
  if (pref === "dark") {
    return false;
  }
  return prefersLight();
}

function applyTheme(pref: ThemePref): void {
  if (typeof document === "undefined") {
    return;
  }
  const root = document.documentElement;
  if (resolveIsLight(pref)) {
    root.setAttribute("data-theme", "light");
  } else {
    root.removeAttribute("data-theme");
  }
}

function readStoredPref(): ThemePref {
  if (typeof window === "undefined") {
    return "dark";
  }
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === "light" || raw === "dark" || raw === "system") {
      return raw;
    }
  } catch {
    /* localStorage unavailable — fall through to default */
  }
  return "dark";
}

type ThemeContextValue = {
  pref: ThemePref;
  setPref: (pref: ThemePref) => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [pref, setPrefState] = useState<ThemePref>("dark");

  // Hydrate the stored preference after mount (SSR renders the dark default).
  useEffect(() => {
    const stored = readStoredPref();
    setPrefState(stored);
    applyTheme(stored);
  }, []);

  // When following the system, react to OS theme changes live.
  useEffect(() => {
    if (pref !== "system" || typeof window === "undefined") {
      return;
    }
    const media = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = () => applyTheme("system");
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [pref]);

  const setPref = useCallback((next: ThemePref) => {
    setPrefState(next);
    applyTheme(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* ignore persistence failures */
    }
  }, []);

  return (
    <ThemeContext.Provider value={{ pref, setPref }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (value === null) {
    return { pref: "dark", setPref: () => undefined };
  }
  return value;
}

/** Inline, run-before-paint snippet to avoid a light/dark flash on first load. */
export const THEME_INIT_SCRIPT = `(function(){try{var p=localStorage.getItem('${STORAGE_KEY}');var light=p==='light'||(p==='system'&&window.matchMedia('(prefers-color-scheme: light)').matches);if(light){document.documentElement.setAttribute('data-theme','light');}}catch(e){}})();`;
