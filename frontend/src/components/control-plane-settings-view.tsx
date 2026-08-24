"use client";

import {
  Check,
  Info,
  LoaderCircle,
  Monitor,
  Moon,
  Palette,
  Sun,
  Upload,
  UserRound,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { useTheme, type ThemePref } from "@/components/theme-provider";
import { LEGAL_DOCS, LegalDocView } from "@/components/legal-content";
import {
  getMyProfile,
  updateMyProfile,
  uploadMyAvatar,
  type ProfileMe,
} from "@/lib/profile-api";

import styles from "./control-plane-settings-view.module.css";

type Tab = "appearance" | "profile" | "about";

const THEME_OPTIONS: {
  key: ThemePref;
  label: string;
  desc: string;
  icon: typeof Sun;
}[] = [
  { key: "light", label: "白天", desc: "浅色界面", icon: Sun },
  { key: "dark", label: "黑夜", desc: "深色驾驶舱(默认)", icon: Moon },
  { key: "system", label: "跟随系统", desc: "随设备自动切换", icon: Monitor },
];

const ABOUT_DOCS = ["terms", "privacy", "support"] as const;

export function ControlPlaneSettingsView() {
  const { pref, setPref } = useTheme();
  const [tab, setTab] = useState<Tab>("appearance");
  const [profile, setProfile] = useState<ProfileMe | null>(null);
  const [nickname, setNickname] = useState("");
  const [savingNick, setSavingNick] = useState(false);
  const [nickSaved, setNickSaved] = useState(false);
  const [avatarBusy, setAvatarBusy] = useState(false);
  const [error, setError] = useState("");
  const [aboutDoc, setAboutDoc] = useState<(typeof ABOUT_DOCS)[number]>("terms");
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let active = true;
    getMyProfile()
      .then((data) => {
        if (!active) {
          return;
        }
        setProfile(data);
        setNickname(data.nickname ?? "");
        if (data.theme_pref && data.theme_pref !== pref) {
          setPref(data.theme_pref);
        }
      })
      .catch(() => setError("个人资料加载失败,请刷新重试。"));
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const chooseTheme = useCallback(
    (next: ThemePref) => {
      setPref(next);
      updateMyProfile({ theme_pref: next }).catch(() => undefined);
    },
    [setPref],
  );

  const saveNickname = useCallback(async () => {
    setSavingNick(true);
    setNickSaved(false);
    setError("");
    try {
      const updated = await updateMyProfile({ nickname: nickname.trim() });
      setProfile(updated);
      setNickSaved(true);
      window.setTimeout(() => setNickSaved(false), 2000);
    } catch {
      setError("昵称保存失败,请重试。");
    } finally {
      setSavingNick(false);
    }
  }, [nickname]);

  const onPickAvatar = useCallback(async (file: File) => {
    setAvatarBusy(true);
    setError("");
    try {
      const updated = await uploadMyAvatar(file);
      setProfile(updated);
    } catch (uploadError) {
      setError(
        uploadError instanceof Error ? uploadError.message : "头像上传失败。",
      );
    } finally {
      setAvatarBusy(false);
    }
  }, []);

  const realName = profile?.display_name ?? profile?.username ?? "";
  const previewName = nickname.trim()
    ? `${nickname.trim()}（${realName}）`
    : realName;

  return (
    <div className={styles.page}>
      <header className={styles.head}>
        <span className={styles.eyebrow}>账号与组织</span>
        <h1 className={styles.title}>设置</h1>
      </header>

      <nav className={styles.tabs}>
        <button
          className={tab === "appearance" ? styles.tabOn : styles.tab}
          onClick={() => setTab("appearance")}
          type="button"
        >
          <Palette size={15} /> 外观
        </button>
        <button
          className={tab === "profile" ? styles.tabOn : styles.tab}
          onClick={() => setTab("profile")}
          type="button"
        >
          <UserRound size={15} /> 个人资料
        </button>
        <button
          className={tab === "about" ? styles.tabOn : styles.tab}
          onClick={() => setTab("about")}
          type="button"
        >
          <Info size={15} /> 关于
        </button>
      </nav>

      {error ? <div className={styles.error}>{error}</div> : null}

      {tab === "appearance" ? (
        <section className={styles.panel}>
          <h2 className={styles.h2}>主题</h2>
          <p className={styles.hint}>
            浅色模式作用于功能页;工作台驾驶舱与登录页始终保持深色。
          </p>
          <div className={styles.themeGrid}>
            {THEME_OPTIONS.map((option) => {
              const Icon = option.icon;
              const active = pref === option.key;
              return (
                <button
                  key={option.key}
                  className={active ? styles.themeCardOn : styles.themeCard}
                  onClick={() => chooseTheme(option.key)}
                  type="button"
                >
                  <Icon size={22} />
                  <span className={styles.themeLabel}>{option.label}</span>
                  <span className={styles.themeDesc}>{option.desc}</span>
                  {active ? <Check className={styles.themeCheck} size={16} /> : null}
                </button>
              );
            })}
          </div>
        </section>
      ) : null}

      {tab === "profile" ? (
        <section className={styles.panel}>
          <h2 className={styles.h2}>头像</h2>
          <div className={styles.avatarRow}>
            <span className={styles.avatar}>
              {profile?.avatar_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={profile.avatar_url} alt="头像" />
              ) : (
                <span className={styles.avatarInitial}>
                  {realName.slice(0, 1) || "?"}
                </span>
              )}
            </span>
            <div>
              <button
                className={styles.uploadBtn}
                disabled={avatarBusy}
                onClick={() => fileRef.current?.click()}
                type="button"
              >
                {avatarBusy ? (
                  <LoaderCircle className={styles.spin} size={16} />
                ) : (
                  <Upload size={16} />
                )}
                {avatarBusy ? "上传中" : "上传头像"}
              </button>
              <p className={styles.avatarHint}>
                方形效果最佳,自动裁成 256×256。右上角与通讯里都会显示。
              </p>
              <input
                ref={fileRef}
                accept="image/*"
                hidden
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) {
                    void onPickAvatar(file);
                  }
                  event.target.value = "";
                }}
                type="file"
              />
            </div>
          </div>

          <h2 className={styles.h2} style={{ marginTop: 30 }}>
            昵称
          </h2>
          <p className={styles.hint}>
            设置后,用户管理与通讯里会显示为「昵称（{realName || "真名"}）」。
          </p>
          <div className={styles.nickRow}>
            <input
              className={styles.input}
              maxLength={64}
              onChange={(event) => setNickname(event.target.value)}
              placeholder="给自己起个称呼"
              value={nickname}
            />
            <button
              className={styles.saveBtn}
              disabled={savingNick}
              onClick={() => void saveNickname()}
              type="button"
            >
              {savingNick ? (
                <LoaderCircle className={styles.spin} size={16} />
              ) : nickSaved ? (
                <Check size={16} />
              ) : null}
              {nickSaved ? "已保存" : "保存"}
            </button>
          </div>
          <p className={styles.preview}>
            预览:<strong>{previewName || "—"}</strong>
          </p>
        </section>
      ) : null}

      {tab === "about" ? (
        <section className={styles.panel}>
          <div className={styles.aboutTabs}>
            {ABOUT_DOCS.map((key) => (
              <button
                key={key}
                className={aboutDoc === key ? styles.aboutTabOn : styles.aboutTab}
                onClick={() => setAboutDoc(key)}
                type="button"
              >
                {LEGAL_DOCS[key].title}
              </button>
            ))}
          </div>
          <LegalDocView doc={LEGAL_DOCS[aboutDoc]} />
          <p className={styles.version}>
            涌龙麟 · 火凤凰内部运营平台 · © 2026 Barong Yekhna
          </p>
        </section>
      ) : null}
    </div>
  );
}
