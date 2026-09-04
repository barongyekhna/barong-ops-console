"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

/**
 * 两根独立的轴：`ThemePref` 选明暗，`SkinPref` 选配色。皮肤没有"跟随系统"这个
 * 概念——只有明暗才有。默认皮肤是 cockpit（火凤凰驾驶舱，产品现有身份）。
 */
export type ThemePref = "light" | "dark" | "system";
export type SkinPref = "cockpit" | "blush" | "celadon";

const MODE_STORAGE_KEY = "barong-theme";
const SKIN_STORAGE_KEY = "barong-skin";

/**
 * 深色优先（沿用产品现有默认）。`data-mode` 只在"明确选了白天/黑夜"时才标注；
 * "跟随系统"表现为**属性缺失**，交给 globals.css 里的 `@media
 * (prefers-color-scheme: light)` 去决定——不在 JS 里把"系统"解析成一个固定值
 * 再写回属性，那样会在系统切换明暗时不联动（除非额外接 matchMedia 监听器，
 * 现在也确实接了，但根源上"系统"就该表现为不标注）。
 *
 * `data-skin` 永远显式标注，默认 "cockpit"——这样即使 CSS 里某处忘了给
 * 无 data-skin 状态兜底，也不会真的发生（JS 侧保证了这个不变量）。
 */
function applyMode(pref: ThemePref): void {
  if (typeof document === "undefined") {
    return;
  }
  const root = document.documentElement;
  if (pref === "light" || pref === "dark") {
    root.setAttribute("data-mode", pref);
  } else {
    root.removeAttribute("data-mode");
  }
}

function applySkin(skin: SkinPref): void {
  if (typeof document === "undefined") {
    return;
  }
  document.documentElement.setAttribute("data-skin", skin);
}

function readStoredMode(): ThemePref {
  if (typeof window === "undefined") {
    return "dark";
  }
  try {
    const raw = window.localStorage.getItem(MODE_STORAGE_KEY);
    if (raw === "light" || raw === "dark" || raw === "system") {
      return raw;
    }
  } catch {
    /* localStorage unavailable — fall through to default */
  }
  return "dark";
}

function readStoredSkin(): SkinPref {
  if (typeof window === "undefined") {
    return "cockpit";
  }
  try {
    const raw = window.localStorage.getItem(SKIN_STORAGE_KEY);
    if (raw === "cockpit" || raw === "blush" || raw === "celadon") {
      return raw;
    }
  } catch {
    /* localStorage unavailable — fall through to default */
  }
  return "cockpit";
}

type ThemeContextValue = {
  modePref: ThemePref;
  setModePref: (pref: ThemePref) => void;
  skinPref: SkinPref;
  setSkinPref: (skin: SkinPref) => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [modePref, setModePrefState] = useState<ThemePref>("dark");
  const [skinPref, setSkinPrefState] = useState<SkinPref>("cockpit");

  // Hydrate the stored preference after mount (SSR renders the dark-cockpit default).
  useEffect(() => {
    const mode = readStoredMode();
    const skin = readStoredSkin();
    setModePrefState(mode);
    setSkinPrefState(skin);
    applyMode(mode);
    applySkin(skin);
  }, []);

  // When following the system, react to OS theme changes live. 对称地查
  // "dark" 这一侧——旧版本只查 "light" 一侧，OS 深色时不对称地判断不出来。
  useEffect(() => {
    if (modePref !== "system" || typeof window === "undefined") {
      return;
    }
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => applyMode("system");
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [modePref]);

  const setModePref = useCallback((next: ThemePref) => {
    setModePrefState(next);
    applyMode(next);
    try {
      window.localStorage.setItem(MODE_STORAGE_KEY, next);
    } catch {
      /* ignore persistence failures */
    }
  }, []);

  const setSkinPref = useCallback((next: SkinPref) => {
    setSkinPrefState(next);
    applySkin(next);
    try {
      window.localStorage.setItem(SKIN_STORAGE_KEY, next);
    } catch {
      /* ignore persistence failures */
    }
  }, []);

  return (
    <ThemeContext.Provider
      value={{ modePref, setModePref, skinPref, setSkinPref }}
    >
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (value === null) {
    return {
      modePref: "dark",
      setModePref: () => undefined,
      skinPref: "cockpit",
      setSkinPref: () => undefined,
    };
  }
  return value;
}

/**
 * Inline, run-before-paint snippet to avoid a flash of the wrong skin/mode
 * on first load. Must stay logically in sync with applyMode/applySkin above —
 * this is a separate, synchronous copy because it runs before React (and
 * therefore before ThemeProvider) ever mounts; see layout.tsx for placement.
 */
export const THEME_INIT_SCRIPT = `(function(){try{
var root=document.documentElement;
var m=localStorage.getItem('${MODE_STORAGE_KEY}');
var s=localStorage.getItem('${SKIN_STORAGE_KEY}');
root.setAttribute('data-skin', (s==='blush'||s==='celadon')?s:'cockpit');
if(m==='light'||m==='dark'){root.setAttribute('data-mode', m);}
}catch(e){}})();`;
