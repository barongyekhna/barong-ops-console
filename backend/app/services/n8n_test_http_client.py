import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
)


class N8nTestWebhookRequestError(RuntimeError):
    pass


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        return None


def send_n8n_test_webhook(
    *,
    url: str,
    payload: dict[str, Any],
    timeout_seconds: int,
) -> int:
    request = Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "barong-ops-console-n8n-test-bridge",
        },
        method="POST",
    )
    opener = build_opener(_RejectRedirects())

    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            status_code = int(response.getcode())
    except (HTTPError, URLError, OSError, TimeoutError) as exc:
        raise N8nTestWebhookRequestError(
            "The configured n8n test webhook request failed."
        ) from exc

    if not 200 <= status_code < 300:
        raise N8nTestWebhookRequestError(
            "The configured n8n test webhook returned a non-success status."
        )
    return status_code
