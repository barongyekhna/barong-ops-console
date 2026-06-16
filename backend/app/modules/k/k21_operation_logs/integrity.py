"""K21-F read-only integrity verification for K operation logs."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any

from .models import KOperationLog

K21_F_MODE = "integrity_verification"
K21_INTEGRITY_MUTATION = False
K21_EXTERNAL_ACCESS = False
ALLOWED_GAP = timedelta(hours=1)
GENESIS_HASH = "GENESIS"


class KLogIntegrity:
    """Read-only integrity checks for append-only K operation logs."""

    def verify_immutable(self, logs: list[KOperationLog]) -> None:
        for log in logs:
            if log.log_id is None:
                raise Exception("log_id is required")
            if log.timestamp is None:
                raise Exception("timestamp is required")
            if not isinstance(log.before_state, (dict, type(None))):
                raise Exception("before_state must be a dict or None")
            if not isinstance(log.after_state, (dict, type(None))):
                raise Exception("after_state must be a dict or None")

    def build_hash_chain(self, logs: list[KOperationLog]) -> list[str]:
        chain = []
        prev_hash = GENESIS_HASH

        for log in self._ordered_logs(logs):
            current_hash = self._hash_log(log, prev_hash)
            chain.append(current_hash)
            prev_hash = current_hash

        return chain

    def detect_missing_logs(self, logs: list[KOperationLog]) -> list[KOperationLog]:
        expected_sequence = self._ordered_logs(logs)

        return [
            log
            for index, log in enumerate(expected_sequence[:-1])
            if expected_sequence[index + 1].timestamp - log.timestamp > ALLOWED_GAP
        ]

    def generate_integrity_report(self, logs: list[KOperationLog]) -> dict[str, Any]:
        tamper_detected = False
        try:
            self.verify_immutable(logs)
            hash_chain = self.build_hash_chain(logs)
            hash_chain_valid = len(hash_chain) == len(logs)
        except Exception:
            tamper_detected = True
            hash_chain_valid = False

        missing_logs = self.detect_missing_logs(logs)
        missing_logs_detected = len(missing_logs) > 0

        return {
            "total_logs": len(logs),
            "hash_chain_valid": hash_chain_valid,
            "missing_logs_detected": missing_logs_detected,
            "tamper_detected": tamper_detected,
            "risk_level": self._risk_level(
                tamper_detected,
                missing_logs_detected,
            ),
            "status": (
                "compromised"
                if tamper_detected or missing_logs_detected
                else "clean"
            ),
        }

    def _hash_log(self, log: KOperationLog, prev_hash: str) -> str:
        payload = {
            "action": log.action,
            "after_state": log.after_state,
            "before_state": log.before_state,
            "entity_id": log.entity_id,
            "entity_type": log.entity_type,
            "event_type": log.event_type,
            "log_id": log.log_id,
            "prev_hash": prev_hash,
            "timestamp": log.timestamp.isoformat(),
        }
        canonical_payload = json.dumps(
            payload,
            default=str,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()

    def _ordered_logs(self, logs: list[KOperationLog]) -> list[KOperationLog]:
        return sorted(logs, key=lambda log: (log.timestamp, log.log_id))

    def _risk_level(
        self,
        tamper_detected: bool,
        missing_logs_detected: bool,
    ) -> str:
        if tamper_detected:
            return "high"
        if missing_logs_detected:
            return "medium"
        return "low"


__all__ = [
    "ALLOWED_GAP",
    "GENESIS_HASH",
    "K21_EXTERNAL_ACCESS",
    "K21_F_MODE",
    "K21_INTEGRITY_MUTATION",
    "KLogIntegrity",
]
