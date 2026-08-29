"""K 外部精修通道(MCP)—— 真库端到端:机器人身份 → 取简报 → 交稿 → 查状态。

跑法(铁律):scripts/run_backend_tests.sh integration
"""

from __future__ import annotations

import io
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.organization import OrganizationRecord
from backend.app.models.user import User
from backend.app.services import mcp_token_service
from backend.app.modules.k_series.product_knowledge import (
    image_render_jobs as irj,
    mcp_channel,
)
from backend.app.modules.k_series.product_knowledge.constants import (
    DEFAULT_BUSINESS_CONTEXT,
)
from backend.app.modules.k_series.product_knowledge.models import (
    KProductKnowledgeProduct,
    KProductKnowledgeVariant,
)

pytestmark = [pytest.mark.integration, pytest.mark.k_mcp]


def _png(size: tuple[int, int], color: str) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _brief() -> dict:
    return {
        "image_count": 2,
        "channel": "dtc",
        "aspect_ratio": "1:1",
        "style_block": "STYLE BLOCK: Bright & Airy commercial product photography.",
        "consistency": "Use the supplied real product photo as the immutable reference.",
        "compliance_checklist": ["Position 1 is the only pure-white-background image."],
        "operating_model": {
            "how_it_works": "A submersible pump: the whole unit sits under water.",
            "hard_constraints": ["the pump body must be fully submerged"],
            "forbidden_depictions": ["pump on dry ground while spraying"],
        },
        "images": [
            {
                "position": 1,
                "role": "main",
                "placement": "gallery",
                "prompt": "Hero product shot on pure white.",
                "title": "Main",
                "alt": "camping shower main unit",
            },
            {
                "position": 2,
                "role": "proof_scene",
                "placement": "description",
                "prompt": "Pump submerged in a bucket at a campsite, hose to the shower head.",
                "title": "In use",
                "alt": "camping shower in use",
            },
        ],
    }


OWNER_PASSWORD = "Mcp-Test-Only-Password-2026"


def _seed(tmp_media: Path) -> tuple[str, str]:
    """机器人账号 + 组织 + 一件带简报和参考图的产品。返回 (bot_username, sku)。
    owner 用户名 = "mcp_owner_" + 与 bot 相同的后缀(协议测试要拿它登录)。"""
    suffix = uuid4().hex[:8]
    bot_username = f"codex_painter_{suffix}"
    org_id = f"org_{uuid4().hex}"
    sku = f"MCPT-{uuid4().hex[:6].upper()}"
    with SessionLocal() as db:
        owner = User(
            username=f"mcp_owner_{suffix}",
            password_hash=hash_password(OWNER_PASSWORD),
            role="owner",
            is_active=True,
            organization_id=org_id,
        )
        db.add(owner)
        db.flush()
        db.add(
            OrganizationRecord(
                org_id=org_id,
                org_name=f"MCP 测试组织 {org_id[-6:]}",
                org_type="store",
                owner_user_id=str(owner.id),
                status="active",
                metadata_json={},
            )
        )
        db.flush()
        db.add(
            OrgMembershipRecord(
                membership_id=f"mem_{uuid4().hex}",
                user_id=str(owner.id),
                org_id=org_id,
                role="owner",
                status="active",
            )
        )
        bot = User(
            username=bot_username,
            password_hash=hash_password("Mcp-Bot-Password-2026"),
            role="viewer",
            is_active=True,
            is_bot=True,
            organization_id=org_id,
        )
        db.add(bot)
        db.flush()
        db.add(
            OrgMembershipRecord(
                membership_id=f"mem_{uuid4().hex}",
                user_id=str(bot.id),
                org_id=org_id,
                role="member",
                status="active",
            )
        )
        product = KProductKnowledgeProduct(
            id=uuid4(),
            workspace_key=org_id,
            business_context=DEFAULT_BUSINESS_CONTEXT,
            scope_mode="production",
            product_key=str(uuid4()),
            source_system="manual",
            source_record_id=sku,
            sku=sku,
            parent_sku=sku,
            product_name_en="Portable camping shower",
            category_path="Sporting Goods > Outdoor Recreation > Camping",
            product_status="draft",
            product_type="simple_product",
            review_status="draft",
            canonical_language="en",
            channel="dtc",
            package_includes_json=["main unit", "shower head", "hose"],
            image_instruction_json=_brief(),
            marketing_copy_json={"title": "Portable camping shower"},
        )
        db.add(product)
        db.flush()
        db.add(
            KProductKnowledgeVariant(
                id=uuid4(),
                product_id=product.id,
                parent_sku=sku,
                variant_sku=f"{sku}-A1B2C3D4",
                variant_hash="A1B2C3D4",
                image_folder=f"images/{product.product_key}/{sku}-A1B2C3D4",
            )
        )
        db.flush()
        irj.store_reference_image_asset(
            db,
            product=product,
            contents=_png((300, 300), "blue"),
            mime_type="image/png",
            source_url="file:///tmp/ref_blue.png",
            user=owner,
            extra_metadata={"variant_reference": False, "variant_color": "blue"},
        )
        db.commit()
    return bot_username, sku


