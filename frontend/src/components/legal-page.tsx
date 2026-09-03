import Link from "next/link";

import { LEGAL_DOCS, LegalDocView } from "@/components/legal-content";

import styles from "./legal-page.module.css";

const TABS = [
  { key: "terms", href: "/terms", label: "使用规范" },
  { key: "privacy", href: "/privacy", label: "隐私政策" },
  { key: "support", href: "/support", label: "技术支持" },
];

export function LegalPageShell({ activeKey }: { activeKey: string }) {
  const doc = LEGAL_DOCS[activeKey];

  return (
    <main className={styles.page}>
      <div className={styles.frame}>
        <header className={styles.head}>
          <Link href="/login" className={styles.brand}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/assets/brand/phoenix-gold.png" alt="" aria-hidden="true" />
            <span>
              <strong>涌龙麟</strong>
              <small>内部运营平台</small>
            </span>
          </Link>
          <Link href="/login" className={styles.back}>
            ← 返回登录
          </Link>
        </header>

        <nav className={styles.tabs} aria-label="法务与支持">
          {TABS.map((tab) => (
            <Link
              key={tab.key}
              href={tab.href}
              className={tab.key === activeKey ? styles.tabOn : styles.tab}
              aria-current={tab.key === activeKey ? "page" : undefined}
            >
              {tab.label}
            </Link>
          ))}
        </nav>

        <h1 className={styles.title}>{doc.title}</h1>
        <LegalDocView doc={doc} />

        <footer className={styles.foot}>© 2026 涌龙麟 · Barong Yekhna · 内部系统</footer>
      </div>
    </main>
  );
}
