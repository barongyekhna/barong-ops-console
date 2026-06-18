from fastapi import Response

from .config import Settings
from .environments import is_production_like

CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "object-src 'none'",
        "img-src 'self' data:",
        "font-src 'self' data:",
        "style-src 'self' 'unsafe-inline'",
        "script-src 'self' 'unsafe-inline'",
        "connect-src 'self'",
        "frame-src 'none'",
    )
)
PERMISSIONS_POLICY = ", ".join(
    (
        "accelerometer=()",
        "camera=()",
        "geolocation=()",
        "gyroscope=()",
        "magnetometer=()",
        "microphone=()",
        "payment=()",
        "usb=()",
    )
)
HSTS_VALUE = "max-age=31536000; includeSubDomains"


def apply_security_headers(response: Response, *, settings: Settings) -> None:
    response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault(
        "Referrer-Policy",
        "strict-origin-when-cross-origin",
    )
    response.headers.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
    if is_production_like(settings):
        response.headers.setdefault("Strict-Transport-Security", HSTS_VALUE)
