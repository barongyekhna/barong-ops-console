from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from backend.app.db.base import Base
from backend.app.models.c19 import (
    C19AffiliationRecord,
    C19FriendRequestRecord,
    C19ProfileRecord,
    C19RelationshipRecord,
    C19UserBlockRecord,
)
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.organization import OrganizationRecord
from backend.app.models.user import User
from backend.app.modules.c19.http_asset_store import (
    ChatAssetStoreProtocolError,
    ChatAssetStoreRejectedError,
    ChatAssetStoreUnavailableError,
    HttpChatAssetStore,
    HttpChatAssetStoreConfig,
)
from backend.app.modules.c19.http_record_store import (
    ChatRecordStoreProtocolError,
    ChatRecordStoreRejectedError,
    HttpChatRecordStore,
    HttpChatRecordStoreConfig,
)
from backend.app.modules.c19.asset_service import (
    C19AssetAccessError,
    authorize_asset_transfer,
)
from backend.app.modules.c19.moment_policy import (
    C19MomentPolicyError,
    resolve_publish_audience,
)
from backend.app.modules.c19.moment_router import router as moment_router
from backend.app.modules.c19.moment_schemas import (
    MomentAssetAccessIntentRequest,
    MomentAssetUploadIntentRequest,
    MomentCommentCreateRequest,
    MomentDraftCreateRequest,
    MomentEventRead,
    MomentPublishRequest,
)
from backend.app.modules.c19 import moment_service
from backend.app.modules.c19.moment_service import (
    C19MomentAccessError,
    create_moment_asset_access_intent,
    create_moment_asset_upload_intent,
    create_moment_comment,
    create_moment_draft,
    delete_moment,
    delete_moment_comment,
    get_moment,
    list_moment_comments,
    list_moment_feed,
    list_moment_likes,
    publish_moment,
    set_moment_like,
)
from backend.app.modules.c19.moment_storage import (
    MOMENT_ASSET_STORE_OPERATIONS,
    MOMENT_STORE_OPERATIONS,
    MomentAssetBindingCommitDTO,
    MomentAssetBindingPrepareDTO,
    MomentAssetBindingResultDTO,
    MomentAssetDTO,
    MomentAssetDownloadRequestDTO,
    MomentAssetFinalizeDTO,
    MomentAssetLookupDTO,
    MomentAssetUploadHandleDTO,
    MomentAssetUploadMetadataDTO,
    MomentCommentCreateDTO,
    MomentCommentDeleteDTO,
    MomentCommentDeleteResultDTO,
    MomentCommentDTO,
    MomentCommentPageDTO,
    MomentCommentQueryDTO,
    MomentDTO,
    MomentDeleteCommandDTO,
    MomentDeleteResultDTO,
    MomentDraftDTO,
    MomentDraftReserveDTO,
    MomentFeedPageDTO,
    MomentFeedQueryDTO,
    MomentLikeCommandDTO,
    MomentLikeDTO,
    MomentLikePageDTO,
    MomentLikeQueryDTO,
    MomentLikeResultDTO,
    MomentPublishDTO,
    MomentQueryDTO,
    MomentUserEventPageDTO,
    MomentUserEventQueryDTO,
    MomentUserEventTailDTO,
    MomentViewerContextDTO,
    ScopedAssetTransferInspectionDTO,
)
from backend.app.modules.c19.router import router as aggregate_router
from backend.app.modules.c19.storage import (
    ChatAssetDeleteCommandDTO,
    ChatAssetDownloadIntentDTO,
    ChatAssetLifecycleResultDTO,
    ChatAssetReferenceDTO,
    StorageCapabilityDescription,
)


pytestmark = pytest.mark.unit

ORG_ONE = "org_" + "1" * 32
ORG_TWO = "org_" + "2" * 32
ORG_THREE = "org_" + "3" * 32
MOMENT_ID = "mom_" + "a" * 32
OTHER_MOMENT_ID = "mom_" + "b" * 32
COMMENT_ID = "cmt_" + "c" * 32
UPLOAD_TICKET = "u" * 43
DOWNLOAD_TICKET = "d" * 43


def _asset_id(index: int) -> str:
    return "att_" + f"{index:032x}"


@dataclass
class RuntimeHarness:
    engine: Engine
    session_factory: sessionmaker[Session]
    affiliations: dict[tuple[int, str], str]
    audits: list[dict[str, Any]]


@pytest.fixture
def runtime_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> RuntimeHarness:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'c19-moments.db'}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: Any, _: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            OrganizationRecord.__table__,
            OrgMembershipRecord.__table__,
            C19ProfileRecord.__table__,
            C19AffiliationRecord.__table__,
            C19FriendRequestRecord.__table__,
            C19RelationshipRecord.__table__,
            C19UserBlockRecord.__table__,
        ],
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    now = datetime.now(UTC)
    user_orgs = {
        1: (ORG_ONE, ORG_TWO),
        2: (ORG_ONE,),
        3: (ORG_TWO,),
        # User 4 keeps C19 access through ORG_THREE even if the selected
        # ORG_ONE affiliation later becomes inactive.
        4: (ORG_THREE, ORG_ONE),
        5: (ORG_ONE,),
        6: (ORG_ONE,),
    }
    affiliations: dict[tuple[int, str], str] = {}
    with factory() as db:
        db.add_all(
            [
                OrganizationRecord(
                    org_id=org_id,
                    name=name,
                    org_type="company",
                    owner_user_id=str(owner),
                    status="active",
                    metadata_json={},
                )
                for org_id, name, owner in (
                    (ORG_ONE, "Organization One", 1),
                    (ORG_TWO, "Organization Two", 3),
                    (ORG_THREE, "Organization Three", 4),
                )
            ]
        )
        db.add_all(
            [
                User(
                    id=user_id,
                    username=f"moment-user-{user_id}",
                    password_hash="unused",
                    role="admin" if user_id == 4 else "member",
                    organization_id=org_ids[0],
                    must_change_password=False,
                    is_active=user_id != 6,
                )
                for user_id, org_ids in user_orgs.items()
            ]
        )
        db.flush()
        db.add_all(
            [
                C19ProfileRecord(
                    user_id=user_id,
                    display_name=f"Moment User {user_id}",
                    avatar_ref=f"avatar-{user_id}",
                )
                for user_id in user_orgs
            ]
        )
        db.flush()
        affiliation_rows: list[C19AffiliationRecord] = []
        for user_id, org_ids in user_orgs.items():
            for offset, org_id in enumerate(org_ids):
                membership_id = f"moment-membership-{user_id}-{offset}"
                affiliation_id = f"moment-affiliation-{user_id}-{offset}"
                affiliations[(user_id, org_id)] = affiliation_id
                db.add(
                    OrgMembershipRecord(
                        membership_id=membership_id,
                        user_id=str(user_id),
                        org_id=org_id,
                        role="member",
                        status="active",
                        joined_at=now,
                    )
                )
                affiliation_rows.append(
                    C19AffiliationRecord(
                        affiliation_id=affiliation_id,
                        user_id=user_id,
                        org_id=org_id,
                        source_membership_id=membership_id,
                        role="member",
                        status="active",
                        joined_at=now,
                    )
                )
        # There is no ORM relationship between the authoritative C18 row and
        # its C19 projection, so make the foreign-key phase explicit.
        db.flush()
        db.add_all(affiliation_rows)
        db.flush()
        db.add_all(
            [
                C19RelationshipRecord(
                    relationship_id=f"moment-rel-1-{peer}",
                    pair_key=f"1:{peer}",
                    user_low_id=1,
                    user_high_id=peer,
                    status="friends",
                    established_at=now,
                )
                for peer in (3, 5)
            ]
        )
        # Blocking is symmetric for visibility even though the privacy row is
        # directionally owned. User 5 must be removed from every audience kind.
        db.add(
            C19UserBlockRecord(
                block_id="moment-block-5-1",
                blocker_user_id=5,
                blocked_user_id=1,
                status="active",
                is_active=True,
                blocked_at=now,
                revoked_at=None,
            )
        )
        db.commit()

    audits: list[dict[str, Any]] = []

    def _capture_audit(_: Session, **values: Any) -> None:
        audits.append(values)

    monkeypatch.setattr(moment_service, "_write_audit", _capture_audit)
    harness = RuntimeHarness(engine, factory, affiliations, audits)
    yield harness
    engine.dispose()


