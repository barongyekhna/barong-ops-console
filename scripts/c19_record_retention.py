#!/usr/bin/env python3
"""Bounded, resumable C19 Record + Asset retention coordinator.

Dry-run is the default. Record deletion is durably idempotent by stable policy
operation ID and batch ordinal. Removed asset references enter a Record outbox;
this coordinator leases only currently unreferenced jobs, asks Asset to verify
the exact committed chat binding, and acknowledges only after Asset has made
the deletion durable as ``delete_pending`` (or returned a protected result).
No response body is ever printed.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import ipaddress
import json
import os
import re
import stat
import sys
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlsplit


IDENTIFIER = re.compile(r"^[^\x00-\x1f\x7f]{1,128}$")
ASSET_ID = re.compile(r"^att_[0-9a-f]{32}$")
UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
PROTOCOL = "record-asset-retention-v2-two-phase"
ASSET_DISPATCH_SCOPE = "all-eligible-record-outbox"
PRIVATE_SERVICE_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
)


class RetentionError(RuntimeError):
    pass


class RetentionIncompleteError(RetentionError):
    """A safety bound was reached; durable state remains for the next run."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        return None


_PROXY_HANDLER = urllib.request.ProxyHandler({})
_SECURE_OPENER = urllib.request.build_opener(
    _PROXY_HANDLER,
    _NoRedirect(),
)


