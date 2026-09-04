"use client";

import { useTheme, type SkinPref, type ThemePref } from "@/components/theme-provider";

import styles from "./login.module.css";

// 登录页拿不到服务端偏好，只有这台浏览器上次留下的 localStorage。
// 这枚胶囊给新设备一个入口：三个色点选皮肤，右边一个按钮在 跟随/白天/黑夜 之间轮转。
// 只写 localStorage 与 <html> 属性，不发任何请求；登录后服务端偏好照常接管。
const SKINS: { key: SkinPref; label: string; className: string }[] = [
  { key: "cockpit", label: "火凤凰驾驶舱", className: styles.dotCockpit },
  { key: "blush", label: "朝霞", className: styles.dotBlush },
  { key: "celadon", label: "青瓷", className: styles.dotCeladon },
];

const MODE_CYCLE: ThemePref[] = ["system", "light", "dark"];
const MODE_GLYPH: Record<ThemePref, string> = { system: "◐", light: "☼", dark: "☾" };
const MODE_LABEL: Record<ThemePref, string> = { system: "跟随系统", light: "白天", dark: "黑夜" };

export function LoginThemeSwitch() {
  const { modePref, setModePref, skinPref, setSkinPref } = useTheme();
  const nextMode = MODE_CYCLE[(MODE_CYCLE.indexOf(modePref) + 1) % MODE_CYCLE.length];

  return (
    <span aria-label="皮肤与明暗" className={styles.dots} role="group">
      {SKINS.map((skin) => (
        <button
          aria-label={skin.label}
          aria-pressed={skinPref === skin.key}
          className={`${styles.dot} ${skin.className}`}
          key={skin.key}
          onClick={() => setSkinPref(skin.key)}
          title={skin.label}
          type="button"
        />
      ))}
      <span aria-hidden="true" className={styles.dotsSep}>|</span>
      <button
        aria-label={`明暗：${MODE_LABEL[modePref]}，点击切到${MODE_LABEL[nextMode]}`}
        className={styles.modeButton}
        onClick={() => setModePref(nextMode)}
        title={`${MODE_LABEL[modePref]} → ${MODE_LABEL[nextMode]}`}
        type="button"
      >
        {MODE_GLYPH[modePref]}
      </button>
    </span>
  );
}
