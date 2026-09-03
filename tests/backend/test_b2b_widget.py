"""产品页 B2B 小窗:契约红线、派单不变式、公开询盘入口。

背景(2026-07-29 用户提出):店家逛产品页看不出这货能批发。小窗是热线索入口
——他已经站在店里了。
"""

from __future__ import annotations

import pytest

from backend.app.modules.b2b import policies
from backend.app.modules.b2b.contract.widget_package import (
    B2B_WIDGET_PACKAGE_VERSION,
    WIDGET_META_KEY,
    WidgetPackage,
    WidgetTarget,
)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------
# 契约红线:价格在契约层就塞不进去
# --------------------------------------------------------------------------


def test_contract_has_no_field_that_can_carry_a_price() -> None:
    """**最重要的一条测试。**

    小窗上不显示批发价:GMC 把"页面价与 feed 价不符"判成 Misrepresentation,
    这个账号被封过两次只剩一次申诉。契约层没有字段能承载价格,后面谁也塞不进去。
    """
    fields = set(WidgetTarget.model_fields)
    for banned in ("price", "wholesale_price", "unit_price", "msrp", "cost"):
        assert banned not in fields, banned
    with pytest.raises(Exception):
        WidgetTarget(sku="X", woo_product_id=1, wholesale_price="9.99")


def test_unavailable_target_carries_no_numbers() -> None:
    """撤下时不带任何数据——插件读到 available=false 就什么都不渲染。"""
    target = WidgetTarget(sku="ET-001", woo_product_id=4025, available=False)
    assert target.moq_units is None
    assert target.case_pack is None
    assert target.lead_time_days is None


def test_package_pins_its_version_and_meta_key() -> None:
    """n8n 的 Code 节点硬断言版本;meta 键也走契约,不在两处各写一份。"""
    package = WidgetPackage()
    assert package.schema_version == B2B_WIDGET_PACKAGE_VERSION
    assert package.meta_key == WIDGET_META_KEY == "_kp_b2b"


# --------------------------------------------------------------------------
# 政策:图册和小窗同源,红线不许丢
# --------------------------------------------------------------------------


def test_widget_policies_never_mention_price_or_card_payment() -> None:
    text = " ".join(entry["text"] for entry in policies.widget_policies()).lower()
    for banned in ("credit card", "paypal", "$", "18.50", "wholesale price"):
        assert banned not in text, banned


def test_free_shipping_line_is_scoped_to_wholesale_first_order_and_sea() -> None:
    """三条都是钱的问题:

    - 不带 "wholesale" 会和零售的「满 $100 免运费」撞口径 → 又一个 GMC 雷
    - 不带 "sea freight only",客户走 UPS 红单能把整单利润吃光
    - 不带 "first",读起来就是**每一单都免运费**(2026-07-30 用户抓到我漏了):
      既白送钱,又和页面/图册写的 first 打架
    """
    entry = next(
        e for e in policies.widget_policies() if e["key"] == "free_shipping"
    )
    text = entry["text"].lower()
    assert "wholesale" in text
    assert "sea freight only" in text
    assert "first" in text


def test_line_sheet_keeps_the_uppercase_sea_freight_lock() -> None:
    joined = " ".join(policies.line_sheet_notes())
    assert "SEA FREIGHT ONLY" in joined
    assert "credited in full" in joined


def test_private_label_wording_avoids_the_oem_odm_cliche() -> None:
    """每封中国工厂群发的垃圾邮件都写 OEM/ODM,美国零售商看到就归类成
    阿里巴巴供应商。他们自己叫 private label。"""
    entry = next(
        e for e in policies.widget_policies() if e["key"] == "private_label"
    )
    assert "private label" in entry["text"].lower()
    assert "oem" not in entry["text"].lower()
    assert "odm" not in entry["text"].lower()


def test_policies_are_single_sourced_by_the_line_sheet_renderer() -> None:
    """图册渲染器必须从 policies 取,不许自己抄一份——抄了门槛一改两边对不上。"""
    from backend.app.modules.b2b.wholesale import service as wholesale_service

    assert wholesale_service.CONTACT_PHONE is policies.CONTACT_PHONE
    assert wholesale_service.DEFAULT_PAYMENT_TERMS is policies.PAYMENT_TERMS
    assert list(wholesale_service.line_sheet_notes()) == list(
        policies.line_sheet_notes()
    )


# --------------------------------------------------------------------------
# 派单不变式(照 GEO 那条守卫测试,靠源码检查钉死顺序)
# --------------------------------------------------------------------------


def _jobs_source() -> str:
    from pathlib import Path

    import backend.app.modules.b2b.widget.jobs as jobs_module

    return Path(jobs_module.__file__).read_text(encoding="utf-8")


