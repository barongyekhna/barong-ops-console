from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

import c19_record_service.moment_repository as moment_repository_module
import c19_record_service.repository as repository_module

from c19_record_service.models import (
    ChatRecord,
    Moment,
    MomentAssetReference,
    RecordAssetDeletionOutbox,
    RecordAssetReference,
    RecordMutationAudit,
    RecordRetentionBatch,
    RecordRetentionOperation,
)
from c19_record_service.operations import record_ops_snapshot
from c19_record_service.repository import (
    AssetDeletionLeaseError,
    RecordStoreInvariantError,
    RetentionOperationConflictError,
    _expected_retention_operation_id,
    _asset_coordination_lock_statement,
    append_record,
    apply_retention,
    authorize_asset_deletion,
    claim_asset_deletions,
    complete_asset_deletion,
    delete_records,
)
from c19_record_service.moment_repository import (
    MomentConflictError,
    publish_moment,
    reserve_moment_draft,
)
from c19_record_service.moment_schemas import (
    MomentAssetReference as MomentAssetReferenceSchema,
    MomentDraftCreateRequest,
    MomentPublishRequest,
)
from c19_record_service.schemas import (
    AssetDeletionClaimRequest,
    AssetDeletionAuthorizeRequest,
    AssetDeletionCompleteRequest,
    DeleteRecordsRequest,
    RetentionRequest,
)

from helpers import make_asset, make_record


def _retention_request(
    *,
    ordinal: int,
    batch_maximum: int,
    approved_maximum: int,
    approved_assets: int | None = None,
    cutoff: datetime,
) -> RetentionRequest:
    request = RetentionRequest(
        operation_id="rtn_" + "0" * 64,
        batch_ordinal=ordinal,
        approved_maximum_records=approved_maximum,
        approved_maximum_asset_jobs=approved_assets or approved_maximum,
        requested_by_user_id="retention-operator",
        reason="approved coordinated retention",
        requested_at=datetime.now(UTC),
        delete_before=cutoff,
        conversation_id="conversation-1",
        maximum_records=batch_maximum,
    )
    request.operation_id = _expected_retention_operation_id(request)
    return request


def _claim(runtime, worker: str = "retention-worker"):
    with runtime.session_factory() as session:
        return claim_asset_deletions(
            session,
            AssetDeletionClaimRequest(
                worker_id=worker,
                requested_at=datetime.now(UTC),
                limit=100,
                lease_seconds=120,
            ),
        )


def _delete(runtime, record_id: str) -> None:
    with runtime.session_factory() as session:
        delete_records(
            session,
            DeleteRecordsRequest(
                conversation_id="conversation-1",
                record_ids=[record_id],
                requested_by_user_id="retention-operator",
                reason="approved asset deletion",
                requested_at=datetime.now(UTC),
            ),
        )


def test_lost_response_replays_exact_batch_and_hard_total_cap(runtime) -> None:
    old = datetime.now(UTC) - timedelta(days=90)
    for number in range(1, 5):
        with runtime.session_factory() as session:
            append_record(
                session,
                make_record(number, created_at=old + timedelta(seconds=number)),
                max_message_chars=1000,
            )
    cutoff = datetime.now(UTC) - timedelta(days=30)
    first_request = _retention_request(
        ordinal=0, batch_maximum=2, approved_maximum=3, cutoff=cutoff
    )
    with runtime.session_factory() as session:
        first = apply_retention(session, first_request)
    assert first.affected_count == 2
    assert first.cumulative_affected_count == 2
    assert first.operation_complete is False

    # Simulate a lost HTTP response: the caller sends the same stable operation
    # and ordinal again with a new transport timestamp. No second selection or
    # mutation audit may occur.
    replay_request = first_request.model_copy(
        update={"requested_at": datetime.now(UTC) + timedelta(seconds=1)}
    )
    with runtime.session_factory() as session:
        replay = apply_retention(session, replay_request)
        assert replay == first
        assert session.scalar(select(func.count(ChatRecord.id))) == 2
        assert session.scalar(select(func.count(RecordMutationAudit.id))) == 1
        assert session.scalar(select(func.count(RecordRetentionBatch.operation_id))) == 1

    second_request = _retention_request(
        ordinal=1, batch_maximum=1, approved_maximum=3, cutoff=cutoff
    )
    assert second_request.operation_id == first_request.operation_id
    with runtime.session_factory() as session:
        second = apply_retention(session, second_request)
        assert second.affected_count == 1
        assert second.cumulative_affected_count == 3
        assert second.operation_complete is True
        operation = session.get(RecordRetentionOperation, second.operation_id)
        assert operation is not None
        assert operation.affected_count == 3
        assert session.scalar(select(func.count(ChatRecord.id))) == 1
    with runtime.session_factory() as session:
        # An earlier non-terminal ordinal remains non-terminal even after a
        # later batch completes the operation.
        assert apply_retention(session, replay_request).operation_complete is False

    with runtime.session_factory() as session:
        with pytest.raises(RetentionOperationConflictError):
            apply_retention(
                session,
                _retention_request(
                    ordinal=2,
                    batch_maximum=1,
                    approved_maximum=3,
                    cutoff=cutoff,
                ),
            )