def _actor(db: Session, user_id: int) -> User:
    actor = db.get(User, user_id)
    assert actor is not None
    return actor


def _reference(index: int, *, ordinal: int | None = None) -> ChatAssetReferenceDTO:
    return ChatAssetReferenceDTO(
        asset_id=_asset_id(index),
        client_asset_id=f"browser-asset-{index}",
        kind="image",
        filename=f"moment-{index}.jpg",
        media_type="image/jpeg",
        size_bytes=1000 + index,
        sha256_hex=f"{index + 1:064x}"[-64:],
        version=1,
        ordinal=index if ordinal is None else ordinal,
    )


def _moment_asset(index: int, *, owner: str = "1", moment_id: str = MOMENT_ID) -> MomentAssetDTO:
    reference = _reference(index)
    return MomentAssetDTO(
        asset_id=reference.asset_id,
        client_asset_id=reference.client_asset_id,
        owner_user_id=owner,
        moment_id=moment_id,
        kind="image",
        filename=reference.filename,
        media_type=reference.media_type,
        size_bytes=reference.size_bytes,
        sha256_hex=reference.sha256_hex,
        version=reference.version,
        status="active",
    )


class FakeMomentAssetStore:
    def __init__(
        self,
        *,
        asset_count: int = 9,
        timeline: list[tuple[str, str]] | None = None,
    ) -> None:
        self.assets = {index: _moment_asset(index) for index in range(asset_count)}
        self.uploads: list[MomentAssetUploadMetadataDTO] = []
        self.prepares: list[MomentAssetBindingPrepareDTO] = []
        self.commits: list[MomentAssetBindingCommitDTO] = []
        self.downloads: list[MomentAssetDownloadRequestDTO] = []
        self.deletes: list[ChatAssetDeleteCommandDTO] = []
        self.calls: list[tuple[str, str]] = []
        self.timeline = timeline
        self.fail_commit_once = False
        self.fail_delete_once = False
        self.transfer: ScopedAssetTransferInspectionDTO | None = None

    @property
    def capability(self) -> StorageCapabilityDescription:
        return StorageCapabilityDescription(
            store_name="chat_asset_store",
            status="configured",
            configured=True,
            readable=True,
            writable=True,
            durable=True,
            external_io_enabled=True,
            operations=MOMENT_ASSET_STORE_OPERATIONS,
            reason="fake Moment asset store",
        )

    def _get(self, asset_id: str) -> MomentAssetDTO:
        for asset in self.assets.values():
            if asset.asset_id == asset_id:
                return asset
        raise ChatAssetStoreRejectedError(operation="get_moment_asset", status_code=404)

    async def create_moment_upload_intent(
        self, metadata: MomentAssetUploadMetadataDTO
    ) -> MomentAssetUploadHandleDTO:
        self.uploads.append(metadata)
        asset = replace(
            _moment_asset(0, owner=metadata.owner_user_id, moment_id=metadata.moment_id),
            client_asset_id=metadata.client_asset_id,
            filename=metadata.filename,
            media_type=metadata.media_type,
            size_bytes=metadata.size_bytes,
            sha256_hex=metadata.sha256_hex,
            status="pending_upload",
        )
        return MomentAssetUploadHandleDTO(
            asset=asset,
            opaque_ticket=UPLOAD_TICKET,
            expires_at=datetime.now(UTC) + timedelta(minutes=2),
        )

    async def get_moment_asset(self, query: MomentAssetLookupDTO) -> MomentAssetDTO:
        asset = self._get(query.asset_id)
        if asset.owner_user_id != query.owner_user_id or asset.moment_id != query.moment_id:
            raise ChatAssetStoreRejectedError(operation="get_moment_asset", status_code=404)
        return asset

    async def finalize_moment_upload(self, command: MomentAssetFinalizeDTO) -> MomentAssetDTO:
        return await self.get_moment_asset(
            MomentAssetLookupDTO(command.asset_id, command.owner_user_id, command.moment_id)
        )

    async def prepare_moment_binding(
        self, command: MomentAssetBindingPrepareDTO
    ) -> MomentAssetBindingResultDTO:
        self.prepares.append(command)
        self.calls.append(("prepare", command.asset_id))
        if self.timeline is not None:
            self.timeline.append(("prepare", command.asset_id))
        asset = await self.get_moment_asset(
            MomentAssetLookupDTO(command.asset_id, command.owner_user_id, command.moment_id)
        )
        return MomentAssetBindingResultDTO(asset=asset, binding_status="prepared")

    async def commit_moment_binding(
        self, command: MomentAssetBindingCommitDTO
    ) -> MomentAssetBindingResultDTO:
        self.commits.append(command)
        self.calls.append(("commit", command.asset_id))
        if self.timeline is not None:
            self.timeline.append(("commit", command.asset_id))
        if self.fail_commit_once and len(self.commits) == 1:
            raise ChatAssetStoreUnavailableError(operation="commit_moment_binding")
        asset = await self.get_moment_asset(
            MomentAssetLookupDTO(command.asset_id, command.owner_user_id, command.moment_id)
        )
        return MomentAssetBindingResultDTO(asset=asset, binding_status="committed")

    async def create_moment_download_intent(
        self, command: MomentAssetDownloadRequestDTO
    ) -> ChatAssetDownloadIntentDTO:
        self.downloads.append(command)
        return ChatAssetDownloadIntentDTO(
            opaque_ticket=DOWNLOAD_TICKET,
            expires_at=datetime.now(UTC) + timedelta(minutes=1),
        )

    async def inspect_scoped_transfer(
        self,
        *,
        opaque_ticket: str,
        direction: str,
        method: str,
    ) -> ScopedAssetTransferInspectionDTO:
        del opaque_ticket, direction, method
        if self.transfer is None:
            raise ChatAssetStoreRejectedError(
                operation="inspect_scoped_transfer", status_code=404
            )
        return self.transfer

    async def delete_asset(
        self, command: ChatAssetDeleteCommandDTO
    ) -> ChatAssetLifecycleResultDTO:
        self.deletes.append(command)
        if self.fail_delete_once and len(self.deletes) == 1:
            raise ChatAssetStoreUnavailableError(operation="delete_asset")
        return ChatAssetLifecycleResultDTO(
            asset_id=command.asset_id,
            status="deleted",
            version=2,
        )


