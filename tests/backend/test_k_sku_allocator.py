from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from backend.app.modules.k_series.product_knowledge.models import (
    KProductKnowledgeMediaAsset,
    KProductKnowledgeProduct,
    KProductKnowledgeVariant,
    KSkuSequence,
)
from backend.app.modules.k_series.product_knowledge.r_to_k_transfer import (
    transfer_from_rw,
)
from backend.app.modules.k_series.product_knowledge.scope_shim import KScopeContext
import backend.app.modules.k_series.product_knowledge.sku_allocator as allocator
from backend.app.modules.k_series.product_knowledge.sku_allocator import (
    allocate_sku,
    derive_category_prefix,
    ensure_product_sku,
    resolve_product_leaf,
)
from backend.app.services.data_isolation import (
    OrgDataIsolationSession,
    OrgDataIsolationUserContext,
    org_data_isolation_context,
)
import backend.app.modules.p_series.upload.assemble as p_assemble


pytestmark = pytest.mark.unit


def _sqlite_session(tmp_path: Path | None = None):
    url = "sqlite:///:memory:" if tmp_path is None else f"sqlite:///{tmp_path / 'sku.db'}"
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    return engine, sessionmaker(bind=engine)


def test_leaf_prefix_contract_and_explicit_collision_override() -> None:
    assert derive_category_prefix("In-Ground Lights") == "IGL"
    assert derive_category_prefix("Cold Therapy Machine") == "CTM"
    assert derive_category_prefix("Outdoor String Lights") == "OSL"
    assert derive_category_prefix("Outdoor Solar Lights") == "OSOL"


def test_allocator_is_idempotent_for_product_and_replaces_legacy_asin() -> None:
    engine, Session = _sqlite_session()
    KSkuSequence.__table__.create(engine)
    KProductKnowledgeProduct.__table__.create(engine)
    KProductKnowledgeVariant.__table__.create(engine)
    KProductKnowledgeMediaAsset.__table__.create(engine)

    with Session() as db:
        product = KProductKnowledgeProduct(
            id=uuid4(),
            product_key=str(uuid4()),
            source_system="r_w",
            source_record_id="B0BYTEST01",
            asin_reference="B0BYTEST01",
            sku="B0BYTEST01",
            parent_sku="B0BYTEST01",
            category_path="Home > Lighting > In-Ground Lights",
            product_status="draft",
            product_type="simple_product",
            review_status="draft",
            canonical_language="en",
        )
        db.add(product)
        db.flush()
        variant = KProductKnowledgeVariant(
            id=uuid4(),
            product_id=product.id,
            parent_sku="B0BYTEST01",
            variant_sku="B0BYTEST01-A1B2C3D4",
            variant_hash="A1B2C3D4",
            image_folder=f"images/{product.product_key}/B0BYTEST01-A1B2C3D4",
        )
        db.add(variant)
        db.flush()
        media = KProductKnowledgeMediaAsset(
            id=uuid4(),
            product_id=product.id,
            variant_id=variant.id,
            variant_sku="B0BYTEST01-A1B2C3D4",
            asset_type="image",
            asset_role="gallery",
            metadata_json={
                "sku": "B0BYTEST01",
                "variant_sku": "B0BYTEST01-A1B2C3D4",
            },
        )
        db.add(media)
        db.flush()

        first = ensure_product_sku(db, product)
        second = ensure_product_sku(db, product, force_allocate=True)

        assert first == "IGL-001"
        assert second == first
        assert product.sku == "IGL-001"
        assert product.parent_sku == "IGL-001"
        assert variant.parent_sku == "IGL-001"
        assert variant.variant_sku == "IGL-001-A1B2C3D4"
        assert variant.image_folder.endswith("/IGL-001-A1B2C3D4")
        assert media.variant_sku == "IGL-001-A1B2C3D4"
        assert media.metadata_json == {
            "sku": "IGL-001",
            "variant_sku": "IGL-001-A1B2C3D4",
        }
        sequence = db.get(KSkuSequence, "path:home lighting in ground lights")
        assert sequence is not None
        assert sequence.next_seq == 2


def test_prefix_reservation_maps_same_initials_to_distinct_namespaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, Session = _sqlite_session()
    KSkuSequence.__table__.create(engine)
    monkeypatch.setattr(allocator, "_legacy_prefix_max", lambda db, prefix: 0)

    with Session() as db:
        first = allocate_sku(
            db,
            leaf_key="google:101",
            leaf_name="Smart Garden Lights",
        )
        second = allocate_sku(
            db,
            leaf_key="google:202",
            leaf_name="Solar Garden Lanterns",
        )
        third = allocate_sku(
            db,
            leaf_key="google:202",
            leaf_name="Solar Garden Lanterns",
        )
        db.commit()

    assert first == "SGL-001"
    second_prefix, second_number = second.rsplit("-", 1)
    third_prefix, third_number = third.rsplit("-", 1)
    assert second_prefix != "SGL"
    assert second_prefix == third_prefix
    assert second_number == "001"
    assert third_number == "002"


