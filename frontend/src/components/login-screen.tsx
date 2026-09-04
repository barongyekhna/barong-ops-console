"use client";

import Link from "next/link";

import { LoginForm } from "@/components/login-form";
import { LoginThemeSwitch } from "@/components/login-theme-switch";

import styles from "./login.module.css";

export function LoginScreen() {
  return (
    <main className={styles.page}>
      {/* 龙鳞：一张 SVG 当 mask，颜色随皮肤（见 login.module.css 的 --lg-d1/d2/d3） */}
      <span className={styles.dragon} aria-hidden="true" />
      <div className={styles.veil} />

      <div className={styles.stage}>
        <section className={styles.brand}>
          <span className={styles.phx}>
            {/* 矢量原稿 barong-phoenix.svg 当 mask，名片金色渐变（见 login.module.css .phoenix） */}
            <span aria-label="涌龙麟 火凤凰" className={styles.phoenix} role="img" />
          </span>
          <span className={styles.eyebrow}>涌 · 龙 · 麟</span>
          <p className={styles.latin}>Barong&nbsp;&nbsp;Yekhna</p>
          <p className={styles.tagline}>
            I will see this great vision,
            <br />
            in which the bush does not burn.
          </p>
        </section>

        <section className={styles.card}>
          <h2 className={styles.cardHead}>登录</h2>
          <p className={styles.cardSub}>Access · 火凤凰指挥中心</p>
          <LoginForm />
          <div className={styles.foot}>
            <span className={styles.footCy} />
            会话加密 · 30 天免掉线
          </div>
        </section>
      </div>

      <footer className={styles.footbar}>
        <div className={styles.footbarL}>
          <LoginThemeSwitch />
          <span>仅限授权人员访问 · 所有操作全程留痕</span>
        </div>
        <div className={styles.footbarR}>
          <Link href="/terms">使用规范</Link>
          <span aria-hidden="true" className={styles.sep}>·</span>
          <Link href="/privacy">隐私政策</Link>
          <span aria-hidden="true" className={styles.sep}>·</span>
          <Link href="/support">技术支持</Link>
          <span className={styles.cr}>© 2026 涌龙麟 · Barong Yekhna</span>
        </div>
      </footer>
    </main>
  );
}
