"use client";

import { ArrowRight, LoaderCircle, LockKeyhole, UserRound } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState, type FormEvent } from "react";

import { useAuth } from "@/components/auth-provider";
import { ApiError, ApiRequestAbortedError, ApiTimeoutError } from "@/lib/api";

import styles from "./login.module.css";

const LOGIN_AUTH_ERROR = "登录失败，请检查账号和密码。";
const LOGIN_BACKEND_ERROR = "登录服务暂未响应，请重试。";
const LOGIN_ERROR = "登录未完成，请重试。";
const LOGIN_REQUEST_TIMEOUT_MS = 8_000;

function isBackendLoginFailure(error: unknown) {
  return (
    error instanceof ApiTimeoutError ||
    error instanceof ApiRequestAbortedError ||
    (error instanceof ApiError && error.status !== 401) ||
    error instanceof TypeError
  );
}

export function LoginForm() {
  const router = useRouter();
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const isSubmittingRef = useRef(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isSubmittingRef.current) {
      return;
    }
    isSubmittingRef.current = true;
    setError("");
    setIsSubmitting(true);
    try {
      const result = await login(username.trim(), password, {
        timeoutMs: LOGIN_REQUEST_TIMEOUT_MS,
      });
      router.replace(
        result.requirePasswordChange ? "/force-password-reset" : "/dashboard",
      );
    } catch (loginError) {
      if (loginError instanceof ApiError && loginError.status === 401) {
        setError(LOGIN_AUTH_ERROR);
      } else if (isBackendLoginFailure(loginError)) {
        setError(LOGIN_BACKEND_ERROR);
      } else {
        setError(LOGIN_ERROR);
      }
    } finally {
      isSubmittingRef.current = false;
      setIsSubmitting(false);
    }
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      <div className={styles.field}>
        <label htmlFor="username">用户名</label>
        <div className={styles.inputShell}>
          <input
            autoComplete="username"
            autoFocus
            id="username"
            name="username"
            onChange={(event) => setUsername(event.target.value)}
            placeholder="请输入用户名"
            required
            type="text"
            value={username}
          />
          <span className={styles.icon}>
            <UserRound aria-hidden="true" size={17} />
          </span>
        </div>
      </div>

      <div className={styles.field}>
        <label htmlFor="password">密码</label>
        <div className={styles.inputShell}>
          <input
            autoComplete="current-password"
            id="password"
            name="password"
            onChange={(event) => setPassword(event.target.value)}
            placeholder="••••••••••••"
            required
            type="password"
            value={password}
          />
          <span className={styles.icon}>
            <LockKeyhole aria-hidden="true" size={17} />
          </span>
        </div>
      </div>

      <div aria-live="polite" className={styles.message}>
        {error}
      </div>

      <button className={styles.submit} disabled={isSubmitting} type="submit">
        {isSubmitting ? (
          <LoaderCircle className="spin" aria-hidden="true" size={17} />
        ) : (
          <ArrowRight aria-hidden="true" size={17} />
        )}
        {isSubmitting ? "正在登录" : "登 录"}
      </button>
    </form>
  );
}
