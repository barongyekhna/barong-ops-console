"""员工技能手册:文件在、带来源与 MIT、有必需小节、加载器指纹稳定、进了提示词。不碰库。"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.modules.amz_series import prompt_skills as ps
from backend.app.modules.amz_series.agents import brain
from backend.app.modules.amz_series.constants import EMPLOYEES

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]

REQUIRED_SECTIONS = {
    "d/ads-funnel-and-bids.md": ("财务框架", "四活动漏斗", "出价调整档", "否词", "需求储备"),
    "a/listing-copy.md": ("字符上限", "标题", "五点", "后台搜索词", "8 维审计", "它不是什么"),
    "b/listing-images.md": ("七图职责", "信息图设计", "移动端", "同屏", "核过:"),
    "c/competitors-and-sqp.md": ("SQP", "点击份额 > 购买份额", "评论合规", "季节日历", "只报变化"),
    "shared/pnl-and-inventory.md": ("利润瀑布", "FBA 尺寸层级", "到岸成本", "补货点", "变体"),
}


def test_every_handbook_exists_with_source_header_and_required_sections() -> None:
    assert set(REQUIRED_SECTIONS) == set(ps.ALL_SKILL_FILES)
    for relative, sections in REQUIRED_SECTIONS.items():
        text, digest = ps.load_skill(relative)
        head = "\n".join(text.splitlines()[:6])
        for mark in ps.REQUIRED_HEADER_MARKS:
            assert mark in head, (relative, mark)
        for section in sections:
            assert section in text, (relative, section)
        assert len(digest) == 64
        # 剥壳:访谈壳和多平台泛化不能留下
        assert "多选格式" not in text and "Shopify" not in text and "第四步" not in text


def test_skills_for_each_employee_fits_budget_and_manifest_is_stable() -> None:
    for employee in EMPLOYEES:
        text = ps.skills_for(employee)
        assert text.startswith("## 你的技能手册") and ps.SKILLS_VERSION in text
        assert len(text) <= ps.MAX_CHARS_PER_EMPLOYEE + 200
    assert "护栏" in ps.skills_for("D") and "需求储备" in ps.skills_for("D")
    assert "它不是什么" in ps.skills_for("A") and "核过:" in ps.skills_for("B")
    assert "点击份额 > 购买份额" in ps.skills_for("C")
    manifest = ps.manifest()
    assert set(manifest) == set(ps.ALL_SKILL_FILES) and manifest == ps.manifest()
    with pytest.raises(KeyError):
        ps.skills_for("Z")


def test_handbook_is_second_system_message_in_chat_and_speak() -> None:
    chat = brain.build_chat_messages("D", user_message="x", speaker_name="boss", snapshot={})
    assert chat[0]["content"].startswith("你是「殷素素」") and chat[1]["content"].startswith("## 你的技能手册")
    speak = brain.build_speak_messages("A", suggestion={"id": "s", "title": "t"})
    assert speak[1]["content"].startswith("## 你的技能手册") and "殷笑笑" in speak[0]["content"]


def test_sources_doc_lists_every_handbook() -> None:
    doc = (ROOT / "docs/AMZ_SKILL_SOURCES.md").read_text(encoding="utf-8")
    for relative in ps.ALL_SKILL_FILES:
        assert relative in doc
    assert "MIT" in doc and "liangdabiao/Amazon-Skills-Liang" in doc
