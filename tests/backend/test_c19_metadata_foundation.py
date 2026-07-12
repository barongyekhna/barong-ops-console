from __future__ import annotations

from datetime import UTC, datetime
import importlib.util
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    func,
    inspect,
    select,
)

from backend.app import models  # noqa: F401
from backend.app.db.base import Base


pytestmark = pytest.mark.unit

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPOSITORY_ROOT
    / "backend"
    / "alembic"
    / "versions"
    / "20260711_01_c19_control_metadata_core.py"
)
NATIVE_ACCESS_MIGRATION_PATH = (
    REPOSITORY_ROOT
    / "backend"
    / "alembic"
    / "versions"
    / "20260712_01_c19_native_user_access.py"
)
C19_CONTROL_TABLES = {
    "c19_profiles",
    "c19_affiliations",
    "c19_friend_requests",
    "c19_relationships",
    "c19_user_blocks",
    "c19_conversations",
    "c19_conversation_members",
    "c19_conversation_user_settings",
}
C19_EXTERNAL_CONTENT_TABLES = {
    "c19_messages",
    "c19_message_receipts",
    "c19_attachments",
    "c19_moments",
    "c19_outbox",
}


def _unique_column_sets(table_name: str) -> set[tuple[str, ...]]:
    table = Base.metadata.tables[table_name]
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_c19_stage_one_registers_only_control_metadata() -> None:
    table_names = set(Base.metadata.tables)

    assert C19_CONTROL_TABLES <= table_names
    assert C19_EXTERNAL_CONTENT_TABLES.isdisjoint(table_names)


def test_c19_profile_and_affiliation_support_multi_org_users() -> None:
    profile = Base.metadata.tables["c19_profiles"]
    affiliation = Base.metadata.tables["c19_affiliations"]

    assert set(profile.primary_key.columns.keys()) == {"user_id"}
    assert "org_id" not in profile.columns
    assert "title" not in profile.columns
    assert {"user_id", "org_id", "source_membership_id"} <= set(
        affiliation.columns.keys()
    )
    assert ("user_id", "org_id") in _unique_column_sets("c19_affiliations")
    assert ("source_membership_id",) in _unique_column_sets("c19_affiliations")


def test_c19_relationship_conversation_and_block_boundaries_are_durable() -> None:
    assert ("pair_key",) in _unique_column_sets("c19_friend_requests")
    assert ("user_low_id", "user_high_id") in _unique_column_sets(
        "c19_relationships"
    )
    assert ("blocker_user_id", "blocked_user_id") in _unique_column_sets(
        "c19_user_blocks"
    )
    assert ("direct_pair_key",) in _unique_column_sets("c19_conversations")
    assert ("conversation_id", "user_id") in _unique_column_sets(
        "c19_conversation_members"
    )


def test_c19_member_and_settings_tables_contain_no_remote_record_position() -> None:
    member_columns = set(
        Base.metadata.tables["c19_conversation_members"].columns.keys()
    )
    setting_columns = set(
        Base.metadata.tables["c19_conversation_user_settings"].columns.keys()
    )

    forbidden = {
        "message_id",
        "message_body",
        "last_message",
        "last_read_cursor",
        "last_read_sequence",
        "attachment_id",
        "storage_url",
    }
    assert forbidden.isdisjoint(member_columns)
    assert forbidden.isdisjoint(setting_columns)
    assert {"is_pinned", "is_muted", "is_archived", "notification_level"} <= (
        setting_columns
    )

    member_table = Base.metadata.tables["c19_conversation_members"]
    affiliation_foreign_keys = [
        constraint
        for constraint in member_table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and {element.target_fullname for element in constraint.elements}
        == {
            "c19_affiliations.affiliation_id",
            "c19_affiliations.user_id",
            "c19_affiliations.org_id",
        }
    ]
    assert len(affiliation_foreign_keys) == 1
    assert affiliation_foreign_keys[0].ondelete == "RESTRICT"
    assert member_table.columns["affiliation_id"].nullable is True
    assert member_table.columns["org_id_at_join"].nullable is True
    profile_foreign_keys = [
        constraint
        for constraint in member_table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and {element.target_fullname for element in constraint.elements}
        == {"c19_profiles.user_id"}
    ]
    assert len(profile_foreign_keys) == 1
    assert profile_foreign_keys[0].ondelete == "RESTRICT"
    assert any(
        isinstance(constraint, CheckConstraint)
        and "affiliation_snapshot_consistent" in str(constraint.name)
        for constraint in member_table.constraints
    )


def test_c19_control_metadata_migration_is_in_the_single_alembic_chain() -> None:
    config = Config(str(REPOSITORY_ROOT / "backend" / "alembic.ini"))
    script = ScriptDirectory.from_config(config)

    heads = script.get_heads()
    assert len(heads) == 1
    assert "20260711_01_c19_control_core" in {
        item.revision for item in script.iterate_revisions(heads[0], "base")
    }
    assert heads == ["20260712_01_c19_native_access"]
    revision = script.get_revision("20260711_01_c19_control_core")
    assert revision is not None
    assert revision.down_revision == "20260710_05_k_brand_guard"