def test_non_leaf_taxonomy_node_uses_real_path_leaf_or_uncategorized() -> None:
    engine, Session = _sqlite_session()
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE k_category_google ("
                "id TEXT PRIMARY KEY, name TEXT, full_path TEXT, is_leaf BOOLEAN)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO k_category_google VALUES "
                "('ROOT', 'Lighting', 'Home > Lighting', 0)"
            )
        )

    product = SimpleNamespace(
        id=uuid4(),
        channel="dtc",
        google_product_category="ROOT",
        amazon_category_id=None,
        category_path="Home > Lighting > In-Ground Lights",
        merchant_product_type=None,
        category_hint=None,
    )
    with Session() as db:
        leaf = resolve_product_leaf(db, product)
        assert leaf.name == "In-Ground Lights"
        assert leaf.key == "path:home lighting in ground lights"

        product.category_path = "Home > Lighting"
        leaf = resolve_product_leaf(db, product)
        assert leaf.name == "Uncategorized"
        assert leaf.key == "fallback:uncategorized"


def test_managed_product_sku_repairs_half_migrated_variant_family() -> None:
    engine, Session = _sqlite_session()
    KProductKnowledgeProduct.__table__.create(engine)
    KProductKnowledgeVariant.__table__.create(engine)
    KProductKnowledgeMediaAsset.__table__.create(engine)

    with Session() as db:
        product = KProductKnowledgeProduct(
            id=uuid4(),
            product_key=str(uuid4()),
            sku="IGL-042",
            parent_sku="B0BYTEST01",
            product_status="draft",
            product_type="simple_product",
            review_status="draft",
            canonical_language="en",
        )
        db.add(product)
        db.flush()
        variant = KProductKnowledgeVariant(
            id=uuid4(),
            product_id=product.id,
            parent_sku="B0BYTEST01",
            variant_sku="B0BYTEST01-DEADBEEF",
            variant_hash="DEADBEEF",
            image_folder=f"images/{product.product_key}/B0BYTEST01-DEADBEEF",
        )
        db.add(variant)
        db.flush()
        media = KProductKnowledgeMediaAsset(
            id=uuid4(),
            product_id=product.id,
            variant_id=variant.id,
            variant_sku="B0BYTEST01-DEADBEEF",
            asset_type="image",
            asset_role="gallery",
            metadata_json={"sku": "B0BYTEST01", "variant_sku": variant.variant_sku},
        )
        db.add(media)
        db.flush()

        assert ensure_product_sku(db, product) == "IGL-042"
        assert product.parent_sku == "IGL-042"
        assert variant.parent_sku == "IGL-042"
        assert variant.variant_sku == "IGL-042-DEADBEEF"
        assert media.variant_sku == "IGL-042-DEADBEEF"
        assert media.metadata_json["sku"] == "IGL-042"


def test_global_sequence_allocation_is_allowed_under_strict_org_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, _ = _sqlite_session()
    KSkuSequence.__table__.create(engine)
    Session = sessionmaker(bind=engine, class_=OrgDataIsolationSession)
    monkeypatch.setattr(allocator, "_legacy_prefix_max", lambda db, prefix: 0)
    context = OrgDataIsolationUserContext(
        org_id="org_11111111111111111111111111111111",
        user_id="user-test",
        role="member",
        source="sku-test",
        strict=True,
    )

    with Session() as db, org_data_isolation_context(context):
        assert (
            allocate_sku(
                db,
                leaf_key="google:303",
                leaf_name="Cold Therapy Machine",
            )
            == "CTM-001"
        )


def test_atomic_upsert_issues_unique_numbers_under_concurrency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, Session = _sqlite_session(tmp_path)
    KSkuSequence.__table__.create(engine)
    monkeypatch.setattr(allocator, "_legacy_prefix_max", lambda db, prefix: 0)
    workers = 12
    barrier = Barrier(workers)

    def issue_one() -> str:
        with Session() as db:
            barrier.wait(timeout=10)
            sku = allocate_sku(
                db,
                leaf_key="google:555",
                leaf_name="In-Ground Lights",
            )
            db.commit()
            return sku

    with ThreadPoolExecutor(max_workers=workers) as pool:
        issued = list(pool.map(lambda _: issue_one(), range(workers)))

    assert len(set(issued)) == workers
    assert sorted(int(sku.rsplit("-", 1)[1]) for sku in issued) == list(
        range(1, workers + 1)
    )
    assert {sku.rsplit("-", 1)[0] for sku in issued} == {"IGL"}


