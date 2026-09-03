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
  Copy,
  Fingerprint,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { useTheme, type ThemePref } from "@/components/theme-provider";
import { LEGAL_DOCS, LegalDocView } from "@/components/legal-content";
import {
  getMyProfile,
  updateMyProfile,
  uploadMyAvatar,
  type ProfileMe,
  getMyMcpAccess,
  resetMyMcpToken,
  type McpAccessMe,
  type McpTokenIssued,
} from "@/lib/profile-api";

import styles from "./control-plane-settings-view.module.css";
import { RELEASE_VERSION } from "@/lib/release-metadata";

type Tab = "appearance" | "profile" | "about";

const THEME_OPTIONS: {
  key: ThemePref;
  label: string;
  desc: string;
  icon: typeof Sun;
}[] = [
  { key: "light", label: "白天", desc: "浅色界面(逐页迁移中)", icon: Sun },
  { key: "dark", label: "黑夜", desc: "深色驾驶舱(默认)", icon: Moon },
  { key: "system", label: "跟随系统", desc: "随设备自动切换", icon: Monitor },
];

const ABOUT_DOCS = ["terms", "privacy", "support"] as const;

export function ControlPlaneSettingsView() {
  const { pref, setPref } = useTheme();
  const [tab, setTab] = useState<Tab>("appearance");
  const [profile, setProfile] = useState<ProfileMe | null>(null);
  const [nickname, setNickname] = useState("");
  // MCP 个人钥匙(Codex 等外部代理的身份)
  const [mcp, setMcp] = useState<McpAccessMe | null>(null);
  const [mcpIssued, setMcpIssued] = useState<McpTokenIssued | null>(null);
  const [mcpBusy, setMcpBusy] = useState(false);
  const [mcpError, setMcpError] = useState<string | null>(null);
  const [mcpCopied, setMcpCopied] = useState<string | null>(null);
  const [mcpOs, setMcpOs] = useState<"mac" | "windows">("mac");
  useEffect(() => {
    if (typeof navigator !== "undefined" && /windows/i.test(navigator.userAgent)) {
      setMcpOs("windows");
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    getMyMcpAccess()
      .then((data) => {
        if (!cancelled) {
          setMcp(data);
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setMcpError(error instanceof Error ? error.message : "取不到钥匙状态。");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const issueMcpToken = useCallback(async () => {
    if (
      mcp?.summary.has_token &&
      !window.confirm("重置会让你所有电脑上的旧钥匙立刻失效,需要重新贴一次装机命令。继续?")
    ) {
      return;
    }
    setMcpBusy(true);
    setMcpError(null);
    try {
      const issued = await resetMyMcpToken();
      setMcpIssued(issued);
      setMcp((prev) => (prev ? { ...prev, summary: issued.summary } : prev));
    } catch (error) {
      setMcpError(error instanceof Error ? error.message : "生成钥匙失败。");
    } finally {
      setMcpBusy(false);
    }
  }, [mcp]);

  const copyMcp = useCallback(async (key: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setMcpCopied(key);
      window.setTimeout(() => setMcpCopied(null), 2500);
    } catch {
      setMcpError("复制失败,请手动选中复制。");
    }
  }, []);
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
            浅色模式还在逐页迁移:已经改用统一配色的页面会变浅,
            其余页面(大多数模块页)仍是深色,切过去会看到深浅混排。
            工作台驾驶舱与登录页按设计始终保持深色。
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

          <h2 className={styles.h2} style={{ marginTop: 30 }}>
            <Fingerprint size={16} style={{ verticalAlign: -3, marginRight: 6 }} />
            Codex / MCP 接入钥匙
          </h2>
          <p className={styles.hint}>
            这是你个人的钥匙:让你电脑上的 Codex 以「你」的身份连进控制台(比如给 K 系列作图,交上去的图记在你名下)。
            明文只在生成那一刻显示一次;换电脑或忘了就重置一把新的,旧的立刻失效。管理员可以停用。
          </p>
          {mcpError ? <p className={styles.error}>{mcpError}</p> : null}
          {mcp && !mcp.eligible ? (
            <p className={styles.hint}>机器人账号不发个人钥匙。</p>
          ) : null}
          {mcp?.eligible ? (
            <div className={styles.nickRow}>
              <span className={styles.hint} style={{ margin: 0 }}>
                状态:
                {mcp.summary.has_token
                  ? mcp.summary.status === "disabled"
                    ? " 已被管理员停用"
                    : ` 正常 · ${mcp.summary.token_prefix}…`
                  : " 尚未生成"}
                {mcp.summary.last_used_at
                  ? ` · 上次使用 ${new Date(mcp.summary.last_used_at).toLocaleString("zh-CN")}`
                  : ""}
              </span>
              {mcp.summary.status !== "disabled" ? (
                <button
                  className={styles.saveBtn}
                  disabled={mcpBusy}
                  onClick={() => void issueMcpToken()}
                  type="button"
                >
                  {mcpBusy ? <LoaderCircle className={styles.spin} size={16} /> : null}
                  {mcp.summary.has_token ? "重置钥匙" : "生成钥匙"}
                </button>
              ) : null}
            </div>
          ) : null}
          {mcpIssued ? (
            <div className={styles.panel} style={{ marginTop: 14 }}>
              <p className={styles.hint} style={{ color: "#ffb13b" }}>
                只显示这一次。复制下面这一行,贴进你电脑的终端,按回车;看到 ✔ 就接好了。
              </p>
              <p className={styles.hint} style={{ margin: "0 0 8px" }}>
                检测到你的电脑是 <strong>{mcpOs === "windows" ? "Windows" : "Mac"}</strong>。
                {" "}
                <button
                  className={styles.tab}
                  onClick={() => setMcpOs(mcpOs === "windows" ? "mac" : "windows")}
                  style={{ padding: "2px 10px", fontSize: 12 }}
                  type="button"
                >
                  不对?切到 {mcpOs === "windows" ? "Mac" : "Windows"}
                </button>
              </p>
              <div className={styles.nickRow} style={{ alignItems: "center" }}>
                <code
                  style={{
                    flex: 1,
                    minWidth: 0,
                    overflowX: "auto",
                    whiteSpace: "nowrap",
                    fontSize: 12,
                    padding: "8px 10px",
                    borderRadius: 8,
                    background: "#0b1220",
                    color: "#e3f0ff",
                    border: "1px solid rgba(120,200,255,.25)",
                  }}
                >
                  {mcpOs === "windows"
                    ? mcpIssued.setup_command_windows
                    : mcpIssued.setup_command_mac}
                </code>
                <button
                  className={styles.saveBtn}
                  onClick={() =>
                    void copyMcp(
                      "cmd",
                      mcpOs === "windows"
                        ? mcpIssued.setup_command_windows
                        : mcpIssued.setup_command_mac,
                    )
                  }
                  type="button"
                >
                  <Copy size={14} />
                  {mcpCopied === "cmd" ? "已复制" : "复制这一行"}
                </button>
              </div>
              <p className={styles.hint} style={{ marginTop: 8 }}>{mcpIssued.verify_hint}</p>
            </div>
          ) : null}
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
            涌龙麟 · 火凤凰内部运营平台 · 版本 {RELEASE_VERSION} · © 2026 Barong
            Yekhna
          </p>
        </section>
      ) : null}
    </div>
  );
}