def test_record_delete_creates_leased_idempotent_asset_handoff(runtime) -> None:
    asset = make_asset(1, kind="file")
    with runtime.session_factory() as session:
        record = append_record(
            session,
            make_record(1, content_type="file", content="", assets=[asset]),
            max_message_chars=1000,
        ).record
    _delete(runtime, record.record_id)

    claimed = _claim(runtime)
    assert claimed.eligible_count == 1
    assert claimed.blocked_count == 0
    assert claimed.leased_count == 0
    assert len(claimed.jobs) == 1
    job = claimed.jobs[0]
    assert job.phase == "prepare"
    assert job.asset_id == asset.asset_id
    assert job.record_id == record.record_id
    with runtime.session_factory() as session:
        authorized = authorize_asset_deletion(
            session,
            job_id=job.job_id,
            request=AssetDeletionAuthorizeRequest(
                worker_id="retention-worker",
                authorized_at=datetime.now(UTC),
            ),
        )
        assert authorized.state == "authorized"
        completed = complete_asset_deletion(
            session,
            job_id=job.job_id,
            request=AssetDeletionCompleteRequest(
                worker_id="retention-worker",
                outcome="accepted",
                completed_at=datetime.now(UTC),
            ),
        )
        assert completed.state == "completed"
        # Lost acknowledgement responses replay without changing state.
        assert (
            complete_asset_deletion(
                session,
                job_id=job.job_id,
                request=AssetDeletionCompleteRequest(
                    worker_id="another-worker",
                    outcome="accepted",
                    completed_at=datetime.now(UTC),
                ),
            )
            == completed
        )
        snapshot = record_ops_snapshot(session)
        assert snapshot.asset_deletion_completed == 1
        assert snapshot.asset_deletion_pending == 0


