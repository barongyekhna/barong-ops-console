"""Single-attempt outbound delivery through the WordPress CS relay."""

from dataclasses import dataclass

import httpx

from ...core.config import Settings

CS_REPLY_TIMEOUT_SECONDS = 15.0
RETAIL_REPLY_SUBJECT = "Re: Your message to Barong Yekhna"
WHOLESALE_REPLY_SUBJECT = "Re: Your wholesale inquiry — Barong Yekhna"


class CSReplyDeliveryError(RuntimeError):
    """A safe, operator-readable summary of one failed delivery attempt."""

    def __init__(self, provider_note: str) -> None:
        normalized = " ".join(str(provider_note).split()).strip()
        self.provider_note = (normalized or "WordPress relay request failed.")[:300]
        super().__init__(self.provider_note)


@dataclass(frozen=True, slots=True)
class CSReplyTarget:
    email: str
    name: str
    channel: str


def reply_subject(channel: str) -> str:
    return (
        WHOLESALE_REPLY_SUBJECT
        if channel == "wholesale"
        else RETAIL_REPLY_SUBJECT
    )


def _relay_url(settings: Settings) -> str:
    raw = str(settings.cs_wp_send_url or "").strip()
    if not raw:
        raise CSReplyDeliveryError("WordPress reply relay is not configured.")
    try:
        parsed = httpx.URL(raw)
    except (TypeError, ValueError) as exc:
        raise CSReplyDeliveryError("WordPress reply relay URL is invalid.") from exc
    if (
        parsed.scheme != "https"
        or not parsed.host
        or parsed.username
        or parsed.password
    ):
        raise CSReplyDeliveryError(
            "WordPress reply relay must use a valid HTTPS URL."
        )
    return str(parsed)


def _shared_key(settings: Settings) -> str:
    secret = settings.cs_inbound_key
    value = secret.get_secret_value().strip() if secret is not None else ""
    if not value:
        raise CSReplyDeliveryError("WordPress reply relay key is not configured.")
    return value


def send_cs_reply_to_wp(
    *,
    settings: Settings,
    message: CSReplyTarget,
    body: str,
) -> None:
    """Send exactly once; callers durably record either outcome."""

    payload = {
        "to_email": message.email,
        "to_name": message.name,
        "subject": reply_subject(message.channel),
        "body_text": body,
        "channel": message.channel,
    }
    try:
        with httpx.Client(
            timeout=httpx.Timeout(CS_REPLY_TIMEOUT_SECONDS),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = client.post(
                _relay_url(settings),
                headers={
                    "Content-Type": "application/json",
                    "X-BY-CS-KEY": _shared_key(settings),
                },
                json=payload,
            )
    except httpx.TimeoutException as exc:
        raise CSReplyDeliveryError(
            "WordPress reply relay timed out after 15 seconds."
        ) from exc
    except httpx.RequestError as exc:
        raise CSReplyDeliveryError("WordPress reply relay request failed.") from exc

    if not response.is_success:
        raise CSReplyDeliveryError(
            f"WordPress reply relay returned HTTP {response.status_code}."
        )
    try:
        result = response.json()
    except ValueError as exc:
        raise CSReplyDeliveryError(
            "WordPress reply relay returned an invalid response."
        ) from exc
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise CSReplyDeliveryError("WordPress reply relay rejected the reply.")


__all__ = [
    "CS_REPLY_TIMEOUT_SECONDS",
    "CSReplyDeliveryError",
    "CSReplyTarget",
    "RETAIL_REPLY_SUBJECT",
    "WHOLESALE_REPLY_SUBJECT",
    "reply_subject",
    "send_cs_reply_to_wp",
]
