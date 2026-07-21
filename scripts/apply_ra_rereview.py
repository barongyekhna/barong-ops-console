#!/usr/bin/env python3
"""Apply the 2026-07-21 R-A Google-data rereview decisions.

The script intentionally changes only ``ra_reports.payload``.  It does not
perform migrations or touch the final/Amazon verdict.  Decisions are grouped
by report so the two DTC routes share one audit snapshot and one write.

Production usage (from the backend container):

    python scripts/apply_ra_rereview.py
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker


REVIEW_DATE = "2026-07-21"
REVIEW_KEY = "rereview_20260721"
REASON_PREFIX = f"[{REVIEW_DATE} 谷歌数据复核] "
PROTECTION_NOTE = "老板保护名单:不淘汰"
ALLOWED_CHANNELS = frozenset({"dtc_seo", "dtc_ad"})
ALLOWED_VERDICTS = frozenset({"pass", "review", "reject"})
ALLOWED_CONFIDENCE = frozenset({"high", "medium", "low"})
PROTECTED_REPORT_IDS = frozenset(
    {"027a4c3d-7f53-4c4b-8623-914a273a6437"}
)
DEFAULT_DECISIONS_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "RA_REREVIEW_20260721"
    / "decisions.jsonl"
)


class DecisionError(ValueError):
    """Raised before database writes when a decision is malformed."""


class ReportPayloadError(RuntimeError):
    """Raised when a report or its route payload cannot be safely updated."""


@dataclass(frozen=True)
class Decision:
    report_id: str
    channel: str
    previous_verdict: str
    new_verdict: str
    confidence: str
    reason_zh: str


@dataclass(frozen=True)
class ApplySummary:
    decisions: int
    reports: int
    changed_reports: int
    protected_upgrades: int
    commits: int


def _required_string(
    row: Mapping[str, object], key: str, *, line_number: int
) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DecisionError(f"第 {line_number} 行 {key} 必须是非空字符串")
    return value.strip()


def parse_decision(row: Mapping[str, object], *, line_number: int) -> Decision:
    report_id = _required_string(row, "report_id", line_number=line_number)
    channel = _required_string(row, "channel", line_number=line_number)
    previous_verdict = _required_string(
        row, "previous_verdict", line_number=line_number
    )
    new_verdict = _required_string(row, "new_verdict", line_number=line_number)
    confidence = _required_string(row, "confidence", line_number=line_number)
    reason_zh = _required_string(row, "reason_zh", line_number=line_number)

    if channel not in ALLOWED_CHANNELS:
        raise DecisionError(
            f"第 {line_number} 行 channel 非法: {channel!r}; "
            "只允许 dtc_seo/dtc_ad"
        )
    if previous_verdict not in ALLOWED_VERDICTS:
        raise DecisionError(
            f"第 {line_number} 行 previous_verdict 非法: {previous_verdict!r}"
        )
    if new_verdict not in ALLOWED_VERDICTS:
        raise DecisionError(
            f"第 {line_number} 行 new_verdict 非法: {new_verdict!r}"
        )
    if confidence not in ALLOWED_CONFIDENCE:
        raise DecisionError(
            f"第 {line_number} 行 confidence 非法: {confidence!r}"
        )
    max_reason_length = 500 if report_id in PROTECTED_REPORT_IDS else 200
    if len(reason_zh) > max_reason_length:
        raise DecisionError(
            f"第 {line_number} 行 reason_zh 超过 {max_reason_length} 字"
        )

    return Decision(
        report_id=report_id,
        channel=channel,
        previous_verdict=previous_verdict,
        new_verdict=new_verdict,
        confidence=confidence,
        reason_zh=reason_zh,
    )


def load_decisions(path: str | Path = DEFAULT_DECISIONS_PATH) -> list[Decision]:
    decisions: list[Decision] = []
    seen: set[tuple[str, str]] = set()
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                continue
            try:
                raw = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise DecisionError(
                    f"第 {line_number} 行不是合法 JSON: {exc.msg}"
                ) from exc
            if not isinstance(raw, dict):
                raise DecisionError(f"第 {line_number} 行必须是 JSON 对象")
            decision = parse_decision(raw, line_number=line_number)
            key = (decision.report_id, decision.channel)
            if key in seen:
                raise DecisionError(
                    f"第 {line_number} 行重复决定: {decision.report_id}/{decision.channel}"
                )
            seen.add(key)
            decisions.append(decision)
    if not decisions:
        raise DecisionError("决定文件为空")
    return decisions


def validate_decisions(decisions: Sequence[Decision]) -> list[Decision]:
    """Revalidate programmatic callers before starting a DB transaction."""
    if not decisions:
        raise DecisionError("决定列表为空")
    validated: list[Decision] = []
    seen: set[tuple[str, str]] = set()
    for line_number, decision in enumerate(decisions, start=1):
        if not isinstance(decision, Decision):
            raise DecisionError(f"第 {line_number} 条决定类型非法")
        parsed = parse_decision(
            {
                "report_id": decision.report_id,
                "channel": decision.channel,
                "previous_verdict": decision.previous_verdict,
                "new_verdict": decision.new_verdict,
                "confidence": decision.confidence,
                "reason_zh": decision.reason_zh,
            },
            line_number=line_number,
        )
        key = (parsed.report_id, parsed.channel)
        if key in seen:
            raise DecisionError(
                f"第 {line_number} 条重复决定: {parsed.report_id}/{parsed.channel}"
            )
        seen.add(key)
        validated.append(parsed)
    return validated


def _group_decisions(
    decisions: Sequence[Decision],
) -> list[tuple[str, list[Decision]]]:
    grouped: OrderedDict[str, list[Decision]] = OrderedDict()
    for decision in decisions:
        grouped.setdefault(decision.report_id, []).append(decision)
    return list(grouped.items())


def _decision_batches(
    grouped: Sequence[tuple[str, list[Decision]]], *, batch_size: int
) -> list[list[tuple[str, list[Decision]]]]:
    """Keep both routes for a report together while capping decision rows."""
    batches: list[list[tuple[str, list[Decision]]]] = []
    current: list[tuple[str, list[Decision]]] = []
    current_size = 0
    for report_group in grouped:
        group_size = len(report_group[1])
        if group_size > batch_size:
            raise ValueError(
                f"报告 {report_group[0]} 的决定数超过 batch_size={batch_size}"
            )
        if current and current_size + group_size > batch_size:
            batches.append(current)
            current = []
            current_size = 0
        current.append(report_group)
        current_size += group_size
    if current:
        batches.append(current)
    return batches


def _payload_from_row(row: object, *, report_id: str) -> dict[str, Any]:
    if row is None:
        raise ReportPayloadError(f"R-A 报告不存在: {report_id}")
    if isinstance(row, Mapping):
        raw_payload = row.get("payload")
    else:
        try:
            raw_payload = row["payload"]  # type: ignore[index]
        except (KeyError, TypeError) as exc:
            raise ReportPayloadError(f"报告 {report_id} 查询结果缺少 payload") from exc
    if isinstance(raw_payload, str):
        try:
            raw_payload = json.loads(raw_payload)
        except json.JSONDecodeError as exc:
            raise ReportPayloadError(f"报告 {report_id} 的 payload 不是合法 JSON") from exc
    if not isinstance(raw_payload, dict):
        raise ReportPayloadError(f"报告 {report_id} 的 payload 必须是 JSON 对象")
    return copy.deepcopy(raw_payload)


def _route_map(payload: dict[str, Any], *, report_id: str) -> dict[str, Any]:
    channel_routes = payload.get("channel_routes")
    if not isinstance(channel_routes, dict):
        raise ReportPayloadError(f"报告 {report_id} 缺少 channel_routes 对象")
    routes = channel_routes.get("routes")
    if not isinstance(routes, dict):
        raise ReportPayloadError(f"报告 {report_id} 缺少 channel_routes.routes 对象")
    return routes


def _route(
    routes: dict[str, Any], *, report_id: str, channel: str
) -> dict[str, Any]:
    route = routes.get(channel)
    if not isinstance(route, dict):
        raise ReportPayloadError(f"报告 {report_id} 缺少 {channel} 路由")
    verdict = route.get("verdict")
    if verdict not in ALLOWED_VERDICTS:
        raise ReportPayloadError(
            f"报告 {report_id} 的 {channel}.verdict 非法: {verdict!r}"
        )
    reasons = route.get("reasons")
    if not isinstance(reasons, list) or not all(
        isinstance(reason, str) for reason in reasons
    ):
        raise ReportPayloadError(
            f"报告 {report_id} 的 {channel}.reasons 必须是字符串数组"
        )
    return route


def _audit_snapshot(
    routes: dict[str, Any], *, report_id: str, protected: bool
) -> dict[str, Any]:
    previous_routes: dict[str, str] = {}
    for channel in sorted(ALLOWED_CHANNELS):
        route = _route(routes, report_id=report_id, channel=channel)
        previous_routes[channel] = str(route["verdict"])
    audit: dict[str, Any] = {
        "by": "codex",
        "previous_routes": previous_routes,
        "applied_at": REVIEW_DATE,
    }
    if protected:
        audit["protected_from_deletion"] = True
    return audit


def _apply_report(
    payload: dict[str, Any],
    report_decisions: Sequence[Decision],
    *,
    report_id: str,
    protected: bool,
) -> tuple[dict[str, Any], int]:
    routes = _route_map(payload, report_id=report_id)
    for decision in report_decisions:
        _route(routes, report_id=report_id, channel=decision.channel)

    if REVIEW_KEY not in payload:
        payload[REVIEW_KEY] = _audit_snapshot(
            routes, report_id=report_id, protected=protected
        )

    protected_upgrades = 0
    for decision in report_decisions:
        route = _route(routes, report_id=report_id, channel=decision.channel)
        effective_verdict = decision.new_verdict
        reason = f"{REASON_PREFIX}{decision.reason_zh}"
        if protected and effective_verdict == "reject":
            effective_verdict = "review"
            protected_upgrades += 1
            reason = f"{reason}；{PROTECTION_NOTE}"
        route["verdict"] = effective_verdict
        reasons = route["reasons"]
        if reason not in reasons:
            reasons.insert(0, reason)
    return payload, protected_upgrades


def apply_decisions(
    session: Session,
    decisions: Sequence[Decision],
    *,
    batch_size: int = 50,
    protected_report_ids: Iterable[str] = PROTECTED_REPORT_IDS,
) -> ApplySummary:
    """Apply validated decisions with one payload write per report."""
    if batch_size < 1:
        raise ValueError("batch_size 必须大于 0")
    validated_decisions = validate_decisions(decisions)
    grouped = _group_decisions(validated_decisions)
    protected_ids = frozenset(protected_report_ids)
    changed_reports = 0
    protected_upgrades = 0
    commits = 0

    session.execute(text("SET statement_timeout='300s'"))
    try:
        for batch in _decision_batches(grouped, batch_size=batch_size):
            for report_id, report_decisions in batch:
                result = session.execute(
                    text(
                        """
                        SELECT payload
                        FROM ra_reports
                        WHERE report_id = :report_id
                        FOR UPDATE
                        """
                    ),
                    {"report_id": report_id},
                )
                row = result.mappings().first()
                original = _payload_from_row(row, report_id=report_id)
                updated, report_upgrades = _apply_report(
                    copy.deepcopy(original),
                    report_decisions,
                    report_id=report_id,
                    protected=report_id in protected_ids,
                )
                protected_upgrades += report_upgrades
                if updated == original:
                    continue
                session.execute(
                    text(
                        """
                        UPDATE ra_reports
                        SET payload = CAST(:payload AS JSONB),
                            updated_at = CURRENT_TIMESTAMP
                        WHERE report_id = :report_id
                        """
                    ),
                    {
                        "report_id": report_id,
                        "payload": json.dumps(
                            updated, ensure_ascii=False, separators=(",", ":")
                        ),
                    },
                )
                changed_reports += 1
            session.commit()
            commits += 1
    except Exception:
        session.rollback()
        raise

    return ApplySummary(
        decisions=len(validated_decisions),
        reports=len(grouped),
        changed_reports=changed_reports,
        protected_upgrades=protected_upgrades,
        commits=commits,
    )


def _session_from_environment() -> Session:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL 未设置")
    engine = create_engine(database_url, pool_pre_ping=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--decisions",
        type=Path,
        default=DEFAULT_DECISIONS_PATH,
        help="decisions.jsonl 路径",
    )
    parser.add_argument("--batch-size", type=int, default=50)
    args = parser.parse_args(argv)

    try:
        decisions = load_decisions(args.decisions)
        session = _session_from_environment()
        try:
            summary = apply_decisions(
                session, decisions, batch_size=args.batch_size
            )
        finally:
            session.close()
    except (DecisionError, ReportPayloadError, RuntimeError, ValueError) as exc:
        print(f"应用失败: {exc}", file=sys.stderr)
        return 2

    print(
        "复核应用完成: "
        f"decisions={summary.decisions}, reports={summary.reports}, "
        f"changed_reports={summary.changed_reports}, "
        f"protected_upgrades={summary.protected_upgrades}, "
        f"commits={summary.commits}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
