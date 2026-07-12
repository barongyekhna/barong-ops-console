from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from c19_record_service.repository import _expected_retention_operation_id
from c19_record_service.schemas import RetentionRequest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "c19_record_retention", ROOT / "scripts" / "c19_record_retention.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _args(**overrides):
    values = {
        "record_url": "http://c19-record-service:8090",
        "asset_url": "http://c19-asset-api:8091",
        "requested_by_user_id": "retention-operator",
        "reason": "approved 90 day chat retention policy",
        "delete_before": "2026-01-01T00:00:00Z",
        "conversation_id": None,
        "minimum_age_days": 30,
        "batch_size": 1000,
        "maximum_records": 1500,
        "maximum_asset_jobs": 1500,
        "maximum_dispatch_jobs": 1500,
        "allow_public_https": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class _Response:
    def __init__(self, body: dict, *, on_read=None):
        self.status = 200
        self._body = json.dumps(body).encode()
        self._on_read = on_read

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, maximum: int) -> bytes:
        assert maximum == 64 * 1024
        if self._on_read is not None:
            self._on_read()
        return self._body


def _empty_claim():
    return {
        "jobs": [],
        "eligible_count": 0,
        "blocked_count": 0,
        "leased_count": 0,
    }


def test_retention_runner_batches_to_hard_total_and_drains_assets() -> None:
    policy = MODULE.build_policy(_args(), now=datetime(2026, 7, 12, tzinfo=UTC))
    requests = []

    def opener(request, *, timeout):
        assert timeout == 30
        requests.append(request)
        if request.full_url.endswith("/asset-deletions/claim"):
            return _Response(_empty_claim())
        body = json.loads(request.data)
        assert request.full_url.endswith("/v1/retention/apply")
        cumulative = 1000 if body["batch_ordinal"] == 0 else 1500
        return _Response(
            {
                "operation_id": policy.operation_id,
                "batch_ordinal": body["batch_ordinal"],
                "affected_count": body["maximum_records"],
                "cumulative_affected_count": cumulative,
                "operation_complete": cumulative == 1500,
                "completed_at": "2026-07-12T10:00:00+00:00",
            }
        )

    result = MODULE.run_retention(
        policy,
        "record-token-" + "x" * 32,
        "asset-token-" + "y" * 32,
        opener=opener,
    )
    assert result.affected_records == 1500
    assert result.record_batches == 2
    record_requests = [
        request
        for request in requests
        if request.full_url.endswith("/v1/retention/apply")
    ]
    bodies = [json.loads(request.data) for request in record_requests]
    assert [body["maximum_records"] for body in bodies] == [1000, 500]
    assert [body["batch_ordinal"] for body in bodies] == [0, 1]
    assert all(body["operation_id"] == policy.operation_id for body in bodies)
    assert all(body["approved_maximum_records"] == 1500 for body in bodies)
    assert all("content" not in body for body in bodies)


