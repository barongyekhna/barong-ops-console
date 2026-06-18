"use client";

import { ArrowRight, LoaderCircle, LockKeyhole, UserRound } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState, type FormEvent } from "react";

import { useAuth } from "@/components/auth-provider";
import { ApiTimeoutError } from "@/lib/api";

const LOGIN_ERROR =
  "Unable to sign in. Check your credentials and try again.";
const LOGIN_TIMEOUT_ERROR =
  "Sign-in took longer than expected. Please try again.";
const LOGIN_REQUEST_TIMEOUT_MS = 5_000;

class LoginRequestTimeoutError extends Error {
  constructor() {
    super("The sign-in request timed out.");
    this.name = "LoginRequestTimeoutError";
  }
}

export function LoginForm() {
  const router = useRouter();
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const submissionIdRef = useRef(0);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const submissionId = submissionIdRef.current + 1;
    submissionIdRef.current = submissionId;
    const controller = new AbortController();
    let timeoutId: number | undefined;

    setError("");
    setIsSubmitting(true);

    try {
      const timeoutPromise = new Promise<never>((_, reject) => {
        timeoutId = window.setTimeout(() => {
          const timeoutError = new LoginRequestTimeoutError();
          controller.abort(timeoutError);
          reject(timeoutError);
        }, LOGIN_REQUEST_TIMEOUT_MS);
      });

      await Promise.race([
        login(username.trim(), password, {
          signal: controller.signal,
          timeoutMs: LOGIN_REQUEST_TIMEOUT_MS,
        }),
        timeoutPromise,
      ]);

      if (submissionIdRef.current !== submissionId) {
        return;
      }

      router.replace("/users");
    } catch (loginError) {
      if (submissionIdRef.current !== submissionId) {
        return;
      }

      if (
        loginError instanceof LoginRequestTimeoutError ||
        loginError instanceof ApiTimeoutError
      ) {
        setError(LOGIN_TIMEOUT_ERROR);
      } else {
        setError(LOGIN_ERROR);
      }
    } finally {
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId);
      }

      if (submissionIdRef.current === submissionId) {
        setIsSubmitting(false);
      }
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
