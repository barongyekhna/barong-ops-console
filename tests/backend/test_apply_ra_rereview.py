from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from scripts.apply_ra_rereview import (
    PROTECTED_REPORT_IDS,
    PROTECTION_NOTE,
    REVIEW_KEY,
    ApplySummary,
    Decision,
    DecisionError,
    apply_decisions,
    load_decisions,
)


pytestmark = pytest.mark.unit


REPORT_ID = "11111111-1111-4111-8111-111111111111"
PROTECTED_ID = next(iter(PROTECTED_REPORT_IDS))
REPO_ROOT = Path(__file__).resolve().parents[2]


def _payload(*, seo: str = "reject", ad: str = "review") -> dict[str, Any]:
    return {
        "final": {"verdict": "pass"},
        "channel_routes": {
            "routes": {
                "amazon": {
                    "verdict": "pass",
                    "reasons": ["Keepa 证据"],
                    "score": 88,
                },
                "dtc_seo": {
                    "verdict": seo,
                    "reasons": ["原 SEO 理由"],
                    "score": 42,
                },
                "dtc_ad": {
                    "verdict": ad,
                    "reasons": ["原广告理由"],
                    "score": 51,
                },
            }
        },
        "unrelated": {"keep": [1, 2, 3]},
    }


class _Mappings:
    def __init__(self, row: Mapping[str, object] | None) -> None:
        self._row = row

    def first(self) -> Mapping[str, object] | None:
        return self._row


class _Result:
    def __init__(self, row: Mapping[str, object] | None = None) -> None:
        self._row = row

    def mappings(self) -> _Mappings:
        return _Mappings(self._row)


class FakeSession:
    def __init__(self, reports: Mapping[str, dict[str, Any]]) -> None:
        self.reports = copy.deepcopy(dict(reports))
        self.commits = 0
        self.rollbacks = 0
        self.sql: list[str] = []

    def execute(
        self, statement: object, params: Mapping[str, object] | None = None
    ) -> _Result:
        sql = " ".join(str(statement).split())
        self.sql.append(sql)
        if sql.startswith("SET statement_timeout"):
            return _Result()
        if sql.startswith("SELECT payload FROM ra_reports"):
            assert params is not None
            report_id = str(params["report_id"])
            payload = self.reports.get(report_id)
            return _Result(
                None if payload is None else {"payload": copy.deepcopy(payload)}
            )
        if sql.startswith("UPDATE ra_reports SET payload"):
            assert params is not None
            report_id = str(params["report_id"])
            self.reports[report_id] = json.loads(str(params["payload"]))
            return _Result()
        raise AssertionError(f"unexpected SQL: {sql}")

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def _decision(
    *,
    report_id: str = REPORT_ID,
    channel: str = "dtc_seo",
    previous: str = "reject",
    new: str = "pass",
    reason: str = "主词月搜1万、CPC高位$5，需求成立。",
) -> Decision:
    return Decision(
        report_id=report_id,
        channel=channel,
        previous_verdict=previous,
        new_verdict=new,
        confidence="high",
        reason_zh=reason,
    )


def test_apply_is_idempotent_and_audit_snapshot_is_written_once() -> None:
    session = FakeSession({REPORT_ID: _payload()})
    decisions = [
        _decision(),
        _decision(
            channel="dtc_ad",
            previous="review",
            new="reject",
            reason="日常CPC $2、5%转化CAC $40，高于售价$30。",
        ),
    ]

    first = apply_decisions(session, decisions)  # type: ignore[arg-type]
    after_first = copy.deepcopy(session.reports[REPORT_ID])
    second = apply_decisions(session, decisions)  # type: ignore[arg-type]

    assert first == ApplySummary(2, 1, 1, 0, 1)
    assert second == ApplySummary(2, 1, 0, 0, 1)
    assert session.reports[REPORT_ID] == after_first
    assert after_first[REVIEW_KEY] == {
        "by": "codex",
        "previous_routes": {"dtc_ad": "review", "dtc_seo": "reject"},
        "applied_at": "2026-07-21",
    }
    seo_reasons = after_first["channel_routes"]["routes"]["dtc_seo"][
        "reasons"
    ]
    assert len(seo_reasons) == 2


