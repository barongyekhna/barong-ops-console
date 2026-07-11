"""Signed opaque cursor codec scoped to a user and query kind."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Literal


CursorKind = Literal["records_older", "records_after", "events"]


class InvalidCursorError(ValueError):
    """A cursor is malformed, expired, tampered with, or used out of scope."""


@dataclass(frozen=True, slots=True)
class DecodedCursor:
    kind: CursorKind
    position: int


def _encode_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_bytes(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except Exception as exc:
        raise InvalidCursorError("invalid cursor") from exc


@dataclass(frozen=True, slots=True)
class CursorCodec:
    secret: str
    ttl_seconds: int

    def encode(self, *, kind: CursorKind, scope: str, position: int) -> str:
        payload = json.dumps(
            {
                "v": 1,
                "k": kind,
                "s": scope,
                "p": position,
                "exp": int(time.time()) + self.ttl_seconds,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        signature = hmac.new(
            self.secret.encode("utf-8"), payload, hashlib.sha256
        ).digest()
        return f"{_encode_bytes(payload)}.{_encode_bytes(signature)}"

    def decode(
        self,
        token: str,
        *,
        kinds: tuple[CursorKind, ...],
        scope: str,
    ) -> DecodedCursor:
        try:
            encoded_payload, encoded_signature = token.split(".", 1)
            payload = _decode_bytes(encoded_payload)
            signature = _decode_bytes(encoded_signature)
            expected = hmac.new(
                self.secret.encode("utf-8"), payload, hashlib.sha256
            ).digest()
            if not hmac.compare_digest(signature, expected):
                raise InvalidCursorError("invalid cursor")
            data = json.loads(payload)
            if (
                data.get("v") != 1
                or data.get("k") not in kinds
                or data.get("s") != scope
                or not isinstance(data.get("p"), int)
                or data["p"] < 0
                or not isinstance(data.get("exp"), int)
                or data["exp"] < int(time.time())
            ):
                raise InvalidCursorError("invalid cursor")
            return DecodedCursor(kind=data["k"], position=data["p"])
        except InvalidCursorError:
            raise
        except Exception as exc:
            raise InvalidCursorError("invalid cursor") from exc