def test_surviving_chat_and_moment_references_block_until_removed(runtime) -> None:
    shared = make_asset(7)
    with runtime.session_factory() as session:
        first = append_record(
            session,
            make_record(1, content_type="image", content="", assets=[shared]),
            max_message_chars=1000,
        ).record
        second = append_record(
            session,
            make_record(2, content_type="image", content="", assets=[shared]),
            max_message_chars=1000,
        ).record
    _delete(runtime, first.record_id)
    blocked = _claim(runtime)
    assert blocked.jobs == []
    assert blocked.blocked_count == 1
    _delete(runtime, second.record_id)
    eligible = _claim(runtime)
    assert eligible.eligible_count == 2
    assert {job.record_id for job in eligible.jobs} == {
        first.record_id,
        second.record_id,
    }

    moment_asset = make_asset(8)
    with runtime.session_factory() as session:
        chat = append_record(
            session,
            make_record(3, content_type="image", content="", assets=[moment_asset]),
            max_message_chars=1000,
        ).record
        now = datetime.now(UTC)
        moment_id = "mom_" + "8" * 32
        session.add(
            Moment(
                id=moment_id,
                client_moment_id="retention-shared-moment",
                author_user_id="user-1",
                author_org_id=None,
                state="draft",
                visibility="private",
                audience_org_ids=[],
                content=None,
                feed_sequence=None,
                like_count=0,
                comment_count=0,
                last_like_sequence=0,
                last_comment_sequence=0,
                publish_intent_sha256=None,
                publish_intent_version=1,
                created_at=now,
                persisted_at=now,
                updated_at=now,
                published_at=None,
                delete_pending_at=None,
                deleted_at=None,
            )
        )
        session.add(
            MomentAssetReference(
                id=str(uuid.uuid4()),
                moment_id=moment_id,
                asset_id=moment_asset.asset_id,
                client_asset_id=moment_asset.client_asset_id,
                kind="image",
                filename=moment_asset.filename,
                media_type=moment_asset.media_type,
                size_bytes=moment_asset.size_bytes,
                sha256_hex=moment_asset.sha256_hex,
                version=1,
                ordinal=0,
            )
        )
        session.commit()
    _delete(runtime, chat.record_id)
    moment_blocked = _claim(runtime, "moment-check-worker")
    assert moment_blocked.blocked_count >= 1
    assert all(job.asset_id != moment_asset.asset_id for job in moment_blocked.jobs)


def test_retention_tombstone_prevents_asset_identifier_reuse(runtime) -> None:
    asset = make_asset(9)
    with runtime.session_factory() as session:
        record = append_record(
            session,
            make_record(1, content_type="image", content="", assets=[asset]),
            max_message_chars=1000,
        ).record
    _delete(runtime, record.record_id)
    with runtime.session_factory() as session:
        with pytest.raises(RecordStoreInvariantError):
            append_record(
                session,
                make_record(2, content_type="image", content="", assets=[asset]),
                max_message_chars=1000,
            )
        assert session.scalar(select(func.count(RecordAssetDeletionOutbox.id))) == 1
        assert session.scalar(select(func.count(RecordAssetReference.id))) == 0


def test_asset_completion_fails_closed_for_wrong_or_expired_lease(runtime) -> None:
    asset = make_asset(10)
    with runtime.session_factory() as session:
        record = append_record(
            session,
            make_record(1, content_type="image", content="", assets=[asset]),
            max_message_chars=1000,
        ).record
    _delete(runtime, record.record_id)
    job = _claim(runtime, "right-worker").jobs[0]
    with runtime.session_factory() as session:
        with pytest.raises(AssetDeletionLeaseError):
            complete_asset_deletion(
                session,
                job_id=job.job_id,
                request=AssetDeletionCompleteRequest(
                    worker_id="wrong-worker",
                    outcome="accepted",
                    completed_at=datetime.now(UTC),
                ),
            )


def test_full_batch_terminal_at_asset_cap_replays_exactly(runtime) -> None:
    old = datetime.now(UTC) - timedelta(days=90)
    for number in range(1, 4):
        with runtime.session_factory() as session:
            append_record(
                session,
                make_record(
                    number,
                    created_at=old + timedelta(seconds=number),
                    content_type="image",
                    content="",
                    assets=[make_asset(number)],
                ),
                max_message_chars=1000,
            )
    request = _retention_request(
        ordinal=0,
        batch_maximum=1,
        approved_maximum=3,
        approved_assets=1,
        cutoff=datetime.now(UTC) - timedelta(days=30),
    )
    with runtime.session_factory() as session:
        first = apply_retention(session, request)
        assert first.affected_count == 1
        assert first.operation_complete is True
    with runtime.session_factory() as session:
        replay = apply_retention(
            session,
            request.model_copy(update={"requested_at": datetime.now(UTC)}),
        )
        assert replay == first
        operation = session.get(RecordRetentionOperation, request.operation_id)
        assert operation is not None
        assert operation.asset_jobs_enqueued_count == 1
        assert session.scalar(select(func.count(ChatRecord.id))) == 2