def _secure_urlopen(request: urllib.request.Request, *, timeout: int):
    return _SECURE_OPENER.open(request, timeout=timeout)


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    record_url: str
    asset_url: str
    requested_by_user_id: str
    reason: str
    delete_before: datetime
    conversation_id: str | None
    batch_size: int
    maximum_records: int
    maximum_asset_jobs: int
    maximum_dispatch_jobs: int
    minimum_age_days: int
    allow_public_https: bool

    @property
    def operation_id(self) -> str:
        evidence = {
            "approved_maximum_asset_jobs": self.maximum_asset_jobs,
            "approved_maximum_records": self.maximum_records,
            "conversation_id": self.conversation_id,
            "delete_before": self.delete_before.isoformat(),
            "reason": self.reason,
            "requested_by_user_id": self.requested_by_user_id,
        }
        digest = hashlib.sha256(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return f"rtn_{digest}"

    @property
    def confirmation(self) -> str:
        evidence = {
            "asset_dispatch_scope": ASSET_DISPATCH_SCOPE,
            "asset_url": self.asset_url,
            "batch_size": self.batch_size,
            "maximum_asset_jobs": self.maximum_asset_jobs,
            "maximum_dispatch_jobs": self.maximum_dispatch_jobs,
            "minimum_age_days": self.minimum_age_days,
            "operation_id": self.operation_id,
            "record_url": self.record_url,
            "allow_public_https": self.allow_public_https,
            "protocol": PROTOCOL,
        }
        digest = hashlib.sha256(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return f"RETENTION/{digest}"


@dataclass(frozen=True, slots=True)
class RetentionResult:
    affected_records: int
    record_batches: int
    accepted_assets: int
    protected_assets: int
    asset_claims: int
    blocked_assets: int


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RetentionError("--delete-before must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RetentionError("--delete-before must include a UTC offset")
    return parsed.astimezone(UTC)


def _base_url(value: str, option: str, *, allow_public_https: bool) -> str:
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise RetentionError(f"{option} has an invalid port") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise RetentionError(f"{option} must be a credential-free HTTP(S) origin")
    if port is not None and not 1 <= port <= 65535:
        raise RetentionError(f"{option} has an invalid port")
    hostname = parsed.hostname
    assert hostname is not None
    internal = (
        hostname == "localhost"
        or "." not in hostname
        or hostname.endswith(
            (".localhost", ".internal", ".local", ".svc", ".svc.cluster.local")
        )
    )
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None:
        internal = address.is_loopback or any(
            address.version == network.version and address in network
            for network in PRIVATE_SERVICE_NETWORKS
        )
    if not internal and parsed.scheme != "https":
        raise RetentionError(f"{option} refuses plaintext transport to a public host")
    if not internal and not allow_public_https:
        raise RetentionError(
            f"{option} public HTTPS requires explicit --allow-public-https"
        )
    return value.rstrip("/")


def build_policy(
    args: argparse.Namespace, *, now: datetime | None = None
) -> RetentionPolicy:
    current = now or datetime.now(UTC)
    delete_before = _timestamp(args.delete_before)
    if not 1 <= args.minimum_age_days <= 3650:
        raise RetentionError("--minimum-age-days must be between 1 and 3650")
    if delete_before > current - timedelta(days=args.minimum_age_days):
        raise RetentionError("retention cutoff violates the configured minimum age")
    if not 1 <= args.batch_size <= 1000:
        raise RetentionError("--batch-size must be between 1 and 1000")
    if not 1 <= args.maximum_records <= 100_000:
        raise RetentionError("--maximum-records must be between 1 and 100000")
    if not 1 <= args.maximum_asset_jobs <= 100_000:
        raise RetentionError("--maximum-asset-jobs must be between 1 and 100000")
    if not 1 <= args.maximum_dispatch_jobs <= 100_000:
        raise RetentionError("--maximum-dispatch-jobs must be between 1 and 100000")
    if IDENTIFIER.fullmatch(args.requested_by_user_id) is None:
        raise RetentionError("--requested-by-user-id is invalid")
    if (
        args.conversation_id is not None
        and IDENTIFIER.fullmatch(args.conversation_id) is None
    ):
        raise RetentionError("--conversation-id is invalid")
    if (
        not 3 <= len(args.reason) <= 500
        or args.reason != args.reason.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in args.reason)
    ):
        raise RetentionError("--reason is invalid")
    return RetentionPolicy(
        record_url=_base_url(
            args.record_url,
            "--record-url",
            allow_public_https=args.allow_public_https,
        ),
        asset_url=_base_url(
            args.asset_url,
            "--asset-url",
            allow_public_https=args.allow_public_https,
        ),
        requested_by_user_id=args.requested_by_user_id,
        reason=args.reason,
        delete_before=delete_before,
        conversation_id=args.conversation_id,
        batch_size=args.batch_size,
        maximum_records=args.maximum_records,
        maximum_asset_jobs=args.maximum_asset_jobs,
        maximum_dispatch_jobs=args.maximum_dispatch_jobs,
        minimum_age_days=args.minimum_age_days,
        allow_public_https=args.allow_public_https,
    )


def _token(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RetentionError(
            "service token file must be a regular non-symlink file"
        ) from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise RetentionError(
                "service token file must be a regular non-symlink file"
            )
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise RetentionError(
                "service token file must not be group/world accessible"
            )
        if not 32 <= metadata.st_size <= 4097:
            raise RetentionError("service token file size is invalid")
        chunks: list[bytes] = []
        remaining = metadata.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 4097))
            if not chunk:
                raise RetentionError("service token file changed while reading")
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) != metadata.st_size:
            raise RetentionError("service token file changed while reading")
        if payload.endswith(b"\n"):
            payload = payload[:-1]
        if not 32 <= len(payload) <= 4096:
            raise RetentionError("service token file is unexpectedly large")
        try:
            value = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RetentionError("service token file is not valid UTF-8") from exc
    finally:
        os.close(descriptor)
    if (
        value != value.strip()
        or any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise RetentionError("service token must be one whitespace-free line")
    if len(value) < 32 or "CHANGE-ME" in value.upper():
        raise RetentionError("service token is missing or unsafe")
    return value


def _post_json(
    url: str,
    token: str,
    body: dict[str, Any],
    *,
    opener: Callable[..., Any],
) -> dict[str, Any]:
    try:
        request = urllib.request.Request(
            url,
            data=json.dumps(body, separators=(",", ":")).encode(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with opener(request, timeout=30) as response:
            status = int(response.status)
            raw = response.read(64 * 1024)
    except urllib.error.HTTPError as exc:
        raise RetentionError(f"retention dependency returned HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RetentionError("retention dependency is unavailable") from exc
    except (ValueError, UnicodeError) as exc:
        raise RetentionError("retention request could not be encoded safely") from exc
    if status != 200:
        raise RetentionError(f"retention dependency returned HTTP {status}")
    try:
        result = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RetentionError("retention dependency returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise RetentionError("retention dependency returned an unexpected shape")
    return result


def _drain_asset_jobs(
    policy: RetentionPolicy,
    record_token: str,
    asset_token: str,
    *,
    worker_id: str,
    budget: int,
    opener: Callable[..., Any],
) -> tuple[int, int, int, int]:
    accepted = protected = claims = blocked = 0
    while accepted + protected < budget:
        claim_limit = min(100, budget - accepted - protected)
        result = _post_json(
            f"{policy.record_url}/v1/retention/asset-deletions/claim",
            record_token,
            {
                "worker_id": worker_id,
                "requested_at": datetime.now(UTC).isoformat(),
                "limit": claim_limit,
                "lease_seconds": 120,
            },
            opener=opener,
        )
        if set(result) != {
            "jobs",
            "eligible_count",
            "blocked_count",
            "leased_count",
        }:
            raise RetentionError("Record asset claim response has an unexpected shape")
        jobs = result["jobs"]
        if (
            not isinstance(jobs, list)
            or len(jobs) > claim_limit
            or not isinstance(result["eligible_count"], int)
            or isinstance(result["eligible_count"], bool)
            or result["eligible_count"] < len(jobs)
            or not isinstance(result["blocked_count"], int)
            or isinstance(result["blocked_count"], bool)
            or result["blocked_count"] < 0
            or not isinstance(result["leased_count"], int)
            or isinstance(result["leased_count"], bool)
            or result["leased_count"] < 0
        ):
            raise RetentionError("Record asset claim response is invalid")
        blocked = result["blocked_count"]
        if not jobs:
            if result["leased_count"]:
                raise RetentionError(
                    "eligible asset deletion jobs are leased; retry after lease expiry"
                )
            return accepted, protected, claims, blocked
        claims += 1
        for job in jobs:
            if (
                not isinstance(job, dict)
                or set(job) != {
                    "job_id",
                    "asset_id",
                    "record_id",
                    "conversation_id",
                    "phase",
                }
                or not isinstance(job["job_id"], str)
                or UUID.fullmatch(job["job_id"]) is None
                or not isinstance(job["asset_id"], str)
                or ASSET_ID.fullmatch(job["asset_id"]) is None
                or not isinstance(job["record_id"], str)
                or not 1 <= len(job["record_id"]) <= 36
                or not isinstance(job["conversation_id"], str)
                or IDENTIFIER.fullmatch(job["conversation_id"]) is None
                or job["phase"] not in {"prepare", "commit"}
            ):
                raise RetentionError("Record asset deletion job is invalid")
            asset_body = {
                "operation_id": job["job_id"],
                "record_id": job["record_id"],
                "conversation_id": job["conversation_id"],
                "requested_at": datetime.now(UTC).isoformat(),
            }
            if job["phase"] == "prepare":
                preparation = _post_json(
                    f"{policy.asset_url}/v1/retention/chat-assets/"
                    f"{quote(job['asset_id'], safe='')}/prepare",
                    asset_token,
                    asset_body,
                    opener=opener,
                )
                if set(preparation) != {"asset_id", "disposition", "status"}:
                    raise RetentionError(
                        "Asset retention preparation has an unexpected shape"
                    )
                if preparation.get("asset_id") != job["asset_id"] or not (
                    preparation.get("disposition") == "accepted"
                    and preparation.get("status") == "prepared"
                    or preparation.get("disposition") == "protected"
                    and preparation.get("status") == "retained"
                ):
                    raise RetentionError("Asset retention preparation is invalid")
                if preparation["disposition"] == "protected":
                    disposition = "protected"
                else:
                    authorization = _post_json(
                        f"{policy.record_url}/v1/retention/asset-deletions/"
                        f"{quote(job['job_id'], safe='')}/authorize",
                        record_token,
                        {
                            "worker_id": worker_id,
                            "authorized_at": datetime.now(UTC).isoformat(),
                        },
                        opener=opener,
                    )
                    if authorization not in (
                        {"job_id": job["job_id"], "state": "authorized"},
                        {"job_id": job["job_id"], "state": "blocked"},
                    ):
                        raise RetentionError(
                            "Record asset authorization response is invalid"
                        )
                    if authorization["state"] == "blocked":
                        blocked += 1
                        continue
                    disposition = "accepted"
            else:
                disposition = "accepted"

            if disposition == "accepted":
                asset_result = _post_json(
                    f"{policy.asset_url}/v1/retention/chat-assets/"
                    f"{quote(job['asset_id'], safe='')}/commit",
                    asset_token,
                    asset_body,
                    opener=opener,
                )
                if set(asset_result) != {"asset_id", "disposition", "status"}:
                    raise RetentionError(
                        "Asset retention commit has an unexpected shape"
                    )
                if (
                    asset_result.get("asset_id") != job["asset_id"]
                    or asset_result.get("disposition") != "accepted"
                    or asset_result.get("status")
                    not in {"delete_pending", "deleted"}
                ):
                    raise RetentionError("Asset retention commit is invalid")
            acknowledged = _post_json(
                f"{policy.record_url}/v1/retention/asset-deletions/"
                f"{quote(job['job_id'], safe='')}/complete",
                record_token,
                {
                    "worker_id": worker_id,
                    "outcome": disposition,
                    "completed_at": datetime.now(UTC).isoformat(),
                },
                opener=opener,
            )
            expected_state = "completed" if disposition == "accepted" else "protected"
            if acknowledged != {
                "job_id": job["job_id"],
                "state": expected_state,
                "outcome": disposition,
            }:
                raise RetentionError("Record asset acknowledgement is invalid")
            if disposition == "accepted":
                accepted += 1
            else:
                protected += 1
        if result["eligible_count"] == len(jobs):
            if result["leased_count"]:
                raise RetentionError(
                    "eligible asset deletion jobs are leased; retry after lease expiry"
                )
            return accepted, protected, claims, blocked
    raise RetentionIncompleteError(
        "maximum asset jobs reached; rerun the identical confirmed operation"
    )


def run_retention(
    policy: RetentionPolicy,
    record_token: str,
    asset_token: str,
    *,
    opener: Callable[..., Any] | None = None,
) -> RetentionResult:
    opener = opener or _secure_urlopen
    worker_id = f"retention-{uuid.uuid4().hex}"
    accepted = protected = claims = blocked = 0
    ordinal = 0
    affected = 0
    batches = 0
    while affected < policy.maximum_records:
        maximum = min(policy.batch_size, policy.maximum_records - affected)
        body: dict[str, Any] = {
            "operation_id": policy.operation_id,
            "batch_ordinal": ordinal,
            "approved_maximum_records": policy.maximum_records,
            "approved_maximum_asset_jobs": policy.maximum_asset_jobs,
            "requested_by_user_id": policy.requested_by_user_id,
            "reason": policy.reason,
            "requested_at": datetime.now(UTC).isoformat(),
            "delete_before": policy.delete_before.isoformat(),
            "maximum_records": maximum,
        }
        if policy.conversation_id is not None:
            body["conversation_id"] = policy.conversation_id
        result = _post_json(
            f"{policy.record_url}/v1/retention/apply",
            record_token,
            body,
            opener=opener,
        )
        if set(result) != {
            "operation_id",
            "batch_ordinal",
            "affected_count",
            "cumulative_affected_count",
            "operation_complete",
            "completed_at",
        }:
            raise RetentionError("Record retention response has an unexpected shape")
        batch_affected = result["affected_count"]
        cumulative = result["cumulative_affected_count"]
        if (
            result["operation_id"] != policy.operation_id
            or result["batch_ordinal"] != ordinal
            or not isinstance(batch_affected, int)
            or isinstance(batch_affected, bool)
            or not 0 <= batch_affected <= maximum
            or not isinstance(cumulative, int)
            or isinstance(cumulative, bool)
            or not batch_affected <= cumulative <= policy.maximum_records
            or not isinstance(result["operation_complete"], bool)
            or not isinstance(result["completed_at"], str)
        ):
            raise RetentionError("Record retention response is invalid")
        _timestamp(result["completed_at"])
        affected = cumulative
        batches += 1
        remaining_asset_budget = policy.maximum_dispatch_jobs - accepted - protected
        if remaining_asset_budget <= 0:
            raise RetentionIncompleteError(
                "maximum asset jobs reached; rerun the identical confirmed operation"
            )
        newly_accepted, newly_protected, new_claims, blocked = _drain_asset_jobs(
            policy,
            record_token,
            asset_token,
            worker_id=worker_id,
            budget=remaining_asset_budget,
            opener=opener,
        )
        accepted += newly_accepted
        protected += newly_protected
        claims += new_claims
        if result["operation_complete"]:
            break
        if accepted + protected >= policy.maximum_dispatch_jobs:
            raise RetentionIncompleteError(
                "maximum dispatch jobs reached before another record batch"
            )
        ordinal += 1
    return RetentionResult(
        affected_records=affected,
        record_batches=batches,
        accepted_assets=accepted,
        protected_assets=protected,
        asset_claims=claims,
        blocked_assets=blocked,
    )


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(prog="c19-record-retention")
    value.add_argument("--record-url", required=True)
    value.add_argument("--asset-url", required=True)
    value.add_argument("--record-service-token-file", type=Path)
    value.add_argument("--asset-service-token-file", type=Path)
    value.add_argument("--requested-by-user-id", required=True)
    value.add_argument("--reason", required=True)
    value.add_argument("--delete-before", required=True)
    value.add_argument("--conversation-id")
    value.add_argument("--minimum-age-days", type=int, default=30)
    value.add_argument("--batch-size", type=int, default=1000)
    value.add_argument("--maximum-records", type=int, default=10_000)
    value.add_argument("--maximum-asset-jobs", type=int, default=10_000)
    value.add_argument("--maximum-dispatch-jobs", type=int, default=10_000)
    value.add_argument(
        "--allow-public-https",
        action="store_true",
        help="explicitly permit credential-bearing calls to public HTTPS origins",
    )
    mode = value.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    return value


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        policy = build_policy(args)
        print("C19 coordinated Record + Asset retention plan")
        print(f"mode: {'execute' if args.execute else 'dry-run'}")
        print(f"protocol: {PROTOCOL}")
        print(f"record_url: {policy.record_url}")
        print(f"asset_url: {policy.asset_url}")
        print(f"delete_before: {policy.delete_before.isoformat()}")
        print(f"conversation_scope: {policy.conversation_id or 'all-records'}")
        print(f"asset_dispatch_scope: {ASSET_DISPATCH_SCOPE}")
        print(f"batch_size: {policy.batch_size}")
        print(f"maximum_records: {policy.maximum_records}")
        print(f"maximum_asset_jobs: {policy.maximum_asset_jobs}")
        print(f"maximum_dispatch_jobs: {policy.maximum_dispatch_jobs}")
        print(f"minimum_age_days: {policy.minimum_age_days}")
        print(f"operation_id: {policy.operation_id}")
        print(f"required_confirmation: {policy.confirmation}")
        if not args.execute:
            print("No HTTP request, record mutation, or asset mutation was performed.")
            return 0
        if not hmac.compare_digest(
            os.getenv("CONFIRM_C19_RECORD_RETENTION", ""), policy.confirmation
        ):
            raise RetentionError(
                "CONFIRM_C19_RECORD_RETENTION does not match the printed plan"
            )
        if args.record_service_token_file is None:
            raise RetentionError(
                "--record-service-token-file is required for execution"
            )
        if args.asset_service_token_file is None:
            raise RetentionError(
                "--asset-service-token-file is required for execution"
            )
        record_token = _token(args.record_service_token_file)
        asset_token = _token(args.asset_service_token_file)
        if hmac.compare_digest(record_token, asset_token):
            raise RetentionError("Record and Asset service tokens must be distinct")
        result = run_retention(policy, record_token, asset_token)
        print("C19 coordinated retention completed")
        print(f"affected_records: {result.affected_records}")
        print(f"record_batches: {result.record_batches}")
        print(f"accepted_assets: {result.accepted_assets}")
        print(f"protected_assets: {result.protected_assets}")
        print(f"asset_claims: {result.asset_claims}")
        print(f"blocked_assets: {result.blocked_assets}")
        return 0
    except RetentionIncompleteError as exc:
        print(f"C19 coordinated retention incomplete: {exc}", file=sys.stderr)
        return 2
    except RetentionError as exc:
        print(f"C19 coordinated retention failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
