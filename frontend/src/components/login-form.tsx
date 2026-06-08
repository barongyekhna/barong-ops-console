"use client";

import { ArrowRight, LoaderCircle, LockKeyhole, UserRound } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { useAuth } from "@/components/auth-provider";

const LOGIN_ERROR =
  "Unable to sign in. Check your credentials and try again.";

export function LoginForm() {
  const router = useRouter();
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);

    try {
      await login(username.trim(), password);
      router.replace("/dashboard");
    } catch {
      setError(LOGIN_ERROR);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <form className="login-form" onSubmit={handleSubmit}>
      <div className="field-group">
        <label htmlFor="username">Username</label>
        <div className="input-shell">
          <UserRound aria-hidden="true" size={18} />
          <input
            autoComplete="username"
            autoFocus
            id="username"
            name="username"
            onChange={(event) => setUsername(event.target.value)}
            required
            type="text"
            value={username}
          />
        </div>
      </div>

      <div className="field-group">
        <label htmlFor="password">Password</label>
        <div className="input-shell">
          <LockKeyhole aria-hidden="true" size={18} />
          <input
            autoComplete="current-password"
            id="password"
            name="password"
            onChange={(event) => setPassword(event.target.value)}
            required
            type="password"
            value={password}
          />
        </div>
      </div>

      <div aria-live="polite" className="form-message">
        {error}
      </div>

      <button
        className="login-button"
        disabled={isSubmitting}
        type="submit"
      >
        {isSubmitting ? (
          <LoaderCircle className="spin" aria-hidden="true" size={18} />
        ) : (
          <ArrowRight aria-hidden="true" size={18} />
        )}
        {isSubmitting ? "Signing in" : "Sign in"}
      </button>
    </form>
  );
}
