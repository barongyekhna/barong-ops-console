"""Category tree generation and selection logic for Keepa ingestion."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]
AMAZON_RULES_PATH = REPO_ROOT / "r_system_v2" / "docs" / "amazon.md"
CATEGORY_TREE_PATH = Path(__file__).resolve().parent / "category_tree.json"


@dataclass
class CategoryNode:
    id: str
    name: str
    children: list["CategoryNode"] = field(default_factory=list)
    selected: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "children": [child.to_dict() for child in self.children],
            "selected": self.selected,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "CategoryNode":
        return cls(
            id=str(payload["id"]),
            name=str(payload["name"]),
            selected=bool(payload.get("selected", False)),
            children=[
                cls.from_dict(child)
                for child in payload.get("children", [])
                if isinstance(child, dict)
            ],
        )


DEFAULT_TREE = CategoryNode(
    id="amazon-product-categories",
    name="亚马逊产品类目",
    selected=False,
    children=[
        CategoryNode(id="1055398", name="家居与厨房", selected=True),
        CategoryNode(id="228013", name="工具与家装", selected=True),
        CategoryNode(id="2972638011", name="庭院草坪花园", selected=True),
        CategoryNode(id="1064954", name="办公用品", selected=True),
        CategoryNode(id="3375251", name="运动与户外", selected=True),
        CategoryNode(id="2617941011", name="手工艺与缝纫", selected=True),
        CategoryNode(id="2619533011", name="宠物用品", selected=True),
        CategoryNode(id="165793011", name="玩具与游戏", selected=True),
        CategoryNode(id="3760911", name="美妆与个人护理", selected=True),
        CategoryNode(id="3760901", name="健康与家居护理", selected=False),
        CategoryNode(id="16310091", name="工业与科学", selected=False),
        CategoryNode(id="2619525011", name="家用电器", selected=False),
    ],
)


def generate_category_tree_from_amazon_doc(
    doc_path: Path = AMAZON_RULES_PATH,
    output_path: Path = CATEGORY_TREE_PATH,
) -> dict[str, object]:
    text = doc_path.read_text(encoding="utf-8") if doc_path.exists() else ""
    tree = DEFAULT_TREE
    redline_terms = _extract_redline_terms(text)
    payload = {
        "source": str(doc_path),
        "generated_from": "amazon.md",
        "redline_terms": redline_terms,
        "root": tree.to_dict(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return payload


def load_category_tree(path: Path = CATEGORY_TREE_PATH) -> dict[str, object]:
    if not path.exists():
        return generate_category_tree_from_amazon_doc(output_path=path)
    return json.loads(path.read_text(encoding="utf-8"))


def selected_category_ids(payload: dict[str, object] | None = None) -> list[str]:
    tree_payload = payload or load_category_tree()
    root_payload = tree_payload["root"]
    root = CategoryNode.from_dict(root_payload) if isinstance(root_payload, dict) else DEFAULT_TREE
    return [node.id for node in iter_nodes(root) if node.selected]


def apply_selected_categories(
    payload: dict[str, object],
    selected_categories: list[str] | None,
) -> dict[str, object]:
    if selected_categories is None:
        return payload
    selected = set(selected_categories)
    root_payload = payload["root"]
    root = CategoryNode.from_dict(root_payload) if isinstance(root_payload, dict) else DEFAULT_TREE
    available = {node.id for node in iter_nodes(root)}
    if selected and selected.isdisjoint(available):
        return payload
    for node in iter_nodes(root):
        node.selected = node.id in selected
    updated = dict(payload)
    updated["root"] = root.to_dict()
    return updated


def select_category_in_payload(
    payload: dict[str, object],
    category_id: str,
    selected: bool,
) -> dict[str, object]:
    root_payload = payload["root"]
    root = CategoryNode.from_dict(root_payload) if isinstance(root_payload, dict) else DEFAULT_TREE
    _select_node(root, category_id, selected)
    updated = dict(payload)
    updated["root"] = root.to_dict()
    return updated


def select_category(category_id: str, selected: bool, path: Path = CATEGORY_TREE_PATH) -> dict[str, object]:
    payload = load_category_tree(path)
    payload = select_category_in_payload(payload, category_id, selected)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return payload


def iter_nodes(root: CategoryNode) -> Iterable[CategoryNode]:
    yield root
    for child in root.children:
        yield from iter_nodes(child)


def _select_node(node: CategoryNode, category_id: str, selected: bool) -> bool:
    if node.id == category_id:
        node.selected = selected
        for child in node.children:
            _set_subtree(child, selected)
        return True
    for child in node.children:
        if _select_node(child, category_id, selected):
            return True
    return False


def _set_subtree(node: CategoryNode, selected: bool) -> None:
    node.selected = selected
    for child in node.children:
        _set_subtree(child, selected)


def _extract_redline_terms(text: str) -> list[str]:
    candidates = ["restricted", "IP", "易碎", "尺码服装", "强制认证"]
    terms = [term for term in candidates if term in text]
    if terms:
        return terms
    return re.findall(r"[A-Za-z][A-Za-z /&-]{3,40}", text)[:8]
