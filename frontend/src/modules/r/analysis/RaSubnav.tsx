"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/r-a/live", label: "选品直播间" },
  { href: "/r-a/groups", label: "选品分组" },
  { href: "/r-a/analysis", label: "定向探测" },
];

export function RaSubnav() {
  const pathname = usePathname();
  return (
    <nav
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: 8,
        marginBottom: 4,
      }}
      aria-label="R-A 子页面"
    >
      {LINKS.map((link) => {
        const active = pathname?.startsWith(link.href);
        return (
          <Link
            key={link.href}
            href={link.href}
            style={{
              border: `1px solid ${active ? "#2dd4cd" : "var(--color-line)"}`,
              color: active ? "#2dd4cd" : "var(--color-muted)",
              background: active ? "rgba(45, 212, 205, 0.07)" : "transparent",
              borderRadius: 999,
              padding: "5px 14px",
              fontSize: "0.78rem",
              fontWeight: 700,
              textDecoration: "none",
            }}
          >
            {link.label}
          </Link>
        );
      })}
    </nav>
  );
}
