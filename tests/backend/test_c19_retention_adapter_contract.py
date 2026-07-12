from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from backend.app.modules.c19.http_record_store import (
    ChatRecordStoreProtocolError,
    HttpChatRecordStore,
    HttpChatRecordStoreConfig,
)
from backend.app.modules.c19.storage import (
    ChatRetentionBatchCommandDTO,
    ChatRetentionBatchResultDTO,
)


pytestmark = pytest.mark.unit


def _command(now: datetime) -> ChatRetentionBatchCommandDTO:
    return ChatRetentionBatchCommandDTO(
        operation_id="rtn_" + "a" * 64,
        batch_ordinal=7,
        approved_maximum_records=10_000,
        approved_maximum_asset_jobs=4_000,
        requested_by_user_id="retention-operator",
        reason="approved 90 day retention policy",
        requested_at=now,
        delete_before=now - timedelta(days=90),
        conversation_id="conversation-1",
        maximum_records=500,
    )


def test_http_adapter_uses_exact_retention_v4_batch_wire() -> None:
    now = datetime.now(UTC)
    command = _command(now)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert json.loads(request.content) == {
            "operation_id": command.operation_id,
            "batch_ordinal": 7,
            "approved_maximum_records": 10_000,
            "approved_maximum_asset_jobs": 4_000,
            "requested_by_user_id": "retention-operator",
            "reason": "approved 90 day retention policy",
            "requested_at": now.isoformat(),
            "delete_before": (now - timedelta(days=90)).isoformat(),
            "conversation_id": "conversation-1",
            "maximum_records": 500,
        }
        return httpx.Response(
            200,
            json={
                "operation_id": command.operation_id,
                "batch_ordinal": 7,
                "affected_count": 400,
                "cumulative_affected_count": 2_400,
                "operation_complete": False,
                "completed_at": now.isoformat(),
            },
        )

    async def run() -> ChatRetentionBatchResultDTO:
        async with HttpChatRecordStore(
            HttpChatRecordStoreConfig(
                base_url="http://c19-record-service:8090",
                token="t" * 32,
            ),
            transport=httpx.MockTransport(handler),
        ) as store:
            return await store.apply_retention_batch(command)

    result = asyncio.run(run())

    assert requests[0].method == "POST"
    assert requests[0].url == httpx.URL(
        "http://c19-record-service:8090/v1/retention/apply"
    )
    assert result == ChatRetentionBatchResultDTO(
        operation_id=command.operation_id,
        batch_ordinal=7,
        affected_count=400,
        cumulative_affected_count=2_400,
        operation_complete=False,
        completed_at=now,
    )


@pytest.mark.parametrize(
    "command_update",
    (
        {"operation_id": "old-operation-id"},
        {"batch_ordinal": -1},
        {"batch_ordinal": 100_001},
        {"approved_maximum_records": 0},
        {"approved_maximum_asset_jobs": 100_001},
        {"maximum_records": 0},
        {"maximum_records": 1_001},
        {"reason": "x"},
        {"requested_by_user_id": " retention-operator"},
        {"conversation_id": ""},
        {"requested_at": datetime.now()},
    ),
)
def test_retention_batch_command_rejects_out_of_contract_values(
    command_update: dict[str, object],
) -> None:
    now = datetime.now(UTC)
    values = {
        "operation_id": "rtn_" + "a" * 64,
        "batch_ordinal": 7,
        "approved_maximum_records": 10_000,
        "approved_maximum_asset_jobs": 4_000,
        "requested_by_user_id": "retention-operator",
        "reason": "approved 90 day retention policy",
        "requested_at": now,
        "delete_before": now - timedelta(days=90),
        "conversation_id": "conversation-1",
        "maximum_records": 500,
    }
    values.update(command_update)

    with pytest.raises(ValueError):
        ChatRetentionBatchCommandDTO(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "response_update",
    (
        {"unexpected": "old-wire-must-not-be-accepted"},
        {"operation_id": "rtn_" + "b" * 64},
        {"batch_ordinal": 8},
        {"affected_count": 501},
        {"cumulative_affected_count": 399},
        {"cumulative_affected_count": 10_001},
    ),
)
def test_http_adapter_rejects_retention_v4_response_drift(
    response_update: dict[str, object],
) -> None:
    now = datetime.now(UTC)
    command = _command(now)
    response: dict[str, object] = {
        "operation_id": command.operation_id,
        "batch_ordinal": 7,
        "affected_count": 400,
        "cumulative_affected_count": 2_400,
        "operation_complete": False,
        "completed_at": now.isoformat(),
    }
    response.update(response_update)

    async def run() -> None:
        async with HttpChatRecordStore(
            HttpChatRecordStoreConfig(
                base_url="http://c19-record-service:8090",
                token="t" * 32,
            ),
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json=response)
            ),
        ) as store:
            with pytest.raises(ChatRecordStoreProtocolError) as captured:
                await store.apply_retention_batch(command)
            assert captured.value.operation == "apply_retention_batch"
            assert "old-wire-must-not-be-accepted" not in str(captured.value)

    asyncio.run(run())
