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
            <small>运营工作台</small>
          </span>
        </div>

        <div className="identity-copy">
          <span className="system-label">安全访问</span>
          <h1>运营工作台</h1>
          <div className="signal-line">
            <span />
            登录后进入你的组织空间
          </div>
        </div>

        <span className="build-label">Barong</span>
      </section>

      <section className="login-panel">
        <div className="login-panel-inner">
          <span className="eyebrow">登录</span>
          <h2>进入工作台</h2>
          <p className="login-intro">使用已分配的账号登录。</p>
          <LoginForm />
        </div>
      </section>
    </main>
  );
}