def test_retention_runner_exact_asset_handoff_and_ack() -> None:
    policy = MODULE.build_policy(
        _args(maximum_records=1, maximum_asset_jobs=2),
        now=datetime(2026, 7, 12, tzinfo=UTC),
    )
    job_id = "11111111-1111-4111-8111-111111111111"
    asset_id = "att_" + "1" * 32
    calls = []
    first_claim = True

    def opener(request, *, timeout):
        nonlocal first_claim
        del timeout
        calls.append(request.full_url)
        if request.full_url.endswith("/asset-deletions/claim"):
            if first_claim:
                first_claim = False
                return _Response(
                    {
                        "jobs": [
                            {
                                "job_id": job_id,
                                "asset_id": asset_id,
                                "record_id": "22222222-2222-4222-8222-222222222222",
                                "conversation_id": "conversation-1",
                                "phase": "prepare",
                            }
                        ],
                        "eligible_count": 1,
                        "blocked_count": 0,
                        "leased_count": 0,
                    }
                )
            return _Response(_empty_claim())
        if request.full_url.endswith(f"/{asset_id}/prepare"):
            return _Response(
                {
                    "asset_id": asset_id,
                    "disposition": "accepted",
                    "status": "prepared",
                }
            )
        if request.full_url.endswith(f"/{job_id}/authorize"):
            return _Response({"job_id": job_id, "state": "authorized"})
        if request.full_url.endswith(f"/{asset_id}/commit"):
            return _Response(
                {
                    "asset_id": asset_id,
                    "disposition": "accepted",
                    "status": "delete_pending",
                }
            )
        if request.full_url.endswith(f"/{job_id}/complete"):
            return _Response(
                {"job_id": job_id, "state": "completed", "outcome": "accepted"}
            )
        assert request.full_url.endswith("/v1/retention/apply")
        return _Response(
            {
                "operation_id": policy.operation_id,
                "batch_ordinal": 0,
                "affected_count": 0,
                "cumulative_affected_count": 0,
                "operation_complete": True,
                "completed_at": "2026-07-12T10:00:00+00:00",
            }
        )

    result = MODULE.run_retention(
        policy,
        "record-token-" + "x" * 32,
        "asset-token-" + "y" * 32,
        opener=opener,
    )
    assert result.accepted_assets == 1
    assert result.protected_assets == 0
    assert any(call.endswith(f"/{asset_id}/prepare") for call in calls)
    assert any(call.endswith(f"/{job_id}/authorize") for call in calls)
    assert any(call.endswith(f"/{asset_id}/commit") for call in calls)
    assert any(call.endswith(f"/{job_id}/complete") for call in calls)


def test_lost_record_response_fails_and_stable_policy_reuses_operation_id() -> None:
    policy = MODULE.build_policy(
        _args(maximum_records=1), now=datetime(2026, 7, 12, tzinfo=UTC)
    )
    calls = 0

    def opener(request, *, timeout):
        nonlocal calls
        del timeout
        if request.full_url.endswith("/asset-deletions/claim"):
            return _Response(_empty_claim())
        calls += 1
        raise urllib.error.URLError("response lost")

    with pytest.raises(MODULE.RetentionError, match="unavailable"):
        MODULE.run_retention(
            policy,
            "record-token-" + "x" * 32,
            "asset-token-" + "y" * 32,
            opener=opener,
        )
    rebuilt = MODULE.build_policy(
        _args(maximum_records=1), now=datetime(2026, 7, 13, tzinfo=UTC)
    )
    assert rebuilt.operation_id == policy.operation_id
    assert calls == 1


def test_claim_all_dispatch_cap_stops_before_next_record_batch() -> None:
    policy = MODULE.build_policy(
        _args(
            batch_size=1,
            maximum_records=3,
            maximum_asset_jobs=3,
            maximum_dispatch_jobs=1,
        ),
        now=datetime(2026, 7, 12, tzinfo=UTC),
    )
    job_id = "33333333-3333-4333-8333-333333333333"
    asset_id = "att_" + "3" * 32
    record_batches = 0
    claim_bodies = []

    def opener(request, *, timeout):
        nonlocal record_batches
        del timeout
        if request.full_url.endswith("/v1/retention/apply"):
            record_batches += 1
            body = json.loads(request.data)
            return _Response(
                {
                    "operation_id": policy.operation_id,
                    "batch_ordinal": body["batch_ordinal"],
                    "affected_count": 1,
                    "cumulative_affected_count": 1,
                    "operation_complete": False,
                    "completed_at": "2026-07-12T10:00:00+00:00",
                }
            )
        if request.full_url.endswith("/asset-deletions/claim"):
            claim_bodies.append(json.loads(request.data))
            return _Response(
                {
                    "jobs": [
                        {
                            "job_id": job_id,
                            "asset_id": asset_id,
                            "record_id": "44444444-4444-4444-8444-444444444444",
                            "conversation_id": "conversation-explicit",
                            "phase": "prepare",
                        }
                    ],
                    # Represents one NULL explicit, one prior-op, and one
                    # current-op job sharing the same dispatch boundary.
                    "eligible_count": 3,
                    "blocked_count": 0,
                    "leased_count": 0,
                }
            )
        if request.full_url.endswith(f"/{asset_id}/prepare"):
            return _Response(
                {
                    "asset_id": asset_id,
                    "disposition": "protected",
                    "status": "retained",
                }
            )
        if request.full_url.endswith(f"/{job_id}/complete"):
            return _Response(
                {"job_id": job_id, "state": "protected", "outcome": "protected"}
            )
        raise AssertionError(request.full_url)

    with pytest.raises(MODULE.RetentionIncompleteError, match="maximum asset jobs"):
        MODULE.run_retention(
            policy,
            "record-token-" + "x" * 32,
            "asset-token-" + "y" * 32,
            opener=opener,
        )
    assert record_batches == 1
    assert len(claim_bodies) == 1
    assert "retention_operation_id" not in claim_bodies[0]