def test_external_channel_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    media_root = tmp_path / "k-media"
    monkeypatch.setenv("K_PRODUCT_MEDIA_STORAGE_DIR", str(media_root))
    bot_username, sku = _seed(media_root)

    with SessionLocal() as db:
        # 认人之后:作用域从这个人的组织推出来(这里借 bot 账号走通道层,权限门在协议层测)
        bot = db.scalars(select(User).where(User.username == bot_username)).first()
        actor = mcp_channel.actor_for_user(db, bot)
        assert actor.user.is_bot is True
        assert actor.scope.scope_mode == "production"
        assert len(actor.scopes) == 1
        # 机器人不发钥匙
        with pytest.raises(mcp_token_service.McpTokenNotForBotsError):
            mcp_token_service.mint_token(db, user=bot, actor=bot, audit=None)

        listing = mcp_channel.list_products_awaiting_images(db, scope=actor.scopes, limit=50)
        mine = [item for item in listing if item["sku"] == sku]
        assert len(mine) == 1
        assert mine[0]["positions_missing"] == [1, 2]
        assert mine[0]["reference_images"] == 1

        product = mcp_channel.get_product_by_sku(db, sku, actor.scopes)
        brief = mcp_channel.build_external_brief(db, product=product)
        assert "fully submerged" in brief
        assert "main unit" in brief and "shower head" in brief
        assert "### Position 1" in brief and "### Position 2" in brief
        assert brief.count(irj.PRODUCT_FIDELITY_BLOCK.strip()) == 2
        assert "aspect ratio: **1:1**" in brief and "aspect ratio: **4:3**" in brief
        refs = mcp_channel.reference_summaries(db, product)
        assert refs and refs[0]["variant_color"] == "blue"

        # 别的组织看不到这件产品
        other_scope = mcp_channel.KScopeContext(
            workspace_key="org_someone_else",
            business_context=actor.scope.business_context,
            scope_mode=actor.scope.scope_mode,
        )
        with pytest.raises(mcp_channel.KMcpChannelError) as excinfo:
            mcp_channel.get_product_by_sku(db, sku, other_scope)
        assert excinfo.value.code == "PRODUCT_NOT_FOUND"

        # 交稿:PNG 进,WebP 出;staged;带外部标记;审查已排队
        result = mcp_channel.submit_rendered_image(
            db,
            product=product,
            position=2,
            image_bytes=_png((1600, 1200), "green"),
            user=actor.user,
            scope=actor.scope,
            note="rendered with blue reference",
        )
        db.commit()

    assert result["status"] == "staged"
    assert result["asset_role"] == "description"
    assert result["stored_mime_type"] == "image/webp"
    assert result["audit_enqueued"] is True

    with SessionLocal() as db:
        row = db.execute(
            text(
                "SELECT status, mime_type, object_key, metadata_json, created_by_user_id "
                "FROM k_product_knowledge_media_assets WHERE id = :id"
            ),
            {"id": result["asset_id"]},
        ).mappings().first()
        assert row is not None
        assert row["status"] == "staged"
        assert row["mime_type"] == "image/webp"
        meta = row["metadata_json"]
        assert meta["render_pipeline"] == "k_auto_render"
        assert meta["submitted_via"] == "mcp"
        assert meta["submitter"] == "codex"
        assert meta["submitted_by_username"] == bot_username
        assert meta["submission_note"] == "rendered with blue reference"
        assert meta["position"] == 2 and meta["placement"] == "description"
        assert row["created_by_user_id"] is not None
        # 外部副作用回读:文件真的落盘、真的是 webp
        stored = media_root / row["object_key"]
        assert stored.is_file()
        assert stored.read_bytes()[:4] == b"RIFF"

        jobs = db.execute(
            text(
                "SELECT job_type, status, requested_by_username FROM k_generation_jobs "
                "WHERE product_id = (SELECT id FROM k_product_knowledge_products WHERE sku = :sku)"
            ),
            {"sku": sku},
        ).mappings().all()
        assert [(j["job_type"], j["status"]) for j in jobs] == [("brand_audit", "pending")]
        assert jobs[0]["requested_by_username"] == bot_username

        # 状态视图看得到它,而且知道它是外部稿
        bot = db.scalars(select(User).where(User.username == bot_username)).first()
        actor = mcp_channel.actor_for_user(db, bot)
        product = mcp_channel.get_product_by_sku(db, sku, actor.scopes)
        status = mcp_channel.submission_status(db, product=product)
        staged = [a for a in status["assets"] if a["status"] == "staged"]
        assert len(staged) == 1 and staged[0]["submitted_via"] == "mcp"
        assert status["audit"]["pending"] is True
        by_pos = {p["position"]: p for p in status["positions"]}
        assert by_pos[2]["has_staged"] is True and by_pos[2]["has_available"] is False

        # 24h 惰性回收:把 staged_at 拨到两天前,外部稿必须还在
        db.execute(
            text(
                "UPDATE k_product_knowledge_media_assets SET metadata_json = "
                "jsonb_set(metadata_json::jsonb, '{staged_at}', "
                "to_jsonb((now() - interval '2 days')::text)) WHERE id = :id"
            ),
            {"id": result["asset_id"]},
        )
        removed = irj.cleanup_stale_staged(db, product.id)
        assert removed == 0
        still = db.execute(
            text("SELECT status FROM k_product_knowledge_media_assets WHERE id = :id"),
            {"id": result["asset_id"]},
        ).scalar()
        assert still == "staged"

        # 错位号 / 非图片 都拒
        with pytest.raises(mcp_channel.KMcpChannelError) as excinfo:
            mcp_channel.submit_rendered_image(
                db,
                product=product,
                position=99,
                image_bytes=_png((10, 10), "red"),
                user=actor.user,
                scope=actor.scope,
            )
        assert excinfo.value.code == "UNKNOWN_POSITION"
        with pytest.raises(mcp_channel.KMcpChannelError) as excinfo:
            mcp_channel.submit_rendered_image(
                db,
                product=product,
                position=1,
                image_bytes=b"garbage",
                user=actor.user,
                scope=actor.scope,
            )
        assert excinfo.value.code == "IMAGE_UNREADABLE"

        # 参考图字节面:本作用域能取,别的作用域 404
        asset, _ = mcp_channel.asset_file_for_download(
            db, asset_id=refs[0]["asset_id"], scope=actor.scopes
        )
        assert asset.asset_role == "reference"
        with pytest.raises(mcp_channel.KMcpChannelError):
            mcp_channel.asset_file_for_download(
                db, asset_id=refs[0]["asset_id"], scope=other_scope
            )


