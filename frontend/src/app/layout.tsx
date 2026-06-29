import type { Metadata } from "next";
import type { ReactNode } from "react";

import { Inter } from "next/font/google";

import { AuthProvider } from "@/components/auth-provider";

import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
});

export const metadata: Metadata = {
  title: {
    default: "Barong Operations",
    template: "%s | Barong Operations",
  },
  description: "Barong workspace operations interface.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