def test_existing_audit_block_is_never_overwritten() -> None:
    payload = _payload()
    original_audit = {
        "by": "earlier-run",
        "previous_routes": {"dtc_ad": "pass", "dtc_seo": "pass"},
        "applied_at": "kept",
    }
    payload[REVIEW_KEY] = copy.deepcopy(original_audit)
    session = FakeSession({REPORT_ID: payload})

    apply_decisions(session, [_decision()])  # type: ignore[arg-type]

    assert session.reports[REPORT_ID][REVIEW_KEY] == original_audit


def test_protected_reject_is_upgraded_and_marked() -> None:
    session = FakeSession({PROTECTED_ID: _payload(seo="reject")})

    summary = apply_decisions(  # type: ignore[arg-type]
        session,
        [
            _decision(
                report_id=PROTECTED_ID,
                new="reject",
                reason="5%转化CAC $60，高于售价$22.99。",
            )
        ],
    )

    payload = session.reports[PROTECTED_ID]
    seo_route = payload["channel_routes"]["routes"]["dtc_seo"]
    assert seo_route["verdict"] == "review"
    assert PROTECTION_NOTE in seo_route["reasons"][0]
    assert payload[REVIEW_KEY]["protected_from_deletion"] is True
    assert summary.protected_upgrades == 1


def test_amazon_route_and_unrelated_payload_are_untouched() -> None:
    original = _payload()
    amazon_before = copy.deepcopy(
        original["channel_routes"]["routes"]["amazon"]
    )
    unrelated_before = copy.deepcopy(original["unrelated"])
    session = FakeSession({REPORT_ID: original})

    apply_decisions(session, [_decision()])  # type: ignore[arg-type]

    updated = session.reports[REPORT_ID]
    assert updated["channel_routes"]["routes"]["amazon"] == amazon_before
    assert updated["unrelated"] == unrelated_before


def test_illegal_verdict_is_rejected_before_database_work(tmp_path: Path) -> None:
    decisions_path = tmp_path / "bad.jsonl"
    decisions_path.write_text(
        json.dumps(
            {
                "report_id": REPORT_ID,
                "channel": "dtc_seo",
                "previous_verdict": "reject",
                "new_verdict": "maybe",
                "confidence": "high",
                "reason_zh": "主词月搜1万。",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(DecisionError, match="new_verdict 非法"):
        load_decisions(decisions_path)

    session = FakeSession({REPORT_ID: _payload()})
    invalid = _decision(new="maybe")
    with pytest.raises(DecisionError, match="new_verdict 非法"):
        apply_decisions(session, [invalid])  # type: ignore[arg-type]
    assert session.sql == []


def test_commits_in_batches_of_fifty_decisions() -> None:
    reports = {
        f"report-{index}": _payload()
        for index in range(51)
    }
    decisions = [
        _decision(report_id=report_id)
        for report_id in reports
    ]
    session = FakeSession(reports)

    summary = apply_decisions(session, decisions, batch_size=50)  # type: ignore[arg-type]

    assert session.commits == 2
    assert summary.commits == 2


def test_shipped_decisions_cover_evidence_and_preserve_previous_verdicts() -> None:
    evidence = json.loads(
        (
            REPO_ROOT / "docs" / "RA_REREVIEW_20260721" / "evidence.json"
        ).read_text(encoding="utf-8")
    )
    decisions = load_decisions(
        REPO_ROOT / "docs" / "RA_REREVIEW_20260721" / "decisions.jsonl"
    )
    indexed = {
        (decision.report_id, decision.channel): decision
        for decision in decisions
    }

    assert len(decisions) == evidence["count"] * 2 == 476
    assert len(indexed) == len(decisions)
    for item in evidence["items"]:
        for channel in ("dtc_seo", "dtc_ad"):
            decision = indexed[(item["report_id"], channel)]
            assert decision.previous_verdict == item["current"][channel]["verdict"]
            max_length = 500 if item.get("protected_from_deletion") else 200
            assert len(decision.reason_zh) <= max_length
        if item.get("protected_from_deletion"):
            assert indexed[(item["report_id"], "dtc_seo")].new_verdict != "reject"
            assert indexed[(item["report_id"], "dtc_ad")].new_verdict != "reject"
