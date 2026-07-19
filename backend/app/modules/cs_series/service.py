"""Security-sensitive helpers for the public CS ingress endpoint."""

from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from threading import Lock
from time import monotonic
from typing import Any
from urllib.parse import urlsplit

from pydantic import ValidationError
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ...models.security import SecurityRateLimitBucket
from ...repositories.security import register_rate_limit_attempt
from .schemas import CSChannel, CSInboundPayload, CSStatus

MINUTE_LIMIT = 5
HOUR_LIMIT = 20
MINUTE_SECONDS = 60.0
HOUR_SECONDS = 3600.0
MAX_TRACKED_IPS = 20_000


class InboundValidationError(ValueError):
    pass


class _PlainTextParser(HTMLParser):
    _BLOCK_TAGS = frozenset(
        {
            "address",
            "article",
            "blockquote",
            "br",
            "div",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "hr",
            "li",
            "p",
            "pre",
            "section",
            "table",
            "tr",
        }
    )
    _SKIP_TAGS = frozenset({"script", "style", "template"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        lowered = tag.lower()
        if lowered in self._SKIP_TAGS:
            self.skip_depth += 1
        elif self.skip_depth == 0 and lowered in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in self._SKIP_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
        elif self.skip_depth == 0 and lowered in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth == 0:
            self.parts.append(data)


def plain_text(value: str, *, multiline: bool = False) -> str:
    parser = _PlainTextParser()
    try:
        parser.feed(value)
        parser.close()
        rendered = "".join(parser.parts)
    except Exception:
        rendered = re.sub(r"<[^>]*>", " ", value)
    rendered = rendered.replace("\x00", "")
    if not multiline:
        return re.sub(r"\s+", " ", rendered).strip()
    lines = [re.sub(r"[\t\f\v ]+", " ", line).strip() for line in rendered.splitlines()]
    compact: list[str] = []
    for line in lines:
        if line or (compact and compact[-1]):
            compact.append(line)
    return "\n".join(compact).strip()


def _valid_email(value: str) -> bool:
    if (
        len(value) > 254
        or value.count("@") != 1
        or any(ch.isspace() for ch in value)
    ):
        return False
    local, domain = value.rsplit("@", 1)
    if not local or len(local) > 64 or local.startswith(".") or local.endswith("."):
        return False
    if (
        ".." in local
        or not domain
        or domain.startswith(".")
        or domain.endswith(".")
    ):
        return False
    if re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+", local) is None:
        return False
    try:
        ascii_domain = domain.encode("idna").decode("ascii")
    except UnicodeError:
        return False
    if len(ascii_domain) > 253 or "." not in ascii_domain:
        return False
    labels = ascii_domain.split(".")
    return all(
        label
        and len(label) <= 63
        and not label.startswith("-")
        and not label.endswith("-")
        and re.fullmatch(r"[A-Za-z0-9-]+", label) is not None
        for label in labels
    )


def _optional(value: str, *, multiline: bool = False) -> str | None:
    cleaned = plain_text(value, multiline=multiline)
    return cleaned or None


def _source_url(value: str) -> str | None:
    cleaned = _optional(value)
    if cleaned is None:
        return None
    parsed = urlsplit(cleaned)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise InboundValidationError("invalid source URL")
    return cleaned


@dataclass(frozen=True)
class NormalizedInbound:
    channel: CSChannel
    name: str
    email: str
    company: str | None
    order_number: str | None
    message: str
    source_url: str | None
    status: CSStatus


def normalize_inbound(raw: Any) -> NormalizedInbound:
    try:
        payload = CSInboundPayload.model_validate(raw)
    except ValidationError as exc:
        raise InboundValidationError("invalid inbound payload") from exc

    email = plain_text(payload.email)
    message = plain_text(payload.message, multiline=True)
    if not _valid_email(email):
        raise InboundValidationError("invalid email")
    if not message or len(message) > 5000:
        raise InboundValidationError("invalid message")

    return NormalizedInbound(
        channel=payload.channel,
        name=plain_text(payload.name),
        email=email,
        company=_optional(payload.company),
        order_number=_optional(payload.order_number),
        message=message,
        source_url=_source_url(payload.source_url),
        status="spam"
        if payload.form_ms is not None and payload.form_ms < 3000
        else "new",
    )


class CSInboundRateLimiter:
    """Process-local fixed-window limits backed by timestamp deques."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._last_sweep = 0.0

    def allow(self, client_ip: str, *, now: float | None = None) -> bool:
        timestamp = monotonic() if now is None else now
        with self._lock:
            if timestamp - self._last_sweep >= MINUTE_SECONDS:
                hour_cutoff = timestamp - HOUR_SECONDS
                stale_keys = [
                    key
                    for key, values in self._attempts.items()
                    if not values or values[-1] <= hour_cutoff
                ]
                for key in stale_keys:
                    self._attempts.pop(key, None)
                self._last_sweep = timestamp
            if (
                client_ip not in self._attempts
                and len(self._attempts) >= MAX_TRACKED_IPS
            ):
                self._attempts.pop(next(iter(self._attempts)), None)
            attempts = self._attempts[client_ip]
            hour_cutoff = timestamp - HOUR_SECONDS
            while attempts and attempts[0] <= hour_cutoff:
                attempts.popleft()
            minute_cutoff = timestamp - MINUTE_SECONDS
            minute_count = sum(item > minute_cutoff for item in attempts)
            if minute_count >= MINUTE_LIMIT or len(attempts) >= HOUR_LIMIT:
                if not attempts:
                    self._attempts.pop(client_ip, None)
                return False
            attempts.append(timestamp)
            return True

    def reset(self) -> None:
        with self._lock:
            self._attempts.clear()
            self._last_sweep = 0.0


def register_shared_inbound_rate_limit(
    db: Session,
    client_ip: str,
    *,
    now: datetime | None = None,
) -> bool:
    """Consume the process-shared minute and hour buckets for one IP."""

    checked_at = now or datetime.now(UTC)
    db.execute(
        delete(SecurityRateLimitBucket).where(
            SecurityRateLimitBucket.scope.in_(
                ("cs_ip_minute", "cs_ip_hour")
            ),
            SecurityRateLimitBucket.expires_at <= checked_at,
        )
    )
    minute = register_rate_limit_attempt(
        db,
        scope="cs_ip_minute",
        identifier=client_ip,
        endpoint_key="cs.inbound",
        limit=MINUTE_LIMIT,
        window_seconds=int(MINUTE_SECONDS),
        now=checked_at,
    )
    if not minute.allowed:
        return False
    hour = register_rate_limit_attempt(
        db,
        scope="cs_ip_hour",
        identifier=client_ip,
        endpoint_key="cs.inbound",
        limit=HOUR_LIMIT,
        window_seconds=int(HOUR_SECONDS),
        now=checked_at,
    )
    return hour.allowed


inbound_rate_limiter = CSInboundRateLimiter()


def reset_inbound_rate_limiter() -> None:
    inbound_rate_limiter.reset()


__all__ = [
    "CSInboundRateLimiter",
    "HOUR_LIMIT",
    "InboundValidationError",
    "MINUTE_LIMIT",
    "NormalizedInbound",
    "inbound_rate_limiter",
    "normalize_inbound",
    "plain_text",
    "register_shared_inbound_rate_limit",
    "reset_inbound_rate_limiter",
]