def test_authorized_job_is_reclaimed_as_commit_phase_after_crash(runtime) -> None:
    asset = make_asset(11)
    with runtime.session_factory() as session:
        record = append_record(
            session,
            make_record(1, content_type="image", content="", assets=[asset]),
            max_message_chars=1000,
        ).record
    _delete(runtime, record.record_id)
    claimed = _claim(runtime, "crashed-worker")
    job = claimed.jobs[0]
    with runtime.session_factory() as session:
        assert authorize_asset_deletion(
            session,
            job_id=job.job_id,
            request=AssetDeletionAuthorizeRequest(
                worker_id="crashed-worker", authorized_at=datetime.now(UTC)
            ),
        ).state == "authorized"
        snapshot = record_ops_snapshot(session)
        assert snapshot.asset_deletion_authorized == 1
        assert snapshot.asset_deletion_leased == 1
        assert snapshot.oldest_asset_deletion_authorized_age_seconds is not None
        row = session.get(RecordAssetDeletionOutbox, job.job_id)
        assert row is not None
        row.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    reclaimed = _claim(runtime, "recovery-worker")
    assert len(reclaimed.jobs) == 1
    assert reclaimed.jobs[0].phase == "commit"
    with runtime.session_factory() as session:
        completed = complete_asset_deletion(
            session,
            job_id=job.job_id,
            request=AssetDeletionCompleteRequest(
                worker_id="recovery-worker",
                outcome="accepted",
                completed_at=datetime.now(UTC),
            ),
        )
        assert completed.state == "completed"


def test_reference_appearing_before_authorize_keeps_preparation_non_destructive(
    runtime,
) -> None:
    asset = make_asset(12)
    with runtime.session_factory() as session:
        record = append_record(
            session,
            make_record(1, content_type="image", content="", assets=[asset]),
            max_message_chars=1000,
        ).record
    _delete(runtime, record.record_id)
    job = _claim(runtime, "prepare-worker").jobs[0]
    # Model an already-started reference transaction becoming visible between
    # Asset prepare and Record authorize. Authorization re-checks under the
    # permanent coordination fence and refuses the destructive commit phase.
    now = datetime.now(UTC)
    survivor_id = str(uuid.uuid4())
    with runtime.session_factory() as session:
        session.add(
            ChatRecord(
                id=survivor_id,
                client_message_id="concurrent-survivor",
                conversation_id="conversation-1",
                sequence=999,
                sender_user_id="user-1",
                recipient_user_ids=["user-2"],
                content_type="image",
                content="",
                sender_org_id=None,
                recipient_org_ids=[],
                record_metadata={},
                created_at=now,
                persisted_at=now,
            )
        )
        session.add(
            RecordAssetReference(
                id=str(uuid.uuid4()),
                record_id=survivor_id,
                asset_id=asset.asset_id,
                client_asset_id=asset.client_asset_id,
                kind="image",
                filename=asset.filename,
                media_type=asset.media_type,
                size_bytes=asset.size_bytes,
                sha256_hex=asset.sha256_hex,
                version=1,
                ordinal=0,
            )
        )
        session.commit()
    with runtime.session_factory() as session:
        blocked = authorize_asset_deletion(
            session,
            job_id=job.job_id,
            request=AssetDeletionAuthorizeRequest(
                worker_id="prepare-worker", authorized_at=datetime.now(UTC)
            ),
        )
        assert blocked.state == "blocked"
        row = session.get(RecordAssetDeletionOutbox, job.job_id)
        assert row is not None and row.state == "pending"


