"use client";

import { ArrowRight, LoaderCircle, LockKeyhole } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { useAuth } from "@/components/auth-provider";
import { ApiError } from "@/lib/api";

const DEFAULT_INITIAL_PASSWORD = "123456";
const PASSWORD_LENGTH_MESSAGE = "New password must be at least 12 characters.";

function messageFromError(error: unknown) {
  if (error instanceof ApiError || error instanceof Error) {
    return error.message || "Password could not be changed.";
  }
  return "Password could not be changed.";
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
    if (status === "authenticated" && !user?.must_change_password) {
      router.replace("/dashboard");
    }
  }, [router, status, user?.must_change_password]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");

    if (currentPassword !== DEFAULT_INITIAL_PASSWORD) {
      setError("Current password must match the initial default password.");
      return;
    }
    if (newPassword.length < 12) {
      setError(PASSWORD_LENGTH_MESSAGE);
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("New password and confirmation must match.");
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

  if (status !== "authenticated" || !user?.must_change_password) {
    return null;
  }

  return (
    <main className="force-reset-page">
      <section className="force-reset-panel" aria-label="Force password reset">
        <div className="force-reset-heading">
          <span className="force-reset-icon">
            <LockKeyhole aria-hidden="true" size={22} />
          </span>
          <div>
            <span className="eyebrow">Password reset</span>
            <h1>Change password</h1>
            <small>
              ⚠️ 首次登录默认密码为 123456，请修改后继续使用系统
            </small>
          </div>
        </div>

        <form className="force-reset-form" onSubmit={handleSubmit}>
          <label className="field-group">
            <span>Current password</span>
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
            <span>New password</span>
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
            <span>Confirm password</span>
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
            Continue
          </button>
        </form>
      </section>
    </main>
  );
}
