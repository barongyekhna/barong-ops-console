"""Google Ads Keyword Planner client for R-A DTC SEO signals.

Fully gated by `google_ads_runtime_gate` (providers.py):
- key 已绑定 + Basic 审核通过 env + RA_GOOGLE_ADS_ENABLE_REAL_CALLS=true 才发真请求；
- 其余情况返回 None，调用方保留 pending/mock 状态，不影响漏斗。

Key payload (bound via api-key orchestration) is a JSON blob:
{"developer_token": "...", "client_id": "...", "client_secret": "...",
 "refresh_token": "...", "customer_id": "1234567890",
 "login_customer_id": "...(optional)"}
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
# Google 一年退役一轮 API 版本：v18 已死(404 HTML)，2026-07 实测 v21/v22 在役。
# 若再遇 404 HTML 就是版本又退役了，改这里或设 RA_GOOGLE_ADS_API_VERSION。
DEFAULT_GOOGLE_ADS_API_VERSION = "v22"
DEFAULT_TIMEOUT_SECONDS = 20.0


class GoogleKeywordPlannerError(RuntimeError):
    pass


class GoogleKeywordPlannerClient:
    def __init__(self, config: dict[str, Any]) -> None:
        self.developer_token = str(config.get("developer_token") or "").strip()
        self.client_id = str(config.get("client_id") or "").strip()
        self.client_secret = str(config.get("client_secret") or "").strip()
        self.refresh_token = str(config.get("refresh_token") or "").strip()
        self.customer_id = str(config.get("customer_id") or "").strip().replace("-", "")
        self.login_customer_id = (
            str(config.get("login_customer_id") or "").strip().replace("-", "")
        )
        self.api_version = str(
            config.get("api_version")
            or os.getenv("RA_GOOGLE_ADS_API_VERSION", DEFAULT_GOOGLE_ADS_API_VERSION)
        )

    @classmethod
    def from_secret_value(cls, value: str) -> "GoogleKeywordPlannerClient":
        try:
            payload = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        return cls(payload)

    def ready(self) -> bool:
        return all(
            (
                self.developer_token,
                self.client_id,
                self.client_secret,
                self.refresh_token,
                self.customer_id,
            )
        )

    def _access_token(self) -> str:
        body = urlencode(
            {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            }
        ).encode("utf-8")
        request = Request(
            GOOGLE_OAUTH_TOKEN_URL,
            data=body,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urlopen(request, timeout=_timeout_seconds()) as response:
                parsed = json.loads(response.read().decode("utf-8", errors="replace"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise GoogleKeywordPlannerError(
                f"Google OAuth 刷新失败：HTTP {exc.code} {detail}"
            ) from exc
        except URLError as exc:
            raise GoogleKeywordPlannerError(f"Google OAuth 网络失败：{exc.reason}") from exc
        token = str(parsed.get("access_token") or "").strip()
        if not token:
            raise GoogleKeywordPlannerError("Google OAuth 未返回 access_token。")
        return token

    def keyword_ideas(self, keyword: str, *, limit: int = 10) -> dict[str, Any]:
        """generateKeywordIdeas for one seed keyword (US / English)."""
        if not self.ready():
            raise GoogleKeywordPlannerError("Google Ads key 配置不完整。")
        cleaned = str(keyword or "").strip()
        if not cleaned:
            raise GoogleKeywordPlannerError("缺少关键词。")
        token = self._access_token()
        url = (
            f"https://googleads.googleapis.com/{self.api_version}/"
            f"customers/{self.customer_id}:generateKeywordIdeas"
        )
        payload = {
            "language": "languageConstants/1000",
            "geoTargetConstants": ["geoTargetConstants/2840"],
            "keywordSeed": {"keywords": [cleaned[:80]]},
            "pageSize": max(1, min(int(limit), 50)),
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "developer-token": self.developer_token,
            "Content-Type": "application/json",
        }
        if self.login_customer_id:
            headers["login-customer-id"] = self.login_customer_id
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers=headers,
        )
        try:
            with urlopen(request, timeout=_timeout_seconds()) as response:
                parsed = json.loads(response.read().decode("utf-8", errors="replace"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            raise GoogleKeywordPlannerError(
                f"Keyword Planner 调用失败：HTTP {exc.code} {detail}"
            ) from exc
        except URLError as exc:
            raise GoogleKeywordPlannerError(f"Keyword Planner 网络失败：{exc.reason}") from exc
        return _normalize_ideas(parsed, seed=cleaned)


def _normalize_ideas(parsed: Any, *, seed: str) -> dict[str, Any]:
    results = parsed.get("results") if isinstance(parsed, dict) else None
    ideas: list[dict[str, Any]] = []
    seed_metrics: dict[str, Any] | None = None
    for item in results or []:
        if not isinstance(item, dict):
            continue
        text_value = str(item.get("text") or "").strip()
        metrics = item.get("keywordIdeaMetrics")
        metrics = metrics if isinstance(metrics, dict) else {}
        idea = {
            "keyword": text_value,
            "avg_monthly_searches": _int_or_none(metrics.get("avgMonthlySearches")),
            "competition": metrics.get("competition"),
            "competition_index": _int_or_none(metrics.get("competitionIndex")),
            "cpc_low_micros": _int_or_none(metrics.get("lowTopOfPageBidMicros")),
            "cpc_high_micros": _int_or_none(metrics.get("highTopOfPageBidMicros")),
        }
        ideas.append(idea)
        if text_value.lower() == seed.lower():
            seed_metrics = idea
    if seed_metrics is None and ideas:
        seed_metrics = ideas[0]
    return {
        "seed_keyword": seed,
        "seed_metrics": seed_metrics,
        "ideas": ideas[:10],
        "idea_count": len(ideas),
        "source": "google_ads_keyword_planner",
    }


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _timeout_seconds() -> float:
    try:
        return max(5.0, min(float(os.getenv("RA_GOOGLE_ADS_TIMEOUT_SECONDS", "20")), 60.0))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