def test_reclaimed_authorized_job_skips_prepare_and_replays_commit() -> None:
    policy = MODULE.build_policy(
        _args(maximum_records=1, maximum_dispatch_jobs=2),
        now=datetime(2026, 7, 12, tzinfo=UTC),
    )
    job_id = "55555555-5555-4555-8555-555555555555"
    asset_id = "att_" + "5" * 32
    calls = []
    claimed = False

    def opener(request, *, timeout):
        nonlocal claimed
        del timeout
        calls.append(request.full_url)
        if request.full_url.endswith("/v1/retention/apply"):
            return _Response(
                {
                    "operation_id": policy.operation_id,
                    "batch_ordinal": 0,
                    "affected_count": 0,
                    "cumulative_affected_count": 0,
                    "operation_complete": True,
                    "completed_at": "2026-07-12T10:00:00+00:00",
                }
            )
        if request.full_url.endswith("/asset-deletions/claim"):
            if claimed:
                return _Response(_empty_claim())
            claimed = True
            return _Response(
                {
                    "jobs": [
                        {
                            "job_id": job_id,
                            "asset_id": asset_id,
                            "record_id": "66666666-6666-4666-8666-666666666666",
                            "conversation_id": "conversation-1",
                            "phase": "commit",
                        }
                    ],
                    "eligible_count": 1,
                    "blocked_count": 0,
                    "leased_count": 0,
                }
            )
        if request.full_url.endswith(f"/{asset_id}/commit"):
            return _Response(
                {
                    "asset_id": asset_id,
                    "disposition": "accepted",
                    "status": "delete_pending",
                }
            )
        if request.full_url.endswith(f"/{job_id}/complete"):
            return _Response(
                {"job_id": job_id, "state": "completed", "outcome": "accepted"}
            )
        raise AssertionError(request.full_url)

    result = MODULE.run_retention(
        policy,
        "record-token-" + "x" * 32,
        "asset-token-" + "y" * 32,
        opener=opener,
    )
    assert result.accepted_assets == 1
    assert not any(call.endswith("/prepare") for call in calls)
    assert not any(call.endswith("/authorize") for call in calls)


def test_retention_policy_rejects_recent_cutoff_and_unbounded_values() -> None:
    now = datetime(2026, 7, 12, tzinfo=UTC)
    with pytest.raises(MODULE.RetentionError):
        MODULE.build_policy(
            _args(delete_before=(now - timedelta(days=5)).isoformat()), now=now
        )
    with pytest.raises(MODULE.RetentionError):
        MODULE.build_policy(_args(batch_size=1001), now=now)
    with pytest.raises(MODULE.RetentionError):
        MODULE.build_policy(_args(maximum_records=100_001), now=now)
    with pytest.raises(MODULE.RetentionError):
        MODULE.build_policy(_args(maximum_asset_jobs=100_001), now=now)
    with pytest.raises(MODULE.RetentionError):
        MODULE.build_policy(_args(maximum_dispatch_jobs=100_001), now=now)