class FakeMomentStore:
    def __init__(
        self,
        *,
        timeline: list[tuple[str, str]] | None = None,
    ) -> None:
        self.drafts: dict[str, MomentDraftDTO] = {}
        self.moments: dict[str, MomentDTO] = {}
        self.audiences: dict[str, set[str]] = {}
        self.publish_commands: list[MomentPublishDTO] = []
        self.queries: list[MomentQueryDTO] = []
        self.feed_queries: list[MomentFeedQueryDTO] = []
        self.likes: dict[str, set[str]] = {}
        self.comments: dict[str, list[MomentCommentDTO]] = {}
        self.calls: list[tuple[str, str]] = []
        self.timeline = timeline

    @property
    def capability(self) -> StorageCapabilityDescription:
        return StorageCapabilityDescription(
            store_name="chat_record_store",
            status="configured",
            configured=True,
            readable=True,
            writable=True,
            durable=True,
            external_io_enabled=True,
            operations=MOMENT_STORE_OPERATIONS,
            reason="fake Moment record store",
        )

    async def reserve_moment(self, command: MomentDraftReserveDTO) -> MomentDraftDTO:
        for draft in self.drafts.values():
            if (
                draft.author_user_id == command.author_user_id
                and draft.client_moment_id == command.client_moment_id
            ):
                return draft
        moment_id = MOMENT_ID if not self.drafts else OTHER_MOMENT_ID
        draft = MomentDraftDTO(
            moment_id=moment_id,
            client_moment_id=command.client_moment_id,
            author_user_id=command.author_user_id,
            state="draft",
            created_at=datetime.now(UTC),
            persisted_at=datetime.now(UTC),
        )
        self.drafts[moment_id] = draft
        return draft

    async def get_moment_draft(self, *, moment_id: str, author_user_id: str) -> MomentDraftDTO:
        draft = self.drafts.get(moment_id)
        if draft is None or draft.author_user_id != author_user_id:
            raise ChatRecordStoreRejectedError(operation="get_moment_draft", status_code=404)
        return draft

    async def publish_moment(self, command: MomentPublishDTO) -> MomentDTO:
        self.publish_commands.append(command)
        self.calls.append(("publish", command.moment_id))
        if self.timeline is not None:
            self.timeline.append(("publish", command.moment_id))
        existing = self.moments.get(command.moment_id)
        if existing is not None:
            return existing
        draft = self.drafts[command.moment_id]
        result = MomentDTO(
            moment_id=command.moment_id,
            client_moment_id=command.client_moment_id,
            author_user_id=command.author_user_id,
            author_org_id=command.author_org_id,
            visibility=command.visibility,
            audience_org_ids=command.audience_org_ids,
            content=command.content,
            state="published",
            created_at=draft.created_at,
            published_at=datetime.now(UTC),
            assets=command.assets,
            like_count=0,
            comment_count=0,
            viewer_has_liked=False,
        )
        self.moments[command.moment_id] = result
        self.audiences[command.moment_id] = set(command.audience_user_ids)
        self.drafts[command.moment_id] = replace(draft, state="published")
        return result

    def _authorize(self, context: MomentViewerContextDTO, moment: MomentDTO) -> None:
        viewer = context.viewer_user_id
        if viewer not in set(context.active_user_ids) or viewer not in self.audiences[moment.moment_id]:
            raise ChatRecordStoreRejectedError(operation="get_moment", status_code=404)
        if viewer == moment.author_user_id:
            return
        if moment.author_user_id in set(context.blocked_user_ids):
            raise ChatRecordStoreRejectedError(operation="get_moment", status_code=404)
        if moment.visibility == "private":
            raise ChatRecordStoreRejectedError(operation="get_moment", status_code=404)
        if moment.visibility == "friends" and moment.author_user_id not in set(context.friend_user_ids):
            raise ChatRecordStoreRejectedError(operation="get_moment", status_code=404)
        if moment.visibility == "org" and not (
            set(moment.audience_org_ids) & set(context.active_org_ids)
        ):
            raise ChatRecordStoreRejectedError(operation="get_moment", status_code=404)

    async def get_moment(self, query: MomentQueryDTO) -> MomentDTO:
        self.queries.append(query)
        moment = self.moments.get(query.moment_id)
        if moment is None:
            raise ChatRecordStoreRejectedError(operation="get_moment", status_code=404)
        self._authorize(query.context, moment)
        return replace(
            moment,
            viewer_has_liked=query.context.viewer_user_id
            in self.likes.get(query.moment_id, set()),
            like_count=len(self.likes.get(query.moment_id, set())),
            comment_count=len(
                [item for item in self.comments.get(query.moment_id, []) if item.state == "active"]
            ),
        )

    async def list_moment_feed(self, query: MomentFeedQueryDTO) -> MomentFeedPageDTO:
        self.feed_queries.append(query)
        visible: list[MomentDTO] = []
        for moment in self.moments.values():
            try:
                self._authorize(query.context, moment)
            except ChatRecordStoreRejectedError:
                continue
            visible.append(moment)
        return MomentFeedPageDTO(
            moments=tuple(visible[: query.limit]),
            next_cursor=query.cursor,
            latest_event_sequence=0,
        )

    async def set_moment_like(self, command: MomentLikeCommandDTO) -> MomentLikeResultDTO:
        moment = self.moments[command.moment_id]
        self._authorize(command.context, moment)
        users = self.likes.setdefault(command.moment_id, set())
        before = command.context.viewer_user_id in users
        if command.liked:
            users.add(command.context.viewer_user_id)
        else:
            users.discard(command.context.viewer_user_id)
        return MomentLikeResultDTO(
            moment_id=command.moment_id,
            user_id=command.context.viewer_user_id,
            liked=command.liked,
            changed=before != command.liked,
            like_count=len(users),
            updated_at=command.occurred_at,
        )

    async def list_moment_likes(self, query: MomentLikeQueryDTO) -> MomentLikePageDTO:
        self._authorize(query.context, self.moments[query.moment_id])
        likes = tuple(
            MomentLikeDTO(user_id=user_id, sequence=index, created_at=datetime.now(UTC))
            for index, user_id in enumerate(sorted(self.likes.get(query.moment_id, set())), 1)
        )
        return MomentLikePageDTO(likes=likes[: query.limit], next_cursor=None)

    async def create_moment_comment(self, command: MomentCommentCreateDTO) -> MomentCommentDTO:
        self._authorize(command.context, self.moments[command.moment_id])
        existing = self.comments.setdefault(command.moment_id, [])
        for item in existing:
            if item.author_user_id == command.author_user_id and item.client_comment_id == command.client_comment_id:
                return item
        comment = MomentCommentDTO(
            comment_id=COMMENT_ID,
            client_comment_id=command.client_comment_id,
            moment_id=command.moment_id,
            author_user_id=command.author_user_id,
            content=command.content,
            state="active",
            sequence=len(existing) + 1,
            created_at=datetime.now(UTC),
            persisted_at=datetime.now(UTC),
        )
        existing.append(comment)
        return comment

    async def list_moment_comments(self, query: MomentCommentQueryDTO) -> MomentCommentPageDTO:
        self._authorize(query.context, self.moments[query.moment_id])
        comments = tuple(self.comments.get(query.moment_id, ()))
        return MomentCommentPageDTO(comments=comments[: query.limit], next_cursor=None)

    async def delete_moment_comment(
        self, command: MomentCommentDeleteDTO
    ) -> MomentCommentDeleteResultDTO:
        moment = self.moments[command.moment_id]
        self._authorize(command.context, moment)
        for index, comment in enumerate(self.comments.get(command.moment_id, [])):
            if comment.comment_id == command.comment_id:
                if command.requested_by_user_id not in {comment.author_user_id, moment.author_user_id}:
                    raise ChatRecordStoreRejectedError(
                        operation="delete_moment_comment", status_code=404
                    )
                changed = comment.state == "active"
                self.comments[command.moment_id][index] = replace(comment, state="deleted", content="")
                return MomentCommentDeleteResultDTO(
                    moment_id=command.moment_id,
                    comment_id=command.comment_id,
                    state="deleted",
                    changed=changed,
                    comment_count=len(
                        [
                            item
                            for item in self.comments[command.moment_id]
                            if item.state == "active"
                        ]
                    ),
                    deleted_at=command.requested_at,
                )
        raise ChatRecordStoreRejectedError(operation="delete_moment_comment", status_code=404)

    async def begin_moment_delete(self, command: MomentDeleteCommandDTO) -> MomentDeleteResultDTO:
        moment = self.moments[command.moment_id]
        if moment.author_user_id != command.requested_by_user_id:
            raise ChatRecordStoreRejectedError(operation="begin_moment_delete", status_code=404)
        changed = moment.state == "published"
        self.moments[command.moment_id] = replace(moment, state="delete_pending", content="")
        self.drafts[command.moment_id] = replace(
            self.drafts[command.moment_id], state="delete_pending"
        )
        return MomentDeleteResultDTO(
            moment_id=command.moment_id,
            state="delete_pending",
            assets=moment.assets,
            changed=changed,
            updated_at=command.requested_at,
        )

    async def complete_moment_delete(self, command: MomentDeleteCommandDTO) -> MomentDeleteResultDTO:
        self.moments[command.moment_id] = replace(
            self.moments[command.moment_id], state="deleted", assets=()
        )
        self.drafts[command.moment_id] = replace(
            self.drafts[command.moment_id], state="deleted"
        )
        return MomentDeleteResultDTO(
            moment_id=command.moment_id,
            state="deleted",
            assets=(),
            changed=True,
            updated_at=command.requested_at,
        )

    async def list_moment_events(
        self, query: MomentUserEventQueryDTO
    ) -> MomentUserEventPageDTO:
        del query
        return MomentUserEventPageDTO(events=(), next_cursor=None, latest_event_sequence=0)

    async def get_moment_event_tail(
        self, context: MomentViewerContextDTO
    ) -> MomentUserEventTailDTO:
        return MomentUserEventTailDTO(
            user_id=context.viewer_user_id,
            cursor="tail",
            latest_event_sequence=0,
        )


