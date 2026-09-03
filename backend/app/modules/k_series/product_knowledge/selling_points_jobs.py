"""K 卖点生成:三阶段异步 job。

此前卖点生成是**唯一**留在同步请求路径上的生成类 AI 调用——运营点一下按钮,
浏览器就挂在那里等两次串行 DeepSeek 调用跑完。实测中位数 100s、最慢 903s,
刷新页面等于白等(后端照跑、token 照烧)。
(``ai_provider_router`` 把超时放宽到 240s 时的注释写着「生成类任务全部走异步
job」——卖点正是那个漏网的例外。)

现在拆成三阶段,每阶段跑完立刻落库,运营约 50-100 秒就能看到最值钱的卖点条目,
中文对照和整段商品页文案随后追加:

    bullets  →  zh  →  copy  →  done

**并发安全是这里最要紧的事。** 单请求原子生成时不存在竞态;一拆三步就打开了
它,而且正好命中我们主动鼓励的场景——"运营在阶段 1 出结果后就开始审"。所以
阶段 2/3 落库前一律做 compare-and-swap(见 ``_reclaim_candidates``),任何一条
不满足就放弃写入,绝不把已提交审核的产品退回未审状态。
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from .generation_jobs_stage import set_job_stage
from .models import KProductKnowledgeAIEvent, KProductKnowledgeProduct
from .prompt_skills import (
    SELLING_POINTS_SKILL_VERSION,
    selling_points_copy_instruction,
    selling_points_instruction,
    selling_points_skill_context,
)
from .scope_shim import KScopeContext
from .service import get_product, invalidate_evidence_outputs

logger = logging.getLogger(__name__)

MODULE_KEY = "k.product_knowledge"

STAGE_BULLETS = "bullets"
STAGE_ZH = "zh"
STAGE_COPY = "copy"
STAGE_DONE = "done"


def _now() -> datetime:
    return datetime.now(UTC)


def run_selling_points_job(
    db: Session,
    *,
    job: dict[str, Any],
    user: Any,
    scope: KScopeContext,
) -> str:
    """跑完三阶段,返回 skill_version 供 job 行记录。

    只有阶段 1 失败才向上抛(job 记 failed)——阶段 2/3 是增强,失败只记进
    ``stage_errors`` 让前端提示"中文没翻出来,可单独重试",绝不把已经到手的
    卖点判成失败(前端会把 failed 显示成"什么都没有,请重试",而 failed 是
    死路:``requeue_stale_running`` 只捞 running)。
    """

    job_id = job["id"]
    product_id = job["product_id"]

    if user is None:
        # ``_process_generation_job`` 按 username 重查 user,查不到就是 None。
        # 与其让卖点以匿名身份跑过权限门,不如当场失败。
        raise RuntimeError("selling_points job requires a resolvable requesting user")

    stage_errors: dict[str, str] = {}

    # ---- 阶段 1:卖点本体(唯一的硬失败点)----------------------------------
    set_job_stage(job_id, STAGE_BULLETS)
    _run_bullets_stage(db, job_id=job_id, product_id=product_id, user=user, scope=scope)

    # ---- 阶段 2:逐条中文对照(flash 模型)----------------------------------
    set_job_stage(job_id, STAGE_ZH)
    try:
        _run_zh_stage(db, job_id=job_id, product_id=product_id, user=user, scope=scope)
    except Exception as exc:  # noqa: BLE001 - 增强阶段绝不阻塞已到手的卖点
        logger.exception("selling points zh stage failed product=%s", product_id)
        stage_errors[STAGE_ZH] = str(exc)[:500]
        set_job_stage(job_id, STAGE_ZH, stage_errors=stage_errors)

    # ---- 阶段 3:商品页整段文案 --------------------------------------------
    set_job_stage(job_id, STAGE_COPY)
    try:
        _run_copy_stage(db, job_id=job_id, product_id=product_id, user=user, scope=scope)
    except Exception as exc:  # noqa: BLE001 - 同上
        logger.exception("selling points copy stage failed product=%s", product_id)
        stage_errors[STAGE_COPY] = str(exc)[:500]
        set_job_stage(job_id, STAGE_COPY, stage_errors=stage_errors)

    set_job_stage(job_id, STAGE_DONE, stage_errors=stage_errors or None)
    return SELLING_POINTS_SKILL_VERSION


# --- 阶段 1 ---------------------------------------------------------------


def _run_bullets_stage(
    db: Session,
    *,
    job_id: UUID,
    product_id: UUID,
    user: Any,
    scope: KScopeContext,
) -> None:
    # 循环依赖:router 在模块级 import generation_jobs,generation_jobs 又
    # import 本模块。这些 helper 都住在 router 里,只能延迟到运行时取。
    from .router import (
        _execute_provider_json,
        _mark_selling_point_evidence_status,
        _normalize_selling_points_response,
        _selling_points_evidence_payload,
        _source_text_hash,
        _strict_json_messages,
    )
    from .structured_specs import (
        apply_customer_translations,
        pending_customer_translation_requests,
    )

    product = get_product(db, product_id=product_id, scope_context=scope)
    context = _module_context(db, user=user)
    key = context.key_for_step("deepseek")
    source_name = key.name

    product_payload = _selling_points_evidence_payload(db, product)
    customer_translation_requests = pending_customer_translation_requests(
        product.structured_specs_json
    )
    input_hash = _source_text_hash(
        json.dumps(product_payload, sort_keys=True, default=str)
    )

    ai_payload: dict[str, Any] = {
        "product": product_payload,
        "module_id": MODULE_KEY,
        "task": "selling_points",
        "provider": "deepseek",
        "task_type": "selling_points",
        "selling_points_skill": selling_points_skill_context(stage=STAGE_BULLETS),
        "customer_translation_requests": customer_translation_requests,
        "required_output": [
            "high_conversion_selling_points",
            "structured_bullet_points",
            *(["customer_translations"] if customer_translation_requests else []),
        ],
    }
    ai_payload["messages"] = _strict_json_messages(
        instruction=selling_points_instruction(stage=STAGE_BULLETS),
        payload=ai_payload,
    )

    # 出网前释放事务:k-worker 容器把 idle-in-transaction 掐在 8s,
    # 占着事务打一分钟以上的 AI 调用会被连接层杀掉。
    db.commit()
    provider_output = _execute_provider_json(
        db,
        context=context,
        provider="deepseek",
        task_type="selling_points",
        payload=ai_payload,
    )

    product = get_product(db, product_id=product_id, scope_context=scope)
    if customer_translation_requests:
        translated_specs, translated_package = apply_customer_translations(
            product.structured_specs_json,
            provider_output,
        )
        if translated_specs is not None:
            product.structured_specs_json = translated_specs
            if translated_package:
                product.package_includes_json = translated_package
            # 规格翻译是 one-shot、digest 绑定的,必须在解析卖点信封之前先落库,
            # 否则一个畸形的卖点响应会让同一段供应商文本被重复送去翻译。
            invalidate_evidence_outputs(product)
            db.add(product)
            db.commit()
            product = get_product(db, product_id=product_id, scope_context=scope)

    response = _normalize_selling_points_response(
        provider_output, product=product, source=source_name
    )
    response = _mark_selling_point_evidence_status(db, product, response)

    payload = response.model_dump(mode="json")
    payload["review_status"] = "candidate"
    payload["generated_at"] = _now().isoformat()
    # compare-and-swap 的凭据:阶段 2/3 靠它确认自己写的还是同一轮生成。
    payload["job_id"] = str(job_id)
    payload["stage"] = STAGE_BULLETS

    event = KProductKnowledgeAIEvent(
        id=uuid4(),
        product_id=product.id,
        event_type="selling_points_generation",
        provider=source_name,
        # 不再硬编码 "deepseek-v4-pro":跟着模型注册表走。
        # (注册表是"预期"型号;provider 内部降级时真实型号以 event_streams
        # 的 ai_provider.execute 事件为准,那里记的是 attempt 级实况。)
        provider_model=_resolved_model("selling_points"),
        prompt_version=SELLING_POINTS_SKILL_VERSION,
        input_hash=input_hash,
        output_summary_json={
            "bullet_count": len(response.bullets),
            "target_language": response.target_language,
            "target_market": product.target_market,
            "stage": STAGE_BULLETS,
        },
        output_payload_json=payload,
        status="succeeded",
        created_by_user_id=_user_uuid(user),
        updated_by_user_id=_user_uuid(user),
    )

    # invalidate 只在这里调一次。阶段 2/3 一律 read-modify-write——把这行
    # 复制过去会让阶段 2 清空阶段 1 刚写的一切。
    invalidate_evidence_outputs(product)
    product.deepseek_structured_output_json = {
        **(product.deepseek_structured_output_json or {}),
        "selling_points_generation": provider_output,
    }
    product.selling_points_candidates_json = payload
    _sync_ai_warnings(product, payload)
    db.add_all([product, event])
    db.commit()


# --- 阶段 2:中文对照 ------------------------------------------------------


def _run_zh_stage(
    db: Session,
    *,
    job_id: UUID,
    product_id: UUID,
    user: Any,
    scope: KScopeContext,
) -> None:
    from .router import _enrich_selling_points_chinese, _selling_points_response_from_payload

    claimed = _reclaim_candidates(db, product_id=product_id, scope=scope, job_id=job_id)
    if claimed is None:
        return
    product, payload = claimed

    response = _selling_points_response_from_payload(product, payload)
    context = _module_context(db, user=user)
    db.commit()
    enriched = _enrich_selling_points_chinese(db, context=context, response=response)

    _merge_stage_result(
        db,
        product_id=product_id,
        scope=scope,
        job_id=job_id,
        stage=STAGE_ZH,
        updates={
            "bullets": [bullet.model_dump(mode="json") for bullet in enriched.bullets],
            "chinese_translation": enriched.chinese_translation,
        },
    )


# --- 阶段 3:商品页整段文案 ------------------------------------------------


def _run_copy_stage(
    db: Session,
    *,
    job_id: UUID,
    product_id: UUID,
    user: Any,
    scope: KScopeContext,
) -> None:
    from .router import _execute_provider_json, _strict_json_messages

    claimed = _reclaim_candidates(db, product_id=product_id, scope=scope, job_id=job_id)
    if claimed is None:
        return
    product, payload = claimed

    bullets = [
        {"text": bullet.get("text"), "category": bullet.get("category")}
        for bullet in (payload.get("bullets") or [])
        if isinstance(bullet, dict) and bullet.get("text")
    ]
    if not bullets:
        return

    ai_payload: dict[str, Any] = {
        "task": "selling_points_copy",
        "bullets": bullets,
        "target_language": payload.get("target_language"),
        "selling_points_skill": selling_points_skill_context(stage=STAGE_COPY),
    }
    ai_payload["messages"] = _strict_json_messages(
        instruction=selling_points_copy_instruction(),
        payload=ai_payload,
    )

    context = _module_context(db, user=user)
    db.commit()
    out = _execute_provider_json(
        db,
        context=context,
        provider="deepseek",
        task_type="selling_points_copy",
        payload=ai_payload,
    )
    marketing_copy = out.get("marketing_copy")
    if not isinstance(marketing_copy, str) or not marketing_copy.strip():
        raise RuntimeError("copy stage returned no marketing_copy")

    _merge_stage_result(
        db,
        product_id=product_id,
        scope=scope,
        job_id=job_id,
        stage=STAGE_COPY,
        updates={"marketing_copy": marketing_copy.strip()},
    )


# --- 并发安全 -------------------------------------------------------------


def _reclaim_candidates(
    db: Session,
    *,
    product_id: UUID,
    scope: KScopeContext,
    job_id: UUID,
) -> tuple[KProductKnowledgeProduct, dict[str, Any]] | None:
    """重新加载产品并确认本轮生成仍然有效。

    返回 ``None`` 表示放弃写入。三种情况:运营已提交审核、已被新一轮生成取代、
    候选已离开 candidate 状态。放弃比覆盖安全得多——覆盖会把 ``review_status``
    从 ``reviewed`` 退回 ``candidate``,前端直接翻回未审核。
    """

    db.expire_all()
    product = get_product(db, product_id=product_id, scope_context=scope)

    if product.selling_points_approved_json is not None:
        logger.info(
            "selling points stage skipped: already approved product=%s job=%s",
            product_id,
            job_id,
        )
        return None

    payload = product.selling_points_candidates_json
    if not isinstance(payload, dict):
        return None
    if str(payload.get("job_id") or "") != str(job_id):
        logger.info(
            "selling points stage skipped: superseded product=%s job=%s",
            product_id,
            job_id,
        )
        return None
    if payload.get("review_status") != "candidate":
        return None
    return product, payload


def _merge_stage_result(
    db: Session,
    *,
    product_id: UUID,
    scope: KScopeContext,
    job_id: UUID,
    stage: str,
    updates: dict[str, Any],
) -> None:
    """把一个阶段的产物合并进候选卖点(写回前再验一次归属)。"""

    claimed = _reclaim_candidates(db, product_id=product_id, scope=scope, job_id=job_id)
    if claimed is None:
        return
    product, payload = claimed

    merged = {**payload, **updates, "stage": stage}
    product.selling_points_candidates_json = merged
    _sync_ai_warnings(product, merged)
    db.add(product)
    db.commit()


def _sync_ai_warnings(product: KProductKnowledgeProduct, payload: dict[str, Any]) -> None:
    """维护 ``ai_warnings_json["selling_points"]`` 这条 legacy 回退读路径。

    ``_stored_selling_points_payload`` 在 candidates 也为空时会回落到这里,
    不同步就会让老数据读者永远拿到阶段 1 的半成品。
    """

    prior = product.ai_warnings_json
    prior = prior if isinstance(prior, dict) else {}
    product.ai_warnings_json = {
        # 不要把 approve 删掉的 selling_points_review 复活:这里过滤掉它,
        # 由 approve 流程自己重新写入。
        **{k: v for k, v in prior.items() if k != "selling_points_review"},
        "selling_points": payload,
    }


# --- 杂项 -----------------------------------------------------------------


def _module_context(db: Session, *, user: Any):
    """解析 deepseek key。worker 没有 Request,照 marketing_copy 的既有姿势传 None。"""

    from ....services.module_execution_gate import require_module_execution_ready

    return require_module_execution_ready(
        db,
        module_id=MODULE_KEY,
        user=user,
        request=None,
        key_requirements={"deepseek": "deepseek"},
    )


def _resolved_model(task_type: str) -> str | None:
    from ....services.ai_provider_router import AIModelRouter

    return AIModelRouter.resolve_model(provider="deepseek", task_type=task_type)


def _user_uuid(user: Any) -> UUID | None:
    raw = getattr(user, "id", None)
    if raw is None:
        return None
    try:
        return UUID(str(raw))
    except (TypeError, ValueError):
        return None