def test_preexisting_outbox_does_not_consume_new_operation_asset_cap(runtime) -> None:
    old = datetime.now(UTC) - timedelta(days=90)
    asset = make_asset(13)
    with runtime.session_factory() as session:
        record = append_record(
            session,
            make_record(
                1,
                created_at=old,
                content_type="image",
                content="",
                assets=[asset],
            ),
            max_message_chars=1000,
        ).record
        session.add(
            RecordAssetDeletionOutbox(
                id=str(uuid.uuid4()),
                asset_id=asset.asset_id,
                record_id=record.record_id,
                conversation_id="conversation-1",
                retention_operation_id=None,
                state="pending",
                attempt_count=0,
                created_at=datetime.now(UTC),
                last_attempt_at=None,
                lease_owner=None,
                lease_until=None,
                outcome=None,
                completed_at=None,
            )
        )
        session.commit()
    request = _retention_request(
        ordinal=0,
        batch_maximum=1,
        approved_maximum=2,
        approved_assets=1,
        cutoff=datetime.now(UTC) - timedelta(days=30),
    )
    with runtime.session_factory() as session:
        result = apply_retention(session, request)
        assert result.affected_count == 1
        operation = session.get(RecordRetentionOperation, request.operation_id)
        assert operation is not None
        assert operation.asset_jobs_enqueued_count == 0
        assert session.scalar(
            select(func.count(RecordAssetDeletionOutbox.id)).where(
                RecordAssetDeletionOutbox.retention_operation_id
                == request.operation_id
            )
        ) == 0


def test_asset_coordination_uses_sorted_postgres_row_locks() -> None:
    sql = str(
        _asset_coordination_lock_statement(
            ["att_" + "2" * 32, "att_" + "1" * 32]
        ).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "record_asset_coordination" in sql
    assert "ORDER BY record_asset_coordination.asset_id" in sql
    assert sql.rstrip().endswith("FOR UPDATE")


def test_append_and_moment_recheck_outbox_after_coordination_fence(
    runtime, monkeypatch
) -> None:
    original_lock = repository_module._lock_asset_coordination
    chat_asset = make_asset(14)

    def inject_chat_retirement(session, asset_ids, *, now=None):
        original_lock(session, asset_ids, now=now)
        session.add(
            RecordAssetDeletionOutbox(
                id=str(uuid.uuid4()),
                asset_id=chat_asset.asset_id,
                record_id=str(uuid.uuid4()),
                conversation_id="conversation-1",
                retention_operation_id=None,
                state="pending",
                attempt_count=0,
                created_at=now or datetime.now(UTC),
                last_attempt_at=None,
                lease_owner=None,
                lease_until=None,
                outcome=None,
                completed_at=None,
            )
        )
        session.flush()

    monkeypatch.setattr(
        repository_module, "_lock_asset_coordination", inject_chat_retirement
    )
    with runtime.session_factory() as session:
        with pytest.raises(RecordStoreInvariantError):
            append_record(
                session,
                make_record(
                    1,
                    content_type="image",
                    content="",
                    assets=[chat_asset],
                ),
                max_message_chars=1000,
            )

    moment_asset = MomentAssetReferenceSchema(
        asset_id="att_" + "f" * 32,
        client_asset_id="moment-fenced-asset",
        kind="image",
        filename="fenced.jpg",
        media_type="image/jpeg",
        size_bytes=100,
        sha256_hex="f" * 64,
        version=1,
        ordinal=0,
    )
    with runtime.session_factory() as session:
        moment_id = reserve_moment_draft(
            session,
            MomentDraftCreateRequest(
                client_moment_id="fenced-moment", author_user_id="user-1"
            ),
        ).moment_id

    def inject_moment_retirement(session, asset_ids, *, now=None):
        original_lock(session, asset_ids, now=now)
        session.add(
            RecordAssetDeletionOutbox(
                id=str(uuid.uuid4()),
                asset_id=moment_asset.asset_id,
                record_id=str(uuid.uuid4()),
                conversation_id="conversation-1",
                retention_operation_id=None,
                state="pending",
                attempt_count=0,
                created_at=now or datetime.now(UTC),
                last_attempt_at=None,
                lease_owner=None,
                lease_until=None,
                outcome=None,
                completed_at=None,
            )
        )
        session.flush()

    monkeypatch.setattr(
        moment_repository_module,
        "_lock_asset_coordination",
        inject_moment_retirement,
    )
    with runtime.session_factory() as session:
        with pytest.raises(MomentConflictError):
            publish_moment(
                session,
                moment_id=moment_id,
                request=MomentPublishRequest(
                    author_user_id="user-1",
                    author_org_id=None,
                    content="fenced publication",
                    visibility="public",
                    audience_user_ids=["user-1"],
                    audience_org_ids=[],
                    assets=[moment_asset],
                ),
            )