def _create_and_publish(
    db: Session,
    *,
    store: FakeMomentStore,
    asset_store: FakeMomentAssetStore,
    visibility: str = "public",
    affiliation_ids: list[str] | None = None,
    asset_ids: list[str] | None = None,
):
    draft = asyncio.run(
        create_moment_draft(
            db,
            actor=_actor(db, 1),
            payload=MomentDraftCreateRequest(client_moment_id="browser-moment-1"),
            store=store,
        )
    )
    result = asyncio.run(
        publish_moment(
            db,
            actor=_actor(db, 1),
            moment_id=draft.moment_id,
            payload=MomentPublishRequest(
                content="The Moment body stays outside Barong.",
                visibility=visibility,  # type: ignore[arg-type]
                audience_affiliation_ids=affiliation_ids or [],
                asset_ids=asset_ids or [],
            ),
            store=store,
            asset_store=asset_store,
        )
    )
    return draft, result


def test_publish_audience_uses_global_users_owned_affiliations_and_blocks(
    runtime_harness: RuntimeHarness,
) -> None:
    with runtime_harness.session_factory() as db:
        actor = _actor(db, 1)
        public = resolve_publish_audience(
            db, actor=actor, visibility="public", audience_affiliation_ids=[]
        )
        friends = resolve_publish_audience(
            db, actor=actor, visibility="friends", audience_affiliation_ids=[]
        )
        private = resolve_publish_audience(
            db, actor=actor, visibility="private", audience_affiliation_ids=[]
        )
        org = resolve_publish_audience(
            db,
            actor=actor,
            visibility="org",
            audience_affiliation_ids=[
                runtime_harness.affiliations[(1, ORG_ONE)],
                runtime_harness.affiliations[(1, ORG_TWO)],
            ],
        )

        assert public.audience_user_ids == ("1", "2", "3", "4")
        assert public.audience_org_ids == ()
        assert friends.audience_user_ids == ("1", "3")
        assert private.audience_user_ids == ("1",)
        assert org.audience_user_ids == ("1", "2", "3", "4")
        assert org.audience_org_ids == (ORG_ONE, ORG_TWO)
        assert org.author_org_id is None

        single_org = resolve_publish_audience(
            db,
            actor=actor,
            visibility="org",
            audience_affiliation_ids=[runtime_harness.affiliations[(1, ORG_ONE)]],
        )
        assert single_org.author_org_id == ORG_ONE

        with pytest.raises(C19MomentPolicyError) as wrong_owner:
            resolve_publish_audience(
                db,
                actor=actor,
                visibility="org",
                audience_affiliation_ids=[runtime_harness.affiliations[(2, ORG_ONE)]],
            )
        assert wrong_owner.value.code == "c19_moment_audience_invalid"
        assert wrong_owner.value.status_code == 422


def test_affiliation_free_viewer_can_use_public_friends_and_private_moments(
    runtime_harness: RuntimeHarness,
) -> None:
    with runtime_harness.session_factory() as db:
        actor = User(
            id=7,
            username="moment-native-user",
            password_hash="unused",
            role="viewer",
            organization_id=None,
            must_change_password=False,
            is_active=True,
        )
        db.add(actor)
        db.flush()
        db.add(C19ProfileRecord(user_id=7, display_name="Moment Native User"))
        db.commit()

        public = resolve_publish_audience(
            db,
            actor=actor,
            visibility="public",
            audience_affiliation_ids=[],
        )
        friends = resolve_publish_audience(
            db,
            actor=actor,
            visibility="friends",
            audience_affiliation_ids=[],
        )
        private = resolve_publish_audience(
            db,
            actor=actor,
            visibility="private",
            audience_affiliation_ids=[],
        )

        assert public.audience_user_ids == ("1", "2", "3", "4", "5", "7")
        assert friends.audience_user_ids == ("7",)
        assert private.audience_user_ids == ("7",)
        assert public.author_org_id is None

        with pytest.raises(C19MomentPolicyError) as missing_explicit_org:
            resolve_publish_audience(
                db,
                actor=actor,
                visibility="org",
                audience_affiliation_ids=[],
            )
        assert missing_explicit_org.value.code == "c19_moment_audience_invalid"


