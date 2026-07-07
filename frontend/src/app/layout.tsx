import type { Metadata } from "next";
import type { CSSProperties, ReactNode } from "react";

import { AuthProvider } from "@/components/auth-provider";

import "./globals.css";

const rootStyle = {
  "--font-inter":
    'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
} as CSSProperties;

export const metadata: Metadata = {
  title: {
    default: "Barong Operations",
    template: "%s | Barong Operations",
  },
  description: "Barong workspace operations interface.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" style={rootStyle}>
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
