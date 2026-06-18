"use client";

import { Blocks } from "lucide-react";

import { LoginForm } from "@/components/login-form";

export function LoginScreen() {
  return (
    <main className="login-page">
      <section className="login-identity">
        <div className="login-brand">
          <span className="brand-mark brand-mark-large">
            <Blocks aria-hidden="true" size={26} />
          </span>
          <span>
            <strong>Barong</strong>
            <small>Ops Console</small>
          </span>
        </div>

        <div className="identity-copy">
          <span className="system-label">CONTROL / FOUNDATION</span>
          <h1>Operational control starts here.</h1>
          <div className="signal-line">
            <span />
            Authenticated workspace
          </div>
        </div>

        <span className="build-label">F09 / Console shell</span>
      </section>

      <section className="login-panel">
        <div className="login-panel-inner">
          <span className="eyebrow">Secure access</span>
          <h2>Sign in to Barong</h2>
          <p className="login-intro">Use your initialized owner account.</p>
          <LoginForm />
        </div>
      </section>
    </main>
  );
}
