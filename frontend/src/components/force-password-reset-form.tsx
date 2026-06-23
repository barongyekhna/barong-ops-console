"use client";

import { ArrowRight, LoaderCircle, LockKeyhole } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { useAuth } from "@/components/auth-provider";
import { ApiError } from "@/lib/api";
import { requiresPasswordChange } from "@/lib/auth";

const DEFAULT_INITIAL_PASSWORD = "123456";
const PASSWORD_LENGTH_MESSAGE = "新密码至少需要 12 个字符。";

function messageFromError(error: unknown) {
  if (error instanceof ApiError && error.status === 401) {
    return "请重新登录后再操作。";
  }
  return "密码修改未完成，请重试。";
}

export function ForcePasswordResetForm() {
  const router = useRouter();
  const { changePassword, status, user } = useAuth();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (status === "unauthenticated") {
      router.replace("/login");
      return;
    }
    if (status === "authenticated" && !requiresPasswordChange(user)) {
      router.replace("/dashboard");
    }
  }, [router, status, user]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");

    if (currentPassword !== DEFAULT_INITIAL_PASSWORD) {
      setError("当前密码必须与初始密码一致。");
      return;
    }
    if (newPassword.length < 12) {
      setError(PASSWORD_LENGTH_MESSAGE);
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("两次输入的新密码必须一致。");
      return;
    }

    setIsSubmitting(true);
    try {
      await changePassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      router.replace("/dashboard");
    } catch (changeError) {
      setError(messageFromError(changeError));
    } finally {
      setIsSubmitting(false);
    }
  }

  if (status !== "authenticated" || !requiresPasswordChange(user)) {
    return null;
  }

  return (
    <main className="force-reset-page">
      <section className="force-reset-panel" aria-label="修改密码">
        <div className="force-reset-heading">
          <span className="force-reset-icon">
            <LockKeyhole aria-hidden="true" size={22} />
          </span>
          <div>
            <span className="eyebrow">密码重置</span>
            <h1>修改密码</h1>
            <small>
              首次登录默认密码为 123456，请修改后继续使用系统
            </small>
          </div>
        </div>

        <form className="force-reset-form" onSubmit={handleSubmit}>
          <label className="field-group">
            <span>当前密码</span>
            <span className="input-shell">
              <input
                autoComplete="current-password"
                onChange={(event) => setCurrentPassword(event.target.value)}
                required
                type="password"
                value={currentPassword}
              />
            </span>
          </label>

          <label className="field-group">
            <span>新密码</span>
            <span className="input-shell">
              <input
                autoComplete="new-password"
                minLength={12}
                onChange={(event) => setNewPassword(event.target.value)}
                required
                type="password"
                value={newPassword}
              />
            </span>
          </label>

          <label className="field-group">
            <span>确认新密码</span>
            <span className="input-shell">
              <input
                autoComplete="new-password"
                minLength={12}
                onChange={(event) => setConfirmPassword(event.target.value)}
                required
                type="password"
                value={confirmPassword}
              />
            </span>
          </label>

          <div aria-live="polite" className="form-message">
            {error}
          </div>

          <button
            className="primary-button"
            disabled={isSubmitting}
            type="submit"
          >
            {isSubmitting ? (
              <LoaderCircle className="spin" aria-hidden="true" size={18} />
            ) : (
              <ArrowRight aria-hidden="true" size={18} />
            )}
            继续
          </button>
        </form>
      </section>
    </main>
  );
}
