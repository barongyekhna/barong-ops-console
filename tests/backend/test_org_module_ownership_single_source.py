"""「哪些模块只属于国际贸易组织」必须只有一份清单，且不按组织名判定。

2026-08-31 体检 + 修复期间实测，这份归属关系一共散在**三处**，各自不同步：

1. `module_registry.INTL_TRADE_ONLY_MODULE_KEYS` —— 按用户过滤。
   漏了 `k./i./p.`：制造组织超管敲 URL 就能打开 K 的创建表单，
   `POST /api/app/k/products` 返回业务校验 422 而不是 403。
2. `module_control_center.TRADE_ONLY_MODULE_IDS` —— 按组织分组过滤。
   漏了 `geo.content` / `seo.content`：owner 的侧边栏里，制造组织下会冒出
   GEO/SEO 内容引擎。
3. 前端 `capability-sidebar-engine.tsx` 里按**组织中文名**比对的遮罩。

三处都靠人手同步，而失效方式是「模块静默出现在不该出现的组织下」——不报错、
不抛异常，只能靠人眼看侧边栏发现。第 3 套已删，第 2 套改成引用第 1 套。

这个文件守两件事：清单只有一份、判定不看组织名。
"""

from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.unit


class TestSingleSourceOfTruth:
    def test_control_center_reuses_the_registry_list(self) -> None:
        """按组织分组用的清单必须**就是**注册表那一份，不能是手抄件。"""
        from backend.app.services.module_control_center import TRADE_ONLY_MODULE_IDS
        from backend.app.services.module_registry import INTL_TRADE_ONLY_MODULE_KEYS

        assert TRADE_ONLY_MODULE_IDS is INTL_TRADE_ONLY_MODULE_KEYS, (
            "TRADE_ONLY_MODULE_IDS 又变成了独立的一份清单。手抄一定会漂移 —— "
            "上一次漂移的结果是制造组织的侧边栏里出现了 GEO/SEO 内容引擎。"
        )

    def test_every_trade_only_module_is_covered(self) -> None:
        """这几个模块历史上分别在某一处清单里漏过，逐个钉死。"""
        from backend.app.services.module_registry import INTL_TRADE_ONLY_MODULE_KEYS

        for key in (
            "k.product_knowledge",   # 后端按用户那份漏过
            "i.image_system",        # 同上
            "p.upload",              # 同上
            "geo.content",           # 后端按组织那份漏过
            "seo.content",           # 同上
            "b2b.wholesale",
            "content.desk",
            "f.enrichment",
            "h.site_health",
            "w.site_ops",
        ):
            assert key in INTL_TRADE_ONLY_MODULE_KEYS, f"{key} 不在组织归属清单里"


class TestOwnershipIsNotDecidedByOrgName:
    def test_per_org_gate_uses_org_type(self) -> None:
        """按组织分组的判定必须看 org_type，不能拿组织名做字符串比较。

        组织名是会变的（工商变更、简称调整）；org_type 是结构性属性。
        原实现里三处都写着 `organization.org_name == "涌龙麟（深圳）国际贸易有限公司"`，
        改一次名字三处一起失效，而且是静默失效。
        """
        from backend.app.services.module_control_center import (
            _module_allowed_for_organization,
        )

        src = inspect.getsource(_module_allowed_for_organization)
        assert "org_type" in src, "按组织分组的判定没有看 org_type"
        assert "org_name" not in src, (
            "按组织分组的判定又用回了组织名比较 —— 改一次组织名就会静默失效。"
        )

    def test_frontend_no_longer_masks_by_org_name(self) -> None:
        """前端不得再出现按组织名的模块遮罩（那是第三套真相源）。"""
        from pathlib import Path

        repo = Path(__file__).resolve().parents[2]
        src = (
            repo / "frontend/src/components/capability-sidebar-engine.tsx"
        ).read_text(encoding="utf-8")
        assert "isRestrictedProductModule" not in src
        assert "isProductKnowledgeOrg" not in src
        assert "isRSeriesOrg" not in src