@pytest.mark.parametrize(
    "url",
    (
        "http://public.example",
        "https://public.example",
        "http://user:password@c19-record-service:8090",
        "http://c19-record-service:99999",
        "http://169.254.169.254:8090",
        "http://[fe80::1]:8090",
        "http://0.0.0.0:8090",
        "http://224.0.0.1:8090",
    ),
)
def test_retention_origins_fail_closed_for_public_or_invalid_urls(url: str) -> None:
    with pytest.raises(MODULE.RetentionError):
        MODULE.build_policy(
            _args(record_url=url), now=datetime(2026, 7, 12, tzinfo=UTC)
        )


@pytest.mark.parametrize(
    "url",
    (
        "http://c19-record-service:8090",
        "http://127.0.0.1:8090",
        "http://10.20.30.40:8090",
        "http://192.168.1.10:8090",
        "http://[fd00::10]:8090",
        "http://record.private.internal:8090",
        "http://record.default.svc.cluster.local:8090",
    ),
)
def test_retention_origins_allow_private_service_boundaries(url: str) -> None:
    policy = MODULE.build_policy(
        _args(record_url=url), now=datetime(2026, 7, 12, tzinfo=UTC)
    )
    assert policy.record_url == url


def test_public_https_requires_explicit_confirmed_opt_in() -> None:
    policy = MODULE.build_policy(
        _args(record_url="https://records.example", allow_public_https=True),
        now=datetime(2026, 7, 12, tzinfo=UTC),
    )
    assert policy.record_url == "https://records.example"
    assert policy.allow_public_https is True


def test_confirmation_binds_protocol_dispatch_scope_and_limits() -> None:
    now = datetime(2026, 7, 12, tzinfo=UTC)
    first = MODULE.build_policy(_args(), now=now)
    replay = MODULE.build_policy(_args(), now=now + timedelta(hours=1))
    changed = MODULE.build_policy(_args(maximum_dispatch_jobs=1499), now=now)
    assert first.confirmation == replay.confirmation
    assert first.confirmation != changed.confirmation
    assert MODULE.PROTOCOL == "record-asset-retention-v2-two-phase"
    assert MODULE.ASSET_DISPATCH_SCOPE == "all-eligible-record-outbox"


def test_runner_operation_id_matches_record_authority_contract() -> None:
    policy = MODULE.build_policy(
        _args(), now=datetime(2026, 7, 12, tzinfo=UTC)
    )
    request = RetentionRequest(
        operation_id=policy.operation_id,
        batch_ordinal=0,
        approved_maximum_records=policy.maximum_records,
        approved_maximum_asset_jobs=policy.maximum_asset_jobs,
        requested_by_user_id=policy.requested_by_user_id,
        reason=policy.reason,
        requested_at=datetime.now(UTC),
        delete_before=policy.delete_before,
        conversation_id=policy.conversation_id,
        maximum_records=policy.batch_size,
    )
    assert _expected_retention_operation_id(request) == policy.operation_id


def test_production_http_opener_disables_proxies_and_redirects() -> None:
    # Passing this explicit empty handler suppresses urllib's environment-based
    # default ProxyHandler (build_opener may omit the no-op instance itself).
    assert MODULE._PROXY_HANDLER.proxies == {}
    assert not any(
        isinstance(handler, urllib.request.ProxyHandler)
        and handler.proxies
        for handler in MODULE._SECURE_OPENER.handlers
    )
    redirect = next(
        handler
        for handler in MODULE._SECURE_OPENER.handlers
        if isinstance(handler, MODULE._NoRedirect)
    )
    assert redirect.redirect_request(None, None, 302, "found", {}, "https://evil") is None

    def redirected(request, *, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 302, "found", {"Location": "https://evil"}, None
        )

    with pytest.raises(MODULE.RetentionError, match="HTTP 302"):
        MODULE._post_json(
            "http://c19-record-service:8090/v1/test",
            "token-" + "x" * 32,
            {},
            opener=redirected,
        )


