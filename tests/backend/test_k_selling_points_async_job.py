"""卖点生成改成后台三阶段 job 之后的守卫。

背景(2026-08-03):卖点生成此前是**唯一**留在同步请求路径上的生成类 AI 调用。
实测台账 21 次调用中位数 100s、最慢 903s,运营点一下按钮就得干等,刷新页面
等于白等(后端照跑、token 照烧)。现在拆成 bullets → zh → copy 三阶段异步 job。

这里钉死的是那次改造里**最容易悄悄坏掉**的几件事。
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from backend.app.db.session import SessionLocal
from backend.app.modules.k_series.product_knowledge import generation_jobs
from backend.app.modules.k_series.product_knowledge.scope_shim import KScopeContext

pytestmark = pytest.mark.integration


def _scope() -> KScopeContext:
    return KScopeContext(
        workspace_key="ws_test",
        business_context="intl_trade",
        scope_mode="single",
    )


def _active_jobs(db, product_id) -> list[dict]:
    rows = db.execute(
        text(
            """
            SELECT id, job_type, status, stage, stage_errors
            FROM k_generation_jobs
            WHERE product_id = :pid
            ORDER BY created_at
            """
        ),
        {"pid": product_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def test_selling_points_is_a_registered_job_type() -> None:
    """漏登记 = 入队直接 ValueError。"""

    assert "selling_points" in generation_jobs.JOB_TYPES


def test_unknown_job_type_raises_instead_of_silently_running_image_brief() -> None:
    """分发分支此前的兜底是 `else: generate_image_brief(...)`。

    也就是说任何新加的 job_type 只要忘了加分支,就会**静默跑成作图指令生成**
    ——不报错、状态还标 completed。这条测试守住"宁可炸出来"。
    """

    job = {
        "id": uuid4(),
        "product_id": uuid4(),
        "job_type": "definitely_not_a_real_job_type",
        "requested_by_username": None,
        "workspace_key": None,
        "business_context": None,
        "scope_mode": None,
    }
    # 失败会被 _process_generation_job 捕获并写进 job 行,所以直接看落库的状态。
    with SessionLocal() as db:
        db.execute(
            text(
                """
                INSERT INTO k_generation_jobs (id, product_id, job_type, status)
                VALUES (:id, :pid, :jt, 'running')
                """
            ),
            {"id": job["id"], "pid": job["product_id"], "jt": job["job_type"]},
        )
        db.commit()

    generation_jobs._process_generation_job(job)

    with SessionLocal() as db:
        row = db.execute(
            text("SELECT status, error FROM k_generation_jobs WHERE id = :id"),
            {"id": job["id"]},
        ).mappings().first()

    assert row is not None
    assert row["status"] == "failed"
    assert "unhandled job_type" in (row["error"] or "")


def test_enqueue_deduplicates_while_a_job_is_still_active() -> None:
    """连点两次「生成」不该跑两遍。

    此前完全没有去重:两条 pending → worker 并发跑两遍同一个产品 → 都写回
    同一行(后写的赢),AI 费用白烧一倍。前端按钮 disable 挡不住刷新页面和
    双标签页,所以保证做在数据库的 partial unique index 上。
    """

    product_id = uuid4()
    with SessionLocal() as db:
        _, first = generation_jobs.enqueue_generation_jobs(
            db,
            product_ids=[product_id],
            job_type="selling_points",
            user=None,
            scope_context=_scope(),
        )
        db.commit()
        _, second = generation_jobs.enqueue_generation_jobs(
            db,
            product_ids=[product_id],
            job_type="selling_points",
            user=None,
            scope_context=_scope(),
        )
        db.commit()

        rows = _active_jobs(db, product_id)

    assert len(first) == 1
    assert len(second) == 1
    # 第二次复用了第一次那条,而不是新建。
    assert second[0]["job_id"] == first[0]["job_id"]
    assert second[0].get("deduplicated") is True
    assert len(rows) == 1, rows


def test_enqueue_allows_a_new_job_once_the_previous_one_finished() -> None:
    """去重只针对**未完成**的任务 —— 跑完了当然还能重新生成。"""

    product_id = uuid4()
    with SessionLocal() as db:
        _, first = generation_jobs.enqueue_generation_jobs(
            db,
            product_ids=[product_id],
            job_type="selling_points",
            user=None,
            scope_context=_scope(),
        )
        db.commit()
        db.execute(
            text("UPDATE k_generation_jobs SET status='completed' WHERE id = :id"),
            {"id": first[0]["job_id"]},
        )
        db.commit()

        _, second = generation_jobs.enqueue_generation_jobs(
            db,
            product_ids=[product_id],
            job_type="selling_points",
            user=None,
            scope_context=_scope(),
        )
        db.commit()
        rows = _active_jobs(db, product_id)

    assert second[0]["job_id"] != first[0]["job_id"]
    assert len(rows) == 2


def test_different_job_types_do_not_block_each_other() -> None:
    """去重的粒度是 (产品, 类型)。卖点在跑不该挡住品牌审查。"""

    product_id = uuid4()
    with SessionLocal() as db:
        generation_jobs.enqueue_generation_jobs(
            db,
            product_ids=[product_id],
            job_type="selling_points",
            user=None,
            scope_context=_scope(),
        )
        generation_jobs.enqueue_generation_jobs(
            db,
            product_ids=[product_id],
            job_type="brand_audit",
            user=None,
            scope_context=_scope(),
        )
        db.commit()
        rows = _active_jobs(db, product_id)

    assert {r["job_type"] for r in rows} == {"selling_points", "brand_audit"}


def test_stage_progress_is_recorded_on_the_job_row() -> None:
    """进度必须落在 job 行上。

    塞进 selling_points_candidates_json 是行不通的:GET /selling-points 走
    _selling_points_response_from_payload,它按固定字段清单重建响应、未知键
    被整个剥掉;而且运营一提交审核,候选就被覆写,进度会跟着消失。
    """

    from backend.app.modules.k_series.product_knowledge.generation_jobs_stage import (
        set_job_stage,
    )

    product_id = uuid4()
    with SessionLocal() as db:
        _, created = generation_jobs.enqueue_generation_jobs(
            db,
            product_ids=[product_id],
            job_type="selling_points",
            user=None,
            scope_context=_scope(),
        )
        db.commit()
    job_id = created[0]["job_id"]

    set_job_stage(job_id, "bullets")
    set_job_stage(job_id, "zh")
    set_job_stage(job_id, "done", stage_errors={"zh": "AI_PROVIDER_TIMEOUT"})

    with SessionLocal() as db:
        rows = _active_jobs(db, product_id)
        # 2026-08-31 起 jobs_status 按 workspace 过滤(裸 SQL 必须带租户条件),
        # 所以查询侧要和入队侧用同一个 scope——不传就等于查默认 workspace。
        status = generation_jobs.jobs_status(
            db, product_id=product_id, scope_context=_scope()
        )

    assert rows[0]["stage"] == "done"
    # 增强阶段失败要留痕,但卖点本体照常可用(job 不标 failed)。
    assert rows[0]["stage_errors"] == {"zh": "AI_PROVIDER_TIMEOUT"}
    # 前端靠 jobs_status 拿这两个字段驱动分步显示,漏了就没有进度条。
    assert status[0]["stage"] == "done"
    assert status[0]["stage_errors"] == {"zh": "AI_PROVIDER_TIMEOUT"}