def test_each_visibility_enforces_snapshot_and_current_relationship_or_org_context(
    runtime_harness: RuntimeHarness,
) -> None:
    with runtime_harness.session_factory() as db:
        stores: dict[str, FakeMomentStore] = {}
        cases = (
            ("public", [], 4, ("1", "2", "3", "4")),
            ("friends", [], 3, ("1", "3")),
            ("private", [], 1, ("1",)),
            (
                "org",
                [runtime_harness.affiliations[(1, ORG_ONE)]],
                4,
                ("1", "2", "4"),
            ),
        )
        for visibility, affiliation_ids, allowed_reader, expected_audience in cases:
            store = FakeMomentStore()
            stores[visibility] = store
            asset_store = FakeMomentAssetStore()
            _create_and_publish(
                db,
                store=store,
                asset_store=asset_store,
                visibility=visibility,
                affiliation_ids=affiliation_ids,
            )
            assert store.publish_commands[0].audience_user_ids == expected_audience
            visible = asyncio.run(
                get_moment(
                    db,
                    actor=_actor(db, allowed_reader),
                    moment_id=MOMENT_ID,
                    store=store,
                )
            )
            assert visible.visibility == visibility

        for visibility, denied_reader in (
            ("friends", 2),
            ("private", 2),
            ("private", 4),
            ("org", 3),
        ):
            with pytest.raises(ChatRecordStoreRejectedError):
                asyncio.run(
                    get_moment(
                        db,
                        actor=_actor(db, denied_reader),
                        moment_id=MOMENT_ID,
                        store=stores[visibility],
                    )
                )

        relationship = db.get(C19RelationshipRecord, "moment-rel-1-3")
        assert relationship is not None
        relationship.status = "removed"
        relationship.ended_at = datetime.now(UTC)
        db.commit()
        with pytest.raises(ChatRecordStoreRejectedError):
            asyncio.run(
                get_moment(
                    db,
                    actor=_actor(db, 3),
                    moment_id=MOMENT_ID,
                    store=stores["friends"],
                )
            )
        assert "1" not in stores["friends"].queries[-1].context.friend_user_ids

        membership = db.get(OrgMembershipRecord, "moment-membership-4-1")
        assert membership is not None and membership.org_id == ORG_ONE
        membership.status = "suspended"
        db.commit()
        with pytest.raises(ChatRecordStoreRejectedError):
            asyncio.run(
                get_moment(
                    db,
                    actor=_actor(db, 4),
                    moment_id=MOMENT_ID,
                    store=stores["org"],
                )
            )
        context = stores["org"].queries[-1].context
        assert context.active_org_ids == (ORG_THREE,)


def test_moment_schemas_enforce_text_visibility_unique_affiliations_and_nine_images() -> None:
    valid = MomentPublishRequest(
        content="",
        visibility="private",
        asset_ids=[_asset_id(index) for index in range(9)],
    )
    assert len(valid.asset_ids) == 9
    for values in (
        {"content": "", "asset_ids": []},
        {"content": "text", "visibility": "org", "audience_affiliation_ids": []},
        {"content": "text", "visibility": "public", "audience_affiliation_ids": ["a"]},
        {"content": "text", "asset_ids": [_asset_id(1), _asset_id(1)]},
        {"content": "text", "asset_ids": [_asset_id(index) for index in range(10)]},
        {"content": "bad\x00text"},
    ):
        with pytest.raises(ValidationError):
            MomentPublishRequest.model_validate(values)

    event = MomentEventRead(
        event_id="moment-event-1",
        event_sequence=1,
        event_type="published",
        moment_id=MOMENT_ID,
        actor_user_id=1,
        comment_id=None,
        created_at=datetime.now(UTC),
    )
    assert set(MomentEventRead.model_fields) == {
        "event_id",
        "event_sequence",
        "event_type",
        "moment_id",
        "actor_user_id",
        "comment_id",
        "created_at",
    }
    with pytest.raises(ValidationError):
        MomentEventRead.model_validate(
            {**event.model_dump(), "content": "must never ride realtime events"}
        )


def test_draft_and_upload_are_scoped_to_global_author_not_request_fields(
    runtime_harness: RuntimeHarness,
) -> None:
    store = FakeMomentStore()
    asset_store = FakeMomentAssetStore()
    with runtime_harness.session_factory() as db:
        draft = asyncio.run(
            create_moment_draft(
                db,
                actor=_actor(db, 1),
                payload=MomentDraftCreateRequest(client_moment_id="draft-owner-test"),
                store=store,
            )
        )
        result = asyncio.run(
            create_moment_asset_upload_intent(
                db,
                actor=_actor(db, 1),
                moment_id=draft.moment_id,
                payload=MomentAssetUploadIntentRequest(
                    client_asset_id="upload-owner-test",
                    kind="image",
                    filename="owner.jpg",
                    media_type="image/jpeg",
                    size_bytes=123,
                    sha256_hex="1" * 64,
                ),
                store=store,
                asset_store=asset_store,
            )
        )
        assert result.moment_id == draft.moment_id
        assert result.upload_locator == f"/api/backend/c19-assets/u/{UPLOAD_TICKET}"
        assert asset_store.uploads[0].owner_user_id == "1"
        assert asset_store.uploads[0].moment_id == draft.moment_id

        with pytest.raises(ChatRecordStoreRejectedError):
            asyncio.run(
                create_moment_asset_upload_intent(
                    db,
                    actor=_actor(db, 2),
                    moment_id=draft.moment_id,
                    payload=MomentAssetUploadIntentRequest(
                        client_asset_id="idor",
                        kind="image",
                        filename="idor.jpg",
                        media_type="image/jpeg",
                        size_bytes=1,
                        sha256_hex="2" * 64,
                    ),
                    store=store,
                    asset_store=asset_store,
                )
            )
    assert len(asset_store.uploads) == 1


def test_publish_prepares_all_images_then_records_snapshot_then_commits_in_order(
    runtime_harness: RuntimeHarness,
) -> None:
    timeline: list[tuple[str, str]] = []
    store = FakeMomentStore(timeline=timeline)
    asset_store = FakeMomentAssetStore(timeline=timeline)
    with runtime_harness.session_factory() as db:
        _, result = _create_and_publish(
            db,
            store=store,
            asset_store=asset_store,
            asset_ids=[_asset_id(index) for index in range(9)],
        )
    command = store.publish_commands[0]
    assert result.author.user_id == 1
    assert result.author.display_name == "Moment User 1"
    assert [item.asset_id for item in command.assets] == [
        _asset_id(index) for index in range(9)
    ]
    assert [item.ordinal for item in command.assets] == list(range(9))
    assert command.audience_user_ids == ("1", "2", "3", "4")
    assert timeline == (
        [("prepare", _asset_id(index)) for index in range(9)]
        + [("publish", MOMENT_ID)]
        + [("commit", _asset_id(index)) for index in range(9)]
    )


