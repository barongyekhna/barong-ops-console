"""串行队列「只许有一份实现」的静态守卫。

刻意和 `test_n8n_queue_contract.py` 分开：那份要真数据库（走 integration 通道，
四分钟一轮），这份纯静态、进 unit 通道，**每次跑单元测试都能挡住第六份副本**。
守卫放在慢通道里等于半个守卫。
"""

from __future__ import annotations

from types import SimpleNamespace

import backend.app.models  # noqa: F401 - 先装载模型注册表，避免直接 import 触发循环
from backend.app.modules.p_series.upload import jobs as p_jobs

def test_nobody_grows_a_sixth_copy_of_the_queue() -> None:
    """串行队列只许有一份实现。

    这套东西曾经在五个模块里各有一份，而且**实测已经分叉**（2026-09-03 比对）：
    四份的 urlopen 不读响应体、收僵尸文案三种写法、SQLAlchemy 调用风格各写各的。
    分叉本身不致命，致命的是下次修 bug 只会修到其中一份。

    刻意排除的两份（不是漏了，是不能合，理由见 n8n_dispatch 的模块注释）：
      · `w_series/logistics.py`  —— 按 target 串行 + definitive/uncertain 错误分类
      · `h_series/sitehealth`    —— 根本没有队列
    """
    from pathlib import Path

    allowed = {
        # 唯一实现
        "backend/app/services/n8n_dispatch.py",
        # 有意例外 ①：按 target 串行，带 definitive/uncertain 错误分类和全站
        # 锁序约定。并进共享队列会重开运费重复写入的口子。
        "backend/app/modules/w_series/logistics.py",
        # 有意例外 ②：**根本没有队列**，就是一次同步调用；10 秒超时被规格
        # 文档锁死，不是可调参数。
        "backend/app/modules/h_series/sitehealth/service.py",
    }
    offenders = []
    for path in Path("backend/app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        # 「自己发 webhook」的特征：直接开 urlopen 打一个 webhook 环境变量
        if "urllib.request.urlopen" in text and "N8N" in text:
            if str(path) not in allowed:
                offenders.append(str(path))
    assert offenders == [], (
        f"这些文件又自己写了一份 n8n 派单：{offenders}；"
        "请改用 services/n8n_dispatch.py"
    )


def test_all_five_queues_share_one_engine() -> None:
    """五个模块的 kick_queue 都必须转发到共享实现。"""
    from backend.app.modules.b2b.widget import jobs as b2b_widget
    from backend.app.modules.geo_series.content import backlink_jobs, publish_jobs
    from backend.app.modules.seo_series.content import publish_jobs as seo_publish
    from backend.app.services import n8n_dispatch

    modules = [p_jobs, publish_jobs, backlink_jobs, seo_publish, b2b_widget]
    for module in modules:
        spec = module._QUEUE
        assert isinstance(spec, n8n_dispatch.QueueSpec), module.__name__
        # 看门狗文案必须含「未回传」：P 的 record_result 靠这三个字区分
        # 「推测的失败」和「事实的失败」，缺了它迟到的成功就翻不了案。
        assert "未回传" in spec.stale_error, module.__name__
        # 载荷三件套，n8n 那头取包和回调全靠它们
        payload = spec.build_payload(
            SimpleNamespace(
                job_id="j", channel="c", token="tk", cluster_id="cl", product_id="pd"
            ),
            "https://base.test",
        )
        assert {"job_id", "token", "package_url", "callback_url"} <= payload.keys()
        assert "token=tk" in payload["package_url"], module.__name__


def test_empty_callback_base_fails_loudly(monkeypatch) -> None:
    """回调地址的根是空的时候必须当场炸，不能发一个相对地址出去。

    2026-09-03 实测：内容台读的 `PUBLIC_API_BASE_URL` 在生产容器里没设置，
    返回空串，现在靠 `P_CALLBACK_BASE` 挡着。这条钉住「挡不住的时候会出声」——
    否则整条链静默失败：任务照常派出、照常等回传、15 分钟后被判失联，
    没有一处会说「地址是错的」。
    """
    import pytest

    from backend.app.services import n8n_dispatch

    monkeypatch.delenv("P_CALLBACK_BASE", raising=False)
    with pytest.raises(RuntimeError, match="没有主机名"):
        n8n_dispatch.callback_base("")
    with pytest.raises(RuntimeError):
        n8n_dispatch.callback_base("   ")

    # 正对照：给了值就正常返回，并且去掉尾斜杠
    assert n8n_dispatch.callback_base("https://x.test/") == "https://x.test"
    monkeypatch.setenv("P_CALLBACK_BASE", "https://override.test/")
    assert n8n_dispatch.callback_base("https://x.test") == "https://override.test"