def test_cli_rejects_identical_role_tokens_before_network(tmp_path, monkeypatch) -> None:
    record = tmp_path / "record.token"
    asset = tmp_path / "asset.token"
    token = "same-role-token-" + "x" * 32
    record.write_text(token, encoding="utf-8")
    asset.write_text(token, encoding="utf-8")
    record.chmod(0o600)
    asset.chmod(0o600)
    argv = [
        "--record-url",
        "http://c19-record-service:8090",
        "--asset-url",
        "http://c19-asset-api:8091",
        "--requested-by-user-id",
        "retention-operator",
        "--reason",
        "approved 90 day chat retention policy",
        "--delete-before",
        "2026-01-01T00:00:00Z",
        "--execute",
        "--record-service-token-file",
        str(record),
        "--asset-service-token-file",
        str(asset),
    ]
    policy = MODULE.build_policy(MODULE.parser().parse_args(argv))
    monkeypatch.setenv("CONFIRM_C19_RECORD_RETENTION", policy.confirmation)
    assert MODULE.main(argv) == 1


@pytest.mark.parametrize(
    "value",
    (
        " leading-token-" + "x" * 32,
        "trailing-token-" + "x" * 32 + " ",
        "embedded\nline-" + "x" * 32,
        "carriage\rreturn-" + "x" * 32,
        "tab\ttoken-" + "x" * 32,
        "nul\x00token-" + "x" * 32,
    ),
)
def test_token_reader_rejects_header_unsafe_content_without_echo(
    tmp_path, value: str
) -> None:
    path = tmp_path / "unsafe.token"
    path.write_bytes(value.encode("utf-8"))
    path.chmod(0o600)
    with pytest.raises(MODULE.RetentionError) as raised:
        MODULE._token(path)
    assert value not in str(raised.value)


def test_retention_cli_defaults_to_network_free_dry_run_and_execute_is_confirmed(
    tmp_path: Path,
) -> None:
    command = [
        str(ROOT / ".venv" / "bin" / "python"),
        "scripts/c19_record_retention.py",
        "--record-url",
        "http://c19-record-service:8090",
        "--asset-url",
        "http://c19-asset-api:8091",
        "--requested-by-user-id",
        "retention-operator",
        "--reason",
        "approved 90 day chat retention policy",
        "--delete-before",
        "2026-01-01T00:00:00Z",
    ]
    dry_run = subprocess.run(
        command,
        cwd=ROOT,
        env={**os.environ, "http_proxy": "http://must-not-be-used.invalid"},
        check=False,
        capture_output=True,
        text=True,
    )
    assert dry_run.returncode == 0, dry_run.stderr
    assert "mode: dry-run" in dry_run.stdout
    assert "protocol: record-asset-retention-v2-two-phase" in dry_run.stdout
    assert "asset_dispatch_scope: all-eligible-record-outbox" in dry_run.stdout
    assert "No HTTP request, record mutation, or asset mutation" in dry_run.stdout

    blocked = subprocess.run(
        [
            *command,
            "--execute",
            "--record-service-token-file",
            str(tmp_path / "missing-record"),
            "--asset-service-token-file",
            str(tmp_path / "missing-asset"),
        ],
        cwd=ROOT,
        env={
            key: value
            for key, value in os.environ.items()
            if key != "CONFIRM_C19_RECORD_RETENTION"
        },
        check=False,
        capture_output=True,
        text=True,
    )
    assert blocked.returncode == 1
    assert "does not match the printed plan" in blocked.stderr