def test_publish_crash_after_record_is_repaired_idempotently_on_retry(
    runtime_harness: RuntimeHarness,
) -> None:
    store = FakeMomentStore()
    asset_store = FakeMomentAssetStore(asset_count=2)
    asset_store.fail_commit_once = True
    with runtime_harness.session_factory() as db:
        draft = asyncio.run(
            create_moment_draft(
                db,
                actor=_actor(db, 1),
                payload=MomentDraftCreateRequest(client_moment_id="crash-retry"),
                store=store,
            )
        )
        payload = MomentPublishRequest(
            content="durable before bind",
            asset_ids=[_asset_id(0), _asset_id(1)],
        )
        with pytest.raises(ChatAssetStoreUnavailableError):
            asyncio.run(
                publish_moment(
                    db,
                    actor=_actor(db, 1),
                    moment_id=draft.moment_id,
                    payload=payload,
                    store=store,
                    asset_store=asset_store,
                )
            )
        repaired = asyncio.run(
            publish_moment(
                db,
                actor=_actor(db, 1),
                moment_id=draft.moment_id,
                payload=payload,
                store=store,
                asset_store=asset_store,
            )
        )
    assert repaired.moment_id == MOMENT_ID
    assert len(store.moments) == 1
    # The retry reads the already durable immutable Moment and repairs only the
    # unfinished bindings; it must not republish or recompute the audience.
    assert len(store.publish_commands) == 1
    assert [command.asset_id for command in asset_store.prepares] == [
        _asset_id(0),
        _asset_id(1),
    ]
    assert [command.asset_id for command in asset_store.commits] == [
        _asset_id(0),
        _asset_id(0),
        _asset_id(1),
    ]
    recovered_audits = [
        item
        for item in runtime_harness.audits
        if item["action"] == "c19.moment.publish"
    ]
    assert len(recovered_audits) == 1
    assert recovered_audits[0]["details"]["recovered"] is True


def test_read_access_uses_snapshot_and_live_context_to_only_tighten(
    runtime_harness: RuntimeHarness,
) -> None:
    store = FakeMomentStore()
    asset_store = FakeMomentAssetStore()
    with runtime_harness.session_factory() as db:
        _create_and_publish(db, store=store, asset_store=asset_store)
        visible = asyncio.run(
            get_moment(db, actor=_actor(db, 2), moment_id=MOMENT_ID, store=store)
        )
        assert visible.author.user_id == 1
        assert store.queries[-1].context.viewer_user_id == "2"

        db.add(
            C19UserBlockRecord(
                block_id="moment-block-2-1",
                blocker_user_id=2,
                blocked_user_id=1,
                status="active",
                is_active=True,
                blocked_at=datetime.now(UTC),
                revoked_at=None,
            )
        )
        db.commit()
        with pytest.raises(ChatRecordStoreRejectedError):
            asyncio.run(
                get_moment(db, actor=_actor(db, 2), moment_id=MOMENT_ID, store=store)
            )
        assert "1" in store.queries[-1].context.blocked_user_ids

        # A new active user was not in the immutable publish snapshot and may
        # not gain access merely because public currently includes all members.
        store.audiences[MOMENT_ID].discard("4")
        with pytest.raises(ChatRecordStoreRejectedError):
            asyncio.run(
                get_moment(db, actor=_actor(db, 4), moment_id=MOMENT_ID, store=store)
            )


def test_feed_like_comment_profiles_delete_and_audit_never_leak_body(
    runtime_harness: RuntimeHarness,
) -> None:
    store = FakeMomentStore()
    asset_store = FakeMomentAssetStore(asset_count=1)
    secret_body = "SECRET-MOMENT-BODY-9f29"
    secret_comment = "SECRET-COMMENT-BODY-a821"
    with runtime_harness.session_factory() as db:
        draft = asyncio.run(
            create_moment_draft(
                db,
                actor=_actor(db, 1),
                payload=MomentDraftCreateRequest(client_moment_id="social-runtime"),
                store=store,
            )
        )
        published = asyncio.run(
            publish_moment(
                db,
                actor=_actor(db, 1),
                moment_id=draft.moment_id,
                payload=MomentPublishRequest(
                    content=secret_body,
                    asset_ids=[_asset_id(0)],
                ),
                store=store,
                asset_store=asset_store,
            )
        )
        assert published.content == secret_body

        like = asyncio.run(
            set_moment_like(
                db,
                actor=_actor(db, 2),
                moment_id=MOMENT_ID,
                liked=True,
                store=store,
            )
        )
        replay = asyncio.run(
            set_moment_like(
                db,
                actor=_actor(db, 2),
                moment_id=MOMENT_ID,
                liked=True,
                store=store,
            )
        )
        assert like.changed is True and replay.changed is False
        like_page = asyncio.run(
            list_moment_likes(
                db,
                actor=_actor(db, 1),
                moment_id=MOMENT_ID,
                limit=50,
                cursor=None,
                store=store,
            )
        )
        assert like_page.likes[0].profile.display_name == "Moment User 2"

        comment = asyncio.run(
            create_moment_comment(
                db,
                actor=_actor(db, 2),
                moment_id=MOMENT_ID,
                payload=MomentCommentCreateRequest(
                    client_comment_id="comment-runtime",
                    content=secret_comment,
                ),
                store=store,
            )
        )
        assert comment.author.user_id == 2
        page = asyncio.run(
            list_moment_comments(
                db,
                actor=_actor(db, 1),
                moment_id=MOMENT_ID,
                limit=50,
                cursor=None,
                store=store,
            )
        )
        assert page.comments[0].content == secret_comment
        with pytest.raises(ChatRecordStoreRejectedError):
            asyncio.run(
                delete_moment_comment(
                    db,
                    actor=_actor(db, 4),
                    moment_id=MOMENT_ID,
                    comment_id=COMMENT_ID,
                    store=store,
                )
            )
        deleted_comment = asyncio.run(
            delete_moment_comment(
                db,
                actor=_actor(db, 1),
                moment_id=MOMENT_ID,
                comment_id=COMMENT_ID,
                store=store,
            )
        )
        assert deleted_comment.state == "deleted"

        feed = asyncio.run(
            list_moment_feed(
                db,
                actor=_actor(db, 2),
                limit=20,
                cursor=None,
                store=store,
            )
        )
        assert feed.moments[0].author.display_name == "Moment User 1"

        with pytest.raises(ChatRecordStoreRejectedError):
            asyncio.run(
                delete_moment(
                    db,
                    actor=_actor(db, 2),
                    moment_id=MOMENT_ID,
                    store=store,
                    asset_store=asset_store,
                )
            )
        deleted = asyncio.run(
            delete_moment(
                db,
                actor=_actor(db, 1),
                moment_id=MOMENT_ID,
                store=store,
                asset_store=asset_store,
            )
        )
        assert deleted.state == "deleted"
    assert [item.asset_id for item in asset_store.deletes] == [_asset_id(0)]
    serialized_audits = repr(runtime_harness.audits)
    assert secret_body not in serialized_audits
    assert secret_comment not in serialized_audits
    assert {item["action"] for item in runtime_harness.audits} >= {
        "c19.moment.publish",
        "c19.moment.like",
        "c19.moment.comment.create",
        "c19.moment.comment.delete",
        "c19.moment.delete",
    }


def test_delete_crash_keeps_tombstone_refs_and_retry_finishes_asset_cleanup(
    runtime_harness: RuntimeHarness,
) -> None:
    store = FakeMomentStore()
    asset_store = FakeMomentAssetStore(asset_count=2)
    asset_store.fail_delete_once = True
    with runtime_harness.session_factory() as db:
        _create_and_publish(
            db,
            store=store,
            asset_store=asset_store,
            asset_ids=[_asset_id(0), _asset_id(1)],
        )
        with pytest.raises(ChatAssetStoreUnavailableError):
            asyncio.run(
                delete_moment(
                    db,
                    actor=_actor(db, 1),
                    moment_id=MOMENT_ID,
                    store=store,
                    asset_store=asset_store,
                )
            )
        pending = store.moments[MOMENT_ID]
        assert pending.state == "delete_pending"
        assert pending.content == ""
        assert [item.asset_id for item in pending.assets] == [
            _asset_id(0),
            _asset_id(1),
        ]

        completed = asyncio.run(
            delete_moment(
                db,
                actor=_actor(db, 1),
                moment_id=MOMENT_ID,
                store=store,
                asset_store=asset_store,
            )
        )
        assert completed.state == "deleted"
        assert store.moments[MOMENT_ID].assets == ()
    assert [item.asset_id for item in asset_store.deletes] == [
        _asset_id(0),
        _asset_id(0),
        _asset_id(1),
    ]
    delete_audits = [
        item
        for item in runtime_harness.audits
        if item["action"] == "c19.moment.delete"
    ]
    assert len(delete_audits) == 1


