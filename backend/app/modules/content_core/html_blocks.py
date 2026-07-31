"""定界 HTML 区块——**可原地替换的那一小段**，全站内链的地基。

## 这套机制解决什么

产品页的 description 是控制台生成的，但它不是一次性的:指南发布了、工艺文上线了、
产品下架了,那一段链接就该跟着变。**每次重新生成整个 description 是不行的**——
运营可能已经在 WordPress 里手改过，重生成会把人的编辑抹掉。

所以做法是:把要变的那一小段用**带特征 class 的 ``<section>`` 自定界**圈起来,
刷新时只换这一段,其余一个字节不动。跑一百遍留下的永远是一个块。

## 为什么现在下沉到 content_core

原来这套只服务一个块(GEO 的 ``kp-guides``)，写死在 ``geo_series/content/backlink.py``。
加上工艺文的 ``kp-factory`` 之后有了**两个 class、三个写入方**(P 组包 / 反链派单 /
n8n 的 MERGE_JS)，下沉判据成立。手法和 ``analysis_persist.py`` 一样:把那个唯一
和调用方绑死的东西(那边是表名，这边是 class)做成参数。

## 三个不变量,一个都不能松

1. **``block_class`` 必须显式传参**,不能从 block 字符串里推。因为摘块时
   ``block == ""``，没有 class 可推——这正是老签名只能服务单一 class 的根因。
2. **块内不许出现 ``</div>``,也不许嵌套 ``<section>``**。
   - 前者是 ``rfind("</div>")`` 抢位安全的**充要条件**:产品 description 里有好几个
     块依次插入，每个都靠"找最后一个 ``</div>``"定位外层 ``.kp-desc`` 的收尾。
     只要块内没有 ``</div>``,第二次 rfind 找到的仍然是外层收尾,**先插的块永远
     不会吞掉后插的**。
   - 后者是非贪婪正则的前提。一旦块内嵌套 ``<section>``,``.*?</section>`` 会在
     内层就截断,**线上页面被切出半截 HTML,而且再也替换不掉**(正则从此匹配到
     错误的范围)。
3. **class 不匹配要抛**。``apply_block(html, 用A建的块, block_class="B")`` 会走
   "无则追加"的分支,每跑一次追加一块,线上失控。宁可炸在调用方(两个调用方本来
   就都包在 ``safely`` 里)。
"""

from __future__ import annotations

import html as html_lib
import re

# class 会被拼进正则,先过白名单——绝不让外部字符串直接进 re.compile。
_CLASS_RE = re.compile(r"^[a-z][a-z0-9-]*$")

# 产品页 description 里各块的先后顺序。谁在前谁在后是运营判断,不是技术约束:
# 指南离购买决策更近所以在前,工艺文是信任兜底所以垫底。改这一行就能翻转。
PDP_BLOCK_ORDER: tuple[str, ...] = ("kp-box", "kp-guides", "kp-factory")


class BlockError(RuntimeError):
    """块的形状不合法——放过去会毁掉线上页面。"""


def _require_class(block_class: str) -> str:
    cleaned = str(block_class or "").strip()
    if not _CLASS_RE.match(cleaned):
        raise BlockError(
            f"非法的 block class「{block_class}」——只允许小写字母、数字和连字符。"
        )
    return cleaned


def block_pattern(block_class: str) -> re.Pattern[str]:
    """匹配带这个 class 的自定界 ``<section>``。"""
    cleaned = _require_class(block_class)
    return re.compile(
        rf'<section class="[^"]*\b{re.escape(cleaned)}\b[^"]*">.*?</section>',
        re.IGNORECASE | re.DOTALL,
    )


def js_block_regex_source(block_class: str) -> str:
    """同一条匹配规则的 **JavaScript 字面量**,供 n8n 的 Code 节点使用。

    为什么要有这个:替换逻辑原本在 Python 和 n8n 的 JS 里**各写了一遍**,两份必须
    手工保持同步。让 JS 那份由这里生成之后,两边只有一个真相源——改这里,重新生成
    workflow JSON,两边一起变。测试断言生成出来的 workflow 里含有这个函数的返回值。
    """
    cleaned = _require_class(block_class)
    return f"/<section class=\"[^\"]*\\b{cleaned}\\b[^\"]*\">[\\s\\S]*?<\\/section>/i"


def build_link_block(
    *,
    block_class: str,
    heading: str,
    links: list[tuple[str, str]],
    wrapper_class: str = "kp-box",
) -> str:
    """一个链接块。**空输入返回空串——绝不出空壳**(空壳等于页面上一个没内容的框)。"""
    cleaned = _require_class(block_class)
    rows = [
        (str(title).strip(), str(url).strip())
        for title, url in links
        if str(title or "").strip() and str(url or "").strip()
    ]
    if not rows:
        return ""
    items = "".join(
        f'<li><a href="{html_lib.escape(url)}">{html_lib.escape(title)}</a></li>'
        for title, url in rows
    )
    block = (
        f'<section class="{html_lib.escape(wrapper_class)} {cleaned}">'
        f"<h2>{html_lib.escape(heading)}</h2><ul>{items}</ul></section>"
    )
    assert_block_shape(block)
    return block


def assert_block_shape(block: str) -> None:
    """不变量 2 的守卫。见模块文档——这两条破了,线上页面会被切坏且修不回来。"""
    if not block:
        return
    if "</div>" in block:
        raise BlockError(
            "块内不许出现 </div>——它会抢走 rfind(\"</div>\") 的定位，"
            "后插入的块会被塞进这个块内部。"
        )
    if block.count("<section") > 1:
        raise BlockError(
            "块内不许嵌套 <section>——非贪婪正则会在内层 </section> 截断，"
            "线上页面会被切出半截 HTML 且再也替换不掉。"
        )


def apply_block(html: str, block: str, *, block_class: str) -> str:
    """有则替换、无则在最后一个 ``</div>`` 前插入;``block == ""`` 则删除。

    幂等:跑一百遍留下的永远是恰好一个块。
    """
    cleaned = _require_class(block_class)
    pattern = block_pattern(cleaned)
    if block:
        assert_block_shape(block)
        if not pattern.search(block):
            # 用 A 的 class 建的块拿去替换 B,会走"无则追加",每跑一次多一块。
            raise BlockError(
                f"这个块不带 class「{cleaned}」——用错 class 会让每次刷新都追加一块。"
            )

    current = str(html or "")
    if pattern.search(current):
        # lambda 而不是直接传字符串:替换值里的 \1 之类会被当反向引用解释,
        # 而链接 URL 里完全可能出现反斜杠。
        return pattern.sub(lambda _m: block, current, count=1)
    if not block:
        return current
    closing = current.rfind("</div>")
    if closing < 0:
        return current + block
    return current[:closing] + block + current[closing:]


def apply_blocks(html: str, blocks: list[tuple[str, str]]) -> str:
    """按给定顺序逐个 ``apply_block``。顺序 = 块在页面上的先后。"""
    out = str(html or "")
    for block_class, block in blocks:
        out = apply_block(out, block, block_class=block_class)
    return out


__all__ = [
    "PDP_BLOCK_ORDER",
    "BlockError",
    "apply_block",
    "apply_blocks",
    "assert_block_shape",
    "block_pattern",
    "build_link_block",
    "js_block_regex_source",
]