def test_c19_migration_upgrades_backfills_multi_org_and_downgrades() -> None:
    spec = importlib.util.spec_from_file_location("c19_control_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    native_spec = importlib.util.spec_from_file_location(
        "c19_native_access_migration",
        NATIVE_ACCESS_MIGRATION_PATH,
    )
    assert native_spec is not None and native_spec.loader is not None
    native_migration = importlib.util.module_from_spec(native_spec)
    native_spec.loader.exec_module(native_migration)

    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata = MetaData()
    users = Table(
        "users",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("username", String(255), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
    )
    organizations = Table(
        "organizations",
        metadata,
        Column("org_id", String(40), primary_key=True),
    )
    memberships = Table(
        "org_memberships",
        metadata,
        Column("membership_id", String(64), primary_key=True),
        Column("user_id", String(255), nullable=False),
        Column("org_id", String(40), nullable=False),
        Column("role", String(20), nullable=False),
        Column("status", String(20), nullable=False),
        Column("joined_at", DateTime(timezone=True), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
    )
    now = datetime.now(UTC)

    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(
            users.insert(),
            [
                {
                    "id": 1,
                    "username": "multi-org-user",
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": 2,
                    "username": "second-user",
                    "created_at": now,
                    "updated_at": now,
                },
            ],
        )
        connection.execute(
            organizations.insert(),
            [{"org_id": "org_" + "1" * 32}, {"org_id": "org_" + "2" * 32}],
        )
        connection.execute(
            memberships.insert(),
            [
                {
                    "membership_id": "mem_1",
                    "user_id": "1",
                    "org_id": "org_" + "1" * 32,
                    "role": "admin",
                    "status": "active",
                    "joined_at": now,
                    "created_at": now,
                },
                {
                    "membership_id": "mem_2",
                    "user_id": "1",
                    "org_id": "org_" + "2" * 32,
                    "role": "member",
                    "status": "active",
                    "joined_at": now,
                    "created_at": now,
                },
                {
                    "membership_id": "mem_orphan",
                    "user_id": "999",
                    "org_id": "org_" + "1" * 32,
                    "role": "member",
                    "status": "active",
                    "joined_at": now,
                    "created_at": now,
                },
            ],
        )

        context = MigrationContext.configure(connection)
        migration.op = Operations(context)
        migration.upgrade()

        tables_after_upgrade = set(inspect(connection).get_table_names())
        assert C19_CONTROL_TABLES <= tables_after_upgrade
        assert C19_EXTERNAL_CONTENT_TABLES.isdisjoint(tables_after_upgrade)

        migrated_metadata = MetaData()
        profiles = Table("c19_profiles", migrated_metadata, autoload_with=connection)
        affiliations = Table(
            "c19_affiliations",
            migrated_metadata,
            autoload_with=connection,
        )
        assert connection.scalar(select(func.count()).select_from(profiles)) == 2
        user_one_affiliations = connection.scalars(
            select(affiliations.c.org_id).where(affiliations.c.user_id == 1)
        ).all()
        assert set(user_one_affiliations) == {
            "org_" + "1" * 32,
            "org_" + "2" * 32,
        }
        assert (
            connection.scalar(select(func.count()).select_from(affiliations)) == 2
        )

        # Simulate legacy drift, then prove the native-user migration repairs
        # the global profile invariant and makes only the org snapshot optional.
        connection.execute(profiles.delete().where(profiles.c.user_id == 2))
        connection.execute(
            users.update().where(users.c.id == 2).values(username="   ")
        )
        native_migration.op = Operations(context)
        native_migration.upgrade()
        assert connection.scalar(select(func.count()).select_from(profiles)) == 2
        assert connection.scalar(
            select(profiles.c.display_name).where(profiles.c.user_id == 2)
        ) == "User 2"
        member_columns = {
            column["name"]: column
            for column in inspect(connection).get_columns(
                "c19_conversation_members"
            )
        }
        assert member_columns["affiliation_id"]["nullable"] is True
        assert member_columns["org_id_at_join"]["nullable"] is True

        native_migration.downgrade()
        downgraded_member_columns = {
            column["name"]: column
            for column in inspect(connection).get_columns(
                "c19_conversation_members"
            )
        }
        assert downgraded_member_columns["affiliation_id"]["nullable"] is False
        assert downgraded_member_columns["org_id_at_join"]["nullable"] is False

        migration.downgrade()
        tables_after_downgrade = set(inspect(connection).get_table_names())
        assert C19_CONTROL_TABLES.isdisjoint(tables_after_downgrade)
        assert {"users", "organizations", "org_memberships"} <= (
            tables_after_downgrade
        )