def test_asset_access_requires_exact_durable_reference_and_current_reader(
    runtime_harness: RuntimeHarness,
) -> None:
    store = FakeMomentStore()
    asset_store = FakeMomentAssetStore(asset_count=1)
    with runtime_harness.session_factory() as db:
        _create_and_publish(
            db,
            store=store,
            asset_store=asset_store,
            asset_ids=[_asset_id(0)],
        )
        intent = asyncio.run(
            create_moment_asset_access_intent(
                db,
                actor=_actor(db, 2),
                moment_id=MOMENT_ID,
                asset_id=_asset_id(0),
                payload=MomentAssetAccessIntentRequest(variant="thumbnail"),
                store=store,
                asset_store=asset_store,
            )
        )
        assert intent.download_locator == f"/api/backend/c19-assets/d/{DOWNLOAD_TICKET}"
        command = asset_store.downloads[-1]
        assert command.owner_user_id == "1"
        assert command.reader_user_id == "2"
        assert command.moment_id == MOMENT_ID
        assert command.asset_version == 1
        assert command.variant == "thumbnail"

        with pytest.raises(C19MomentAccessError):
            asyncio.run(
                create_moment_asset_access_intent(
                    db,
                    actor=_actor(db, 2),
                    moment_id=MOMENT_ID,
                    asset_id=_asset_id(8),
                    payload=MomentAssetAccessIntentRequest(),
                    store=store,
                    asset_store=asset_store,
                )
            )
        assert len(asset_store.downloads) == 1

        asset_store.assets[0] = replace(asset_store.assets[0], version=2)
        with pytest.raises(C19MomentAccessError):
            asyncio.run(
                create_moment_asset_access_intent(
                    db,
                    actor=_actor(db, 2),
                    moment_id=MOMENT_ID,
                    asset_id=_asset_id(0),
                    payload=MomentAssetAccessIntentRequest(),
                    store=store,
                    asset_store=asset_store,
                )
            )
        assert len(asset_store.downloads) == 1

        asset_store.assets[0] = replace(asset_store.assets[0], version=1)
        db.add(
            C19UserBlockRecord(
                block_id="moment-access-block-2-1",
                blocker_user_id=2,
                blocked_user_id=1,
                status="active",
                is_active=True,
                blocked_at=datetime.now(UTC),
                revoked_at=None,
            )
        )
        db.commit()
        with pytest.raises(ChatRecordStoreRejectedError):
            asyncio.run(
                create_moment_asset_access_intent(
                    db,
                    actor=_actor(db, 2),
                    moment_id=MOMENT_ID,
                    asset_id=_asset_id(0),
                    payload=MomentAssetAccessIntentRequest(),
                    store=store,
                    asset_store=asset_store,
                )
            )
    assert len(asset_store.downloads) == 1


def test_v2_transfer_authorization_rechecks_draft_owner_snapshot_and_live_context(
    runtime_harness: RuntimeHarness,
) -> None:
    store = FakeMomentStore()
    asset_store = FakeMomentAssetStore(asset_count=1)
    expires = datetime.now(UTC) + timedelta(minutes=1)
    with runtime_harness.session_factory() as db:
        draft = asyncio.run(
            create_moment_draft(
                db,
                actor=_actor(db, 1),
                payload=MomentDraftCreateRequest(client_moment_id="transfer-runtime"),
                store=store,
            )
        )
        asset_store.transfer = ScopedAssetTransferInspectionDTO(
            asset_id=_asset_id(0),
            owner_user_id="1",
            reader_user_id=None,
            usage="moment_image",
            scope_id=draft.moment_id,
            bound_resource_id=None,
            variant=None,
            version=1,
            expires_at=expires,
        )
        approved_upload = asyncio.run(
            authorize_asset_transfer(
                db,
                actor=_actor(db, 1),
                transfer_uri=f"/api/backend/c19-assets/u/{UPLOAD_TICKET}",
                transfer_method="PUT",
                record_store=store,  # type: ignore[arg-type]
                asset_store=asset_store,  # type: ignore[arg-type]
                moment_store=store,
                moment_asset_store=asset_store,
            )
        )
        assert approved_upload.usage == "moment_image"
        with pytest.raises(C19AssetAccessError):
            asyncio.run(
                authorize_asset_transfer(
                    db,
                    actor=_actor(db, 4),
                    transfer_uri=f"/api/backend/c19-assets/u/{UPLOAD_TICKET}",
                    transfer_method="PUT",
                    record_store=store,  # type: ignore[arg-type]
                    asset_store=asset_store,  # type: ignore[arg-type]
                    moment_store=store,
                    moment_asset_store=asset_store,
                )
            )

        asyncio.run(
            publish_moment(
                db,
                actor=_actor(db, 1),
                moment_id=draft.moment_id,
                payload=MomentPublishRequest(
                    content="transfer snapshot",
                    asset_ids=[_asset_id(0)],
                ),
                store=store,
                asset_store=asset_store,
            )
        )
        # An upload ticket cannot be used after its owning draft is published.
        with pytest.raises(C19AssetAccessError):
            asyncio.run(
                authorize_asset_transfer(
                    db,
                    actor=_actor(db, 1),
                    transfer_uri=f"/api/backend/c19-assets/u/{UPLOAD_TICKET}",
                    transfer_method="PUT",
                    record_store=store,  # type: ignore[arg-type]
                    asset_store=asset_store,  # type: ignore[arg-type]
                    moment_store=store,
                    moment_asset_store=asset_store,
                )
            )

        asset_store.transfer = ScopedAssetTransferInspectionDTO(
            asset_id=_asset_id(0),
            owner_user_id="1",
            reader_user_id="2",
            usage="moment_image",
            scope_id=MOMENT_ID,
            bound_resource_id=MOMENT_ID,
            variant="thumbnail",
            version=1,
            expires_at=expires,
        )
        approved_download = asyncio.run(
            authorize_asset_transfer(
                db,
                actor=_actor(db, 2),
                transfer_uri=f"/api/backend/c19-assets/d/{DOWNLOAD_TICKET}",
                transfer_method="HEAD",
                record_store=store,  # type: ignore[arg-type]
                asset_store=asset_store,  # type: ignore[arg-type]
                moment_store=store,
                moment_asset_store=asset_store,
            )
        )
        assert approved_download.reader_user_id == "2"

        asset_store.transfer = replace(asset_store.transfer, version=2)
        with pytest.raises(C19AssetAccessError):
            asyncio.run(
                authorize_asset_transfer(
                    db,
                    actor=_actor(db, 2),
                    transfer_uri=f"/api/backend/c19-assets/d/{DOWNLOAD_TICKET}",
                    transfer_method="GET",
                    record_store=store,  # type: ignore[arg-type]
                    asset_store=asset_store,  # type: ignore[arg-type]
                    moment_store=store,
                    moment_asset_store=asset_store,
                )
            )

        asset_store.transfer = replace(asset_store.transfer, version=1)
        db.add(
            C19UserBlockRecord(
                block_id="moment-transfer-block-2-1",
                blocker_user_id=2,
                blocked_user_id=1,
                status="active",
                is_active=True,
                blocked_at=datetime.now(UTC),
                revoked_at=None,
            )
        )
        db.commit()
        with pytest.raises(ChatRecordStoreRejectedError):
            asyncio.run(
                authorize_asset_transfer(
                    db,
                    actor=_actor(db, 2),
                    transfer_uri=f"/api/backend/c19-assets/d/{DOWNLOAD_TICKET}",
                    transfer_method="GET",
                    record_store=store,  # type: ignore[arg-type]
                    asset_store=asset_store,  # type: ignore[arg-type]
                    moment_store=store,
                    moment_asset_store=asset_store,
                )
            )

        with pytest.raises(C19AssetAccessError):
            asyncio.run(
                authorize_asset_transfer(
                    db,
                    actor=_actor(db, 1),
                    transfer_uri=f"/api/backend/c19-assets/d/{DOWNLOAD_TICKET}?leak=1",
                    transfer_method="GET",
                    record_store=store,  # type: ignore[arg-type]
                    asset_store=asset_store,  # type: ignore[arg-type]
                    moment_store=store,
                    moment_asset_store=asset_store,
                )
            )