def test_r_to_k_transfer_keeps_asin_as_reference_never_as_sku() -> None:
    engine, Session = _sqlite_session()
    KSkuSequence.__table__.create(engine)
    KProductKnowledgeProduct.__table__.create(engine)
    KProductKnowledgeVariant.__table__.create(engine)
    KProductKnowledgeMediaAsset.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE products_rw ("
                "asin TEXT PRIMARY KEY, marketplace TEXT, title TEXT, brand TEXT, "
                "category_id TEXT, category_path TEXT, price NUMERIC, "
                "image_url TEXT, source_query TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE k_category_amazon ("
                "id TEXT PRIMARY KEY, name TEXT, full_path TEXT, "
                "parent_id TEXT, level INTEGER, is_leaf BOOLEAN, marketplace TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE k_category_google ("
                "id TEXT PRIMARY KEY, name TEXT, full_path TEXT, "
                "parent_id TEXT, level INTEGER, is_leaf BOOLEAN)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE k_category_alignment ("
                "amazon_id TEXT, marketplace TEXT, google_id TEXT, "
                "confidence NUMERIC)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO products_rw VALUES ("
                "'B0BYTEST01', 'US', 'Solar path light', 'Third Party', "
                "'A-10', 'Home > Lighting > In-Ground Lights', 19.99, "
                "'https://example.test/light.jpg', 'solar path light')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO k_category_amazon VALUES ("
                "'A-10', 'In-Ground Lights', 'Home > Lighting > In-Ground Lights', "
                "NULL, 3, 1, 'US')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO k_category_google VALUES ("
                "'G-20', 'In-Ground Lights', 'Home > Lighting > In-Ground Lights', "
                "NULL, 3, 1)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO k_category_alignment VALUES "
                "('A-10', 'US', 'G-20', 1.0)"
            )
        )

    scope = KScopeContext(
        workspace_key="org_test",
        business_context="independent_store",
        scope_mode="production",
    )
    with Session() as db:
        result = transfer_from_rw(
            db,
            asins=["B0BYTEST01"],
            channel="dtc",
            user=None,
            scope_context=scope,
        )
        product = db.scalar(select(KProductKnowledgeProduct))
        variant = db.scalar(select(KProductKnowledgeVariant))

        assert result["errors"] == []
        assert result["created"][0]["sku"] == "IGL-001"
        assert product is not None
        assert product.sku == "IGL-001"
        assert product.parent_sku == "IGL-001"
        assert product.asin_reference == "B0BYTEST01"
        assert product.source_record_id == "B0BYTEST01"
        assert variant is not None
        assert variant.product_id == product.id
        assert variant.parent_sku == product.sku
        assert variant.variant_sku.startswith(f"{product.sku}-")
        assert variant.attributes_json == {"default_variant": True}
        assert variant.image_folder.endswith(f"/{variant.variant_sku}")


def test_p_package_allocates_after_category_fail_safe_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, Session = _sqlite_session()
    KSkuSequence.__table__.create(engine)
    KProductKnowledgeProduct.__table__.create(engine)
    KProductKnowledgeVariant.__table__.create(engine)
    KProductKnowledgeMediaAsset.__table__.create(engine)

    with Session() as db:
        product = KProductKnowledgeProduct(
            id=uuid4(),
            product_key=str(uuid4()),
            source_system="r_w",
            source_record_id="B0BYTEST01",
            asin_reference="B0BYTEST01",
            sku="B0BYTEST01",
            parent_sku="B0BYTEST01",
            product_name_en="Solar path light",
            category_path="Home > Lighting > In-Ground Lights",
            product_status="draft",
            product_type="simple_product",
            review_status="approved",
            canonical_language="en",
            regular_price=Decimal("19.99"),
            price_currency="USD",
            marketing_copy_json={},
        )
        db.add(product)
        db.flush()
        db.add(
            KProductKnowledgeVariant(
                id=uuid4(),
                product_id=product.id,
                parent_sku="B0BYTEST01",
                variant_sku="B0BYTEST01-A1B2C3D4",
                variant_hash="A1B2C3D4",
                image_folder=(
                    f"images/{product.product_key}/B0BYTEST01-A1B2C3D4"
                ),
            )
        )
        db.commit()

        monkeypatch.setattr(p_assemble, "_image_assets", lambda *args, **kwargs: [])

        def current_variants(session, _product):
            row = session.scalar(
                select(KProductKnowledgeVariant).where(
                    KProductKnowledgeVariant.product_id == product.id
                )
            )
            assert row is not None
            return [p_assemble.Variant(sku=row.variant_sku)]

        monkeypatch.setattr(p_assemble, "_variants", current_variants)

        def category_failure(session, _product):
            session.rollback()
            return None, None

        monkeypatch.setattr(p_assemble, "_resolve_wc_category", category_failure)
        package = p_assemble.assemble_upload_package(
            db,
            product,
            base_url="https://ops.example.test",
        )

        assert package.product.sku == "IGL-001"
        assert package.woo_lookup_sku == "B0BYTEST01"
        assert package.woo_existing_product_id is None
        assert [item.sku for item in package.product.variants] == [
            "IGL-001-A1B2C3D4"
        ]
        assert product.sku == "IGL-001"
        assert db.get(KSkuSequence, "path:home lighting in ground lights").next_seq == 2


def test_sku_sequence_migration_chains_from_previous_single_head() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    scripts = ScriptDirectory.from_config(
        Config(str(repo_root / "backend" / "alembic.ini"))
    )

    revision = scripts.get_revision("20260716_02_k_sku_sequence")
    assert revision is not None
    assert revision.down_revision == "20260716_01_p_wc_category_map"