def test_widget_queue_uses_the_shared_serial_engine() -> None:
    """小窗推送共用 `services/n8n_dispatch.py`。

    四条不变量（收僵尸 / 严格串行 / **先提交再发送** / 失败递归）由
    `tests/backend/test_n8n_queue_contract.py` 真跑验证。这里只钉住
    「B2B 确实用的是那一份」以及本模块特有的载荷形状 ——
    2026-09-03 之前这两条断的是源码文本，换个写法就能绕过去。
    """
    from types import SimpleNamespace

    from backend.app.modules.b2b.widget import jobs as widget_jobs
    from backend.app.services import n8n_dispatch

    assert widget_jobs.IN_FLIGHT_TIMEOUT_MINUTES == 15
    assert isinstance(widget_jobs._QUEUE, n8n_dispatch.QueueSpec)
    assert widget_jobs._QUEUE.model is widget_jobs.B2BWidgetJob
    assert "未回传" in widget_jobs._QUEUE.stale_error
    payload = widget_jobs._QUEUE.build_payload(
        SimpleNamespace(job_id="j4", channel="wp", token="t4"), "https://base.test"
    )
    assert "/b2b/widget-jobs/j4/package?token=t4" in payload["package_url"]
    assert payload["callback_url"].endswith("/b2b/widget-jobs/j4/result")


def test_record_result_is_terminal_state_idempotent() -> None:
    """n8n 重试不该把成功改成失败。"""
    source = _jobs_source()
    assert 'if job.status in {"success", "failed"}:' in source


# --------------------------------------------------------------------------
# n8n 工作流:爆炸半径
# --------------------------------------------------------------------------


def _workflow() -> dict:
    import json
    from pathlib import Path

    import backend.app.modules.b2b.n8n.build_widget_workflow as builder

    path = Path(builder.__file__).with_name("b2b_widget_workflow.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _node(workflow: dict, name: str) -> dict:
    return next(n for n in workflow["nodes"] if n["name"] == name)


def test_workflow_writes_only_the_widget_meta_key() -> None:
    """只碰 meta_data 一个键。description / price / images / status 分别
    归 GEO 反链、Woo、P 系列管——历史上打过架。"""
    split = _node(_workflow(), "拆产品")["parameters"]["jsCode"]
    for banned in (
        "description",
        "regular_price",
        "sale_price",
        "images",
        "status:",
        "categories",
    ):
        assert banned not in split, banned
    assert "meta_data" in split


def test_workflow_writes_the_key_even_when_removing() -> None:
    """撤下时写空串而不是跳过,否则产品页会留着过期的小窗。"""
    split = _node(_workflow(), "拆产品")["parameters"]["jsCode"]
    assert "t.available" in split
    assert ": ''" in split


def test_workflow_asserts_the_package_version_and_maps_every_item() -> None:
    split = _node(_workflow(), "拆产品")["parameters"]["jsCode"]
    assert B2B_WIDGET_PACKAGE_VERSION in split
    # 只取第一条会把整批压成一个产品(GEO 发布流踩过)
    assert "targets.map(" in split
    assert "$input.first().json" in split  # 包本身是单条,这里取包是对的


def test_workflow_is_its_own_flow_and_active_version_matches() -> None:
    workflow = _workflow()
    assert workflow["id"] == "barongB2Bwidget001"
    # 只改 workflow_entity 不生效,执行读历史表——两个 id 必须一致
    assert workflow["versionId"] == workflow["activeVersionId"]
    assert workflow["active"] is True


# --------------------------------------------------------------------------
# 询盘入口:走 CS 那条已在生产上的路,不另开公开写入口
# --------------------------------------------------------------------------


def test_only_wholesale_channel_becomes_a_b2b_lead() -> None:
    """零售询盘不该跑进 B2B 线索池。"""
    from backend.app.modules.b2b import inbound_bridge

    class Msg:
        channel = "retail"
        email = "shopper@gmail.com"
        name = "Sam"
        company = None
        message = "where is my order"
        source_url = ""
        status = "new"

    assert inbound_bridge.ingest_wholesale_inquiry(None, Msg()) is None


def test_inquiry_without_email_is_ignored() -> None:
    from backend.app.modules.b2b import inbound_bridge

    class Msg:
        channel = "wholesale"
        email = ""
        name = "Sam"
        company = "Shop"
        message = "hi"
        source_url = ""
        status = "new"

    assert inbound_bridge.ingest_wholesale_inquiry(None, Msg()) is None


def test_bridge_never_raises_into_the_customer_service_path() -> None:
    """**客服消息优先**：B2B 出任何问题都不许把它带崩。"""
    from backend.app.modules.b2b import inbound_bridge

    class Exploding:
        @property
        def channel(self):
            raise RuntimeError("boom")

    inbound_bridge.ingest_wholesale_inquiry_safely(None, Exploding())  # 不抛
