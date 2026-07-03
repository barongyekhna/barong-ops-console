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
HOLIDAY_CATEGORY_SEARCH_TERMS = {
    "holiday-christmas": (
        "christmas tree",
        "christmas stockings",
        "christmas tableware",
        "christmas ornament",
        "christmas decor",
    ),
    "holiday-halloween": (
        "halloween decor",
        "halloween costume accessories",
        "halloween lights",
        "halloween party supplies",
    ),
    "holiday-easter": (
        "easter basket",
        "easter decor",
        "easter egg",
        "easter party supplies",
    ),
    "holiday-thanksgiving": (
        "thanksgiving decor",
        "thanksgiving tableware",
        "thanksgiving centerpiece",
    ),
    "holiday-valentines": (
        "valentines decor",
        "valentines gift",
        "valentines party supplies",
    ),
    "holiday-new-year": (
        "new year decor",
        "new year party supplies",
        "new year tableware",
    ),
}


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


def _node(
    category_id: str,
    name: str,
    *,
    selected: bool = False,
    children: list[CategoryNode] | None = None,
) -> CategoryNode:
    return CategoryNode(
        id=category_id,
        name=name,
        selected=selected,
        children=children or [],
    )


DEFAULT_TREE = CategoryNode(
    id="amazon-product-categories",
    name="亚马逊产品类目",
    selected=False,
    children=[
        _node(
            "1055398",
            "家居与厨房",
            selected=True,
            children=[
                _node("284507", "厨房与餐饮", selected=True),
                _node("16510975011", "床上用品", selected=True),
                _node("510240", "卫浴", selected=True),
                _node("3206324011", "家具", selected=True),
                _node("3736081", "暖通与空气质量", selected=True),
                _node("510106", "家居装饰", selected=True),
                _node("10802561", "儿童家居", selected=True),
                _node("3206325011", "灯具与吊扇", selected=True),
                _node("901590", "节日装饰", selected=True),
                _node("13679381", "收纳整理", selected=True),
                _node("1063252", "吸尘与地面护理", selected=True),
                _node("3610841", "墙面艺术", selected=True),
                _node("1063236", "窗帘与窗饰", selected=True),
                _node("1063278", "熨烫与挂烫", selected=True),
                _node("1063306", "清洁用品", selected=True),
            ],
        ),
        _node(
            "228013",
            "工具与家装",
            selected=True,
            children=[
                _node("8106310011", "建筑用品", selected=True),
                _node("13397451", "电气", selected=True),
                _node("495224", "五金", selected=True),
                _node("328182011", "厨卫固定装置", selected=True),
                _node("553244", "灯泡", selected=True),
                _node("322525011", "灯具与吊扇", selected=True),
                _node("551240", "测量与划线工具", selected=True),
                _node("13400631", "涂装与墙面处理", selected=True),
                _node("3180231", "电动与手动工具", selected=True),
                _node("13749581", "管道基础材料", selected=True),
                _node("228899", "安全与安防", selected=True),
                _node("495266", "收纳与家居整理", selected=True),
                _node("511228", "焊接与焊锡", selected=True),
                _node("3754161", "木工", selected=True),
            ],
        ),
        _node(
            "2972638011",
            "庭院草坪花园",
            selected=True,
            children=[
                _node("215739575011", "农场与牧场", selected=True),
                _node("553632", "园艺与草坪护理", selected=True),
                _node("1272941011", "发电机与便携电源", selected=True),
                _node("552808", "烧烤与户外烹饪", selected=True),
                _node("553760", "户外装饰", selected=True),
                _node("3043471", "户外取暖与降温", selected=True),
                _node("13638732011", "户外动力与草坪设备", selected=True),
                _node("13400641", "户外收纳与棚屋", selected=True),
                _node("553844", "庭院家具与配件", selected=True),
                _node("4619352011", "虫害控制", selected=True),
                _node("3610851", "泳池与热水浴缸", selected=True),
                _node("551242", "除雪工具", selected=True),
                _node("553824", "户外休闲用品", selected=True),
                _node("553788", "水景与池塘", selected=True),
            ],
        ),
        _node(
            "1064954",
            "办公用品",
            selected=True,
            children=[
                _node("172574", "办公与学校用品", selected=True),
                _node("1069242", "办公家具与照明", selected=True),
                _node("1069102", "办公电子", selected=True),
            ],
        ),
        _node(
            "3375251",
            "运动与户外",
            selected=True,
            children=[
                _node("23466320011", "运动与健身", selected=True),
                _node("2358921011", "户外运动", selected=True),
                _node("3407731", "狩猎与钓鱼", selected=True),
                _node("3422351", "团队运动", selected=True),
                _node("10971181011", "训练与健身器材", selected=True),
                _node("3394801", "运动服饰", selected=True),
                _node("706813011", "球迷商店", selected=True),
                _node("3386071", "休闲运动与游戏室", selected=True),
                _node("706814011", "运动收藏品", selected=True),
            ],
        ),
        _node(
            "2617941011",
            "手工艺与缝纫",
            selected=True,
            children=[
                _node("23539912011", "艺术与手工用品", selected=True),
                _node("2237594011", "串珠与首饰制作", selected=True),
                _node("2237329011", "手工制作", selected=True),
                _node("12896841", "布料", selected=True),
                _node("12897221", "布料装饰", selected=True),
                _node("12898821", "针织与钩针", selected=True),
                _node("12896081", "刺绣与针线", selected=True),
                _node("378733011", "手工收纳", selected=True),
                _node("2747968011", "绘画与美术用品", selected=True),
                _node("12899091", "版画", selected=True),
                _node("12899121", "剪贴簿", selected=True),
                _node("12898451", "缝纫", selected=True),
            ],
        ),
        _node(
            "2619533011",
            "宠物用品",
            selected=True,
            children=[
                _node("2975497011", "鸟类用品", selected=True),
                _node("2975481011", "猫用品", selected=True),
                _node("2975446011", "狗用品", selected=True),
                _node("2975520011", "鱼与水族用品", selected=True),
                _node("2975221011", "马用品", selected=True),
                _node("2975504011", "爬宠与两栖用品", selected=True),
                _node("2975312011", "小宠用品", selected=True),
            ],
        ),
        _node(
            "165793011",
            "玩具与游戏",
            selected=True,
            children=[
                _node("19431275011", "收藏玩具", selected=True),
                _node("166333011", "动作玩具与模型", selected=True),
                _node("166118011", "艺术与手工玩具", selected=True),
                _node("166359011", "婴幼儿玩具", selected=True),
                _node("166092011", "积木", selected=True),
                _node("166461011", "玩偶与配件", selected=True),
                _node("6925830011", "电子玩具", selected=True),
                _node("165993011", "学习与教育玩具", selected=True),
                _node("166269011", "游戏", selected=True),
                _node("166420011", "户外玩具", selected=True),
                _node("256994011", "益智拼图", selected=True),
                _node("166316011", "模型与套装", selected=True),
                _node("196601011", "毛绒玩具", selected=True),
                _node("23539911011", "遥控与应用控制玩具", selected=True),
                _node("1266203011", "骑乘玩具", selected=True),
                _node("166164011", "仿真玩具", selected=True),
                _node("166027011", "运动玩具", selected=True),
                _node("166057011", "玩具遥控车", selected=True),
                _node("166220011", "车辆玩具", selected=True),
            ],
        ),
        _node(
            "3760911",
            "美妆与个人护理",
            selected=True,
            children=[
                _node("211908598011", "手足与美甲护理", selected=True),
                _node("17242866011", "美妆工具与配件", selected=True),
                _node("11060451", "香水香氛", selected=True),
                _node("11058281", "头发护理", selected=True),
                _node("11056591", "彩妆", selected=True),
                _node("15144566011", "口腔护理", selected=True),
                _node("3777891", "个人护理", selected=True),
                _node("11057241", "护肤", selected=True),
                _node("11062741", "剃须与脱毛", selected=True),
                _node("3778591", "造型工具", selected=True),
            ],
        ),
        _node(
            "3760901",
            "健康与家居护理",
            selected=False,
            children=[
                _node("8622234011", "宝宝与儿童护理"),
                _node("19763358011", "医疗用品与设备"),
                _node("84631868011", "性健康"),
                _node("723418011", "健康护理"),
                _node("10079992011", "家居诊断与监测"),
                _node("23675621011", "家居医疗"),
                _node("3775161", "家庭护理"),
                _node("10079996011", "医疗测试"),
                _node("3777371", "营养与保健"),
                _node("15342811", "个人护理"),
                _node("10079994011", "运动营养"),
                _node("10787321", "视力护理"),
                _node("3760941", "维生素与膳食补充剂"),
                _node("3764441", "健康用品"),
            ],
        ),
        _node(
            "16310091",
            "工业与科学",
            selected=False,
            children=[
                _node("3061625011", "研磨与精加工"),
                _node("383599011", "加工作业"),
                _node("16310181", "清洁与卫生"),
                _node("6066126011", "商业门禁与安全"),
                _node("8553197011", "切削工具"),
                _node("383598011", "紧固件"),
                _node("3021479011", "过滤"),
                _node("18746931011", "食品服务设备"),
                _node("8498884011", "液压气动与管路"),
                _node("16310191", "工业电气"),
                _node("393459011", "实验室与科学用品"),
                _node("8297371011", "物料搬运"),
                _node("10773802011", "职业健康安全"),
                _node("16412251", "包装与运输用品"),
                _node("8615538011", "动力传动"),
                _node("6054382011", "专业牙科用品"),
                _node("256225011", "专业医疗用品"),
                _node("317971011", "原材料"),
                _node("8297370011", "零售商店装置"),
                _node("256346011", "机器人"),
                _node("306506011", "科学教育"),
                _node("256409011", "测试测量与检测"),
                _node("317970011", "焊接与焊锡"),
            ],
        ),
        _node("2619525011", "家用电器", selected=False),
        _node(
            "holiday-products",
            "节日产品",
            selected=False,
            children=[
                _node("holiday-christmas", "圣诞节"),
                _node("holiday-halloween", "万圣节"),
                _node("holiday-easter", "复活节"),
                _node("holiday-thanksgiving", "感恩节"),
                _node("holiday-valentines", "情人节"),
                _node("holiday-new-year", "新年"),
            ],
        ),
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
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _upgrade_payload_with_default_children(payload)


def selected_category_ids(payload: dict[str, object] | None = None) -> list[str]:
    tree_payload = payload or load_category_tree()
    root_payload = tree_payload["root"]
    root = CategoryNode.from_dict(root_payload) if isinstance(root_payload, dict) else DEFAULT_TREE
    return [node.id for node in iter_nodes(root) if node.selected]


def runnable_selected_category_ids(payload: dict[str, object] | None = None) -> list[str]:
    tree_payload = payload or load_category_tree()
    root_payload = tree_payload["root"]
    root = CategoryNode.from_dict(root_payload) if isinstance(root_payload, dict) else DEFAULT_TREE
    runnable: list[str] = []

    def visit(node: CategoryNode) -> bool:
        child_selected = False
        for child in node.children:
            child_selected = visit(child) or child_selected
        if node.selected and not child_selected and node.id != root.id:
            runnable.append(node.id)
            return True
        return child_selected or node.selected

    visit(root)
    return runnable


def is_holiday_category_id(category_id: str | None) -> bool:
    if category_id is None:
        return False
    return category_id.strip() in HOLIDAY_CATEGORY_SEARCH_TERMS


def holiday_search_terms(category_id: str) -> tuple[str, ...]:
    return HOLIDAY_CATEGORY_SEARCH_TERMS.get(category_id.strip(), ())


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
    for node in iter_nodes(root):
        if node.id in selected and node.children and selected.isdisjoint(_descendant_ids(node)):
            _set_subtree(node, True)
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


def _upgrade_payload_with_default_children(payload: dict[str, object]) -> dict[str, object]:
    root_payload = payload.get("root")
    if not isinstance(root_payload, dict):
        return generate_category_tree_from_amazon_doc()
    current_root = CategoryNode.from_dict(root_payload)
    current_selected = {node.id for node in iter_nodes(current_root) if node.selected}
    default_ids = {node.id for node in iter_nodes(DEFAULT_TREE)}
    current_ids = {node.id for node in iter_nodes(current_root)}
    if default_ids.issubset(current_ids):
        return payload
    upgraded = dict(payload)
    upgraded["root"] = _clone_with_selection(DEFAULT_TREE, current_selected).to_dict()
    upgraded["generated_from"] = "keepa_category_api_subcategories"
    return upgraded


def _clone_with_selection(node: CategoryNode, selected_ids: set[str]) -> CategoryNode:
    return CategoryNode(
        id=node.id,
        name=node.name,
        selected=node.selected or node.id in selected_ids,
        children=[_clone_with_selection(child, selected_ids) for child in node.children],
    )


def _set_subtree(node: CategoryNode, selected: bool) -> None:
    node.selected = selected
    for child in node.children:
        _set_subtree(child, selected)


def _descendant_ids(node: CategoryNode) -> set[str]:
    output: set[str] = set()
    for child in node.children:
        output.add(child.id)
        output.update(_descendant_ids(child))
    return output


def _extract_redline_terms(text: str) -> list[str]:
    candidates = ["restricted", "IP", "易碎", "尺码服装", "强制认证"]
    terms = [term for term in candidates if term in text]
    if terms:
        return terms
    return re.findall(r"[A-Za-z][A-Za-z /&-]{3,40}", text)[:8]