def test_token_resolution_and_permission_gate() -> None:
    from backend.app.services.auth_service import AuditContext

    audit = AuditContext(request_id="t", ip_address=None, user_agent=None)
    with SessionLocal() as db:
        org_id = f"org_{uuid4().hex}"
        db.add(OrganizationRecord(org_id=org_id, org_name="钥匙测试组织", org_type="store",
                                  owner_user_id="0", status="active", metadata_json={}))
        owner = User(username=f"tk_owner_{uuid4().hex[:8]}", password_hash=hash_password("Mcp-Bot-Password-2026"),
                     role="owner", is_active=True)
        viewer = User(username=f"tk_viewer_{uuid4().hex[:8]}", password_hash=hash_password("Mcp-Bot-Password-2026"),
                      role="viewer", is_active=True, organization_id=org_id)
        db.add_all([owner, viewer]); db.flush()
        db.add(OrgMembershipRecord(membership_id=f"mem_{uuid4().hex}", user_id=str(viewer.id), org_id=org_id, role="member", status="active"))
        db.flush()

        issued = mcp_token_service.mint_token(db, user=viewer, actor=owner, audit=audit)
        db.commit()
        token = issued.token
        assert token.startswith("bk_")
        row = mcp_token_service.get_token_row(db, viewer.id)
        assert row.token_hash != token and row.token_prefix == token[:12]

        # 认人
        assert mcp_token_service.resolve_user_by_token(db, token).id == viewer.id
        assert mcp_token_service.resolve_user_by_token(db, token + "x") is None
        # viewer 没有 K 权限 → 看和交都被门挡;owner 直通
        actor = mcp_channel.actor_for_user(db, viewer)
        with pytest.raises(mcp_channel.KMcpChannelError) as excinfo:
            mcp_channel.require_k_access(db, actor.user, write=False)
        assert excinfo.value.code == "PERMISSION_DENIED"
        mcp_channel.require_k_access(db, owner, write=True)

        # 管理者停用 → 即刻认不出;本人重置不能复活;管理者启用后又能认出
        mcp_token_service.disable_token_for_user(db, user_id=viewer.id, actor=owner, audit=audit)
        assert mcp_token_service.resolve_user_by_token(db, token) is None
        with pytest.raises(Exception):
            mcp_token_service.reset_own_token(db, user=viewer, audit=audit)
        mcp_token_service.enable_token_for_user(db, user_id=viewer.id, actor=owner, audit=audit)
        assert mcp_token_service.resolve_user_by_token(db, token).id == viewer.id
        # 重置 → 旧的失效、新的可用
        reissued = mcp_token_service.reset_token_for_user(db, user_id=viewer.id, actor=owner, audit=audit)
        assert mcp_token_service.resolve_user_by_token(db, token) is None
        assert mcp_token_service.resolve_user_by_token(db, reissued.token).id == viewer.id
        # 审计落了
        actions = db.execute(text("SELECT action FROM operation_logs WHERE target_id = :t ORDER BY id"), {"t": str(viewer.id)}).scalars().all()
        assert [a for a in actions if a.startswith("mcp_token.")] == [
            "mcp_token.issue", "mcp_token.disable", "mcp_token.enable", "mcp_token.reset",
        ]
        # 账号停用 → 钥匙跟着失效
        viewer.is_active = False; db.add(viewer); db.flush()
        assert mcp_token_service.resolve_user_by_token(db, reissued.token) is None
        db.rollback()