def _moment_json(
    *,
    content: str = "provider-contract",
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    now = datetime.now(UTC).isoformat()
    result: dict[str, object] = {
        "moment_id": MOMENT_ID,
        "client_moment_id": "provider-moment",
        "author_user_id": "1",
        "author_org_id": None,
        "visibility": "public",
        "audience_org_ids": [],
        "content": content,
        "state": "published",
        "created_at": now,
        "published_at": now,
        "assets": [],
        "like_count": 0,
        "comment_count": 0,
        "viewer_has_liked": False,
    }
    result.update(extra or {})
    return result


def test_http_providers_use_exact_moment_echo_and_generic_v2_transfer_contract() -> None:
    record_requests: list[httpx.Request] = []

    def record_handler(request: httpx.Request) -> httpx.Response:
        record_requests.append(request)
        return httpx.Response(201, json=_moment_json())

    command = MomentPublishDTO(
        moment_id=MOMENT_ID,
        client_moment_id="provider-moment",
        author_user_id="1",
        author_org_id=None,
        visibility="public",
        audience_user_ids=("1", "2"),
        audience_org_ids=(),
        content="provider-contract",
        assets=(),
    )

    async def valid_record_roundtrip() -> None:
        async with HttpChatRecordStore(
            HttpChatRecordStoreConfig(
                base_url="http://c19-record-api:8089",
                token="r" * 32,
            ),
            transport=httpx.MockTransport(record_handler),
        ) as adapter:
            result = await adapter.publish_moment(command)
            assert result.content == command.content

    asyncio.run(valid_record_roundtrip())
    assert record_requests[0].url.path == f"/v1/moments/{MOMENT_ID}/publish"
    request_body = json.loads(record_requests[0].content)
    assert request_body["audience_user_ids"] == ["1", "2"]
    assert request_body["content"] == "provider-contract"

    async def mismatched_record_roundtrip(response: dict[str, object]) -> None:
        async with HttpChatRecordStore(
            HttpChatRecordStoreConfig(
                base_url="http://c19-record-api:8089",
                token="r" * 32,
            ),
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json=response)
            ),
        ) as adapter:
            with pytest.raises(ChatRecordStoreProtocolError):
                await adapter.publish_moment(command)

    asyncio.run(
        mismatched_record_roundtrip(
            _moment_json(content="provider-substituted-content")
        )
    )
    asyncio.run(
        mismatched_record_roundtrip(_moment_json(extra={"object_key": "must-not-leak"}))
    )

    expires = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()
    transfer_json = {
        "asset_id": _asset_id(0),
        "owner_user_id": "1",
        "reader_user_id": "2",
        "usage": "moment_image",
        "scope_id": MOMENT_ID,
        "bound_resource_id": MOMENT_ID,
        "variant": "thumbnail",
        "version": 1,
        "expires_at": expires,
    }
    asset_requests: list[httpx.Request] = []

    async def valid_asset_roundtrip() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            asset_requests.append(request)
            return httpx.Response(200, json=transfer_json)

        async with HttpChatAssetStore(
            HttpChatAssetStoreConfig(
                base_url="http://c19-asset-api:8091",
                token="a" * 32,
            ),
            transport=httpx.MockTransport(handler),
        ) as adapter:
            inspected = await adapter.inspect_scoped_transfer(
                opaque_ticket=DOWNLOAD_TICKET,
                direction="download",
                method="GET",
            )
            assert inspected.usage == "moment_image"
            assert inspected.scope_id == MOMENT_ID

    asyncio.run(valid_asset_roundtrip())
    assert asset_requests[0].url.path == "/v2/transfers/inspect"
    assert json.loads(asset_requests[0].content) == {
        "ticket": DOWNLOAD_TICKET,
        "direction": "download",
        "method": "GET",
    }

    async def extra_asset_field_is_rejected() -> None:
        async with HttpChatAssetStore(
            HttpChatAssetStoreConfig(
                base_url="http://c19-asset-api:8091",
                token="a" * 32,
            ),
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json={**transfer_json, "object_key": "forbidden"},
                )
            ),
        ) as adapter:
            with pytest.raises(ChatAssetStoreProtocolError):
                await adapter.inspect_scoped_transfer(
                    opaque_ticket=DOWNLOAD_TICKET,
                    direction="download",
                    method="GET",
                )

    asyncio.run(extra_asset_field_is_rejected())


def test_moment_routes_are_registered_without_widening_chat_routes() -> None:
    expected = {
        ("POST", "/c19/moments/drafts"),
        ("GET", "/c19/moments/feed"),
        ("GET", "/c19/moments/events/tail"),
        ("GET", "/c19/moments/events"),
        ("POST", "/c19/moments/{moment_id}/assets/upload-intents"),
        ("GET", "/c19/moments/{moment_id}/assets/{asset_id}"),
        ("POST", "/c19/moments/{moment_id}/assets/{asset_id}/finalize"),
        ("POST", "/c19/moments/{moment_id}/assets/{asset_id}/access-intents"),
        ("POST", "/c19/moments/{moment_id}/publish"),
        ("PUT", "/c19/moments/{moment_id}/like"),
        ("DELETE", "/c19/moments/{moment_id}/like"),
        ("GET", "/c19/moments/{moment_id}/likes"),
        ("POST", "/c19/moments/{moment_id}/comments"),
        ("GET", "/c19/moments/{moment_id}/comments"),
        ("DELETE", "/c19/moments/{moment_id}/comments/{comment_id}"),
        ("GET", "/c19/moments/{moment_id}"),
        ("DELETE", "/c19/moments/{moment_id}"),
    }
    actual = {
        (method, route.path)
        for route in moment_router.routes
        for method in route.methods
    }
    aggregate = {
        (method, route.path)
        for route in aggregate_router.routes
        for method in route.methods
    }
    assert actual == expected
    assert expected <= aggregate
