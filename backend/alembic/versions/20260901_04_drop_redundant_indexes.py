"""删掉 61 条结构性冗余的索引。

2026-09-01 体检：全库有两类白拿的索引，删掉不影响任何查询计划——

**精确重复**：同表、同列、同唯一性，两条一模一样。
**前缀冗余**：存在 (a, b) 时 (a) 是多余的——Postgres 用得了更长的那条。
这是 B-tree 的性质，不是「看起来没人用」的猜测，所以即使某条被扫过很多次
（`api_key_module_bindings` 上那条被扫了 51 万次）删掉也安全：
那些扫描会落到覆盖它的更长索引上。

**为什么值得删**：不是省那 34 MB 磁盘，是省写入。每一条 INSERT/UPDATE 都要
维护表上的每一棵 B-tree。`products_rw`、`k_product_knowledge_variants`、
`event_streams` 是全库写得最频繁的几张表，它们身上都挂着这种白维护的索引。

**没有动**：主键、唯一约束支撑的索引、带不同 WHERE 的部分索引，
以及 event_streams / storage_events 上那 14 条从没被扫过但结构上不冗余的索引
（674 MB，要不要删是留存策略问题，另行决定）。

降级会把它们原样建回来（定义是从生产库 pg_get_indexdef 抓的原文）。

Revision ID: 20260901_04_drop_redundant_indexes
Revises: 20260901_03_auth_session_active_org
"""

from __future__ import annotations

from alembic import op

revision = "20260901_04_drop_redundant_indexes"
down_revision = "20260901_03_auth_session_active_org"
branch_labels = None
depends_on = None


# (索引名, 原始 CREATE INDEX 语句)——降级时照原样建回来。
REDUNDANT_INDEXES: tuple[tuple[str, str], ...] = (
    # agent_memory_access_logs: (org_id) 是 ix_agent_memory_access_logs_org_id_created_at (org_id, created_at) 的前缀
    ("ix_agent_memory_access_logs_org_id", "CREATE INDEX ix_agent_memory_access_logs_org_id ON public.agent_memory_access_logs USING btree (org_id)"),
    # anomaly_events: (org_id) 是 ix_anomaly_events_org_id_type_severity (org_id, anomaly_type, severity) 的前缀
    ("ix_anomaly_events_org_id", "CREATE INDEX ix_anomaly_events_org_id ON public.anomaly_events USING btree (org_id)"),
    # api_key_module_bindings: (org_id) 是 uq_api_key_module_bindings_org_module_key (org_id, module_id, key_id) 的前缀
    ("ix_api_key_module_bindings_org_id", "CREATE INDEX ix_api_key_module_bindings_org_id ON public.api_key_module_bindings USING btree (org_id)"),
    # api_key_module_bindings: (org_id, module_id) 是 uq_api_key_module_bindings_org_module_key (org_id, module_id, key_id) 的前缀
    ("ix_api_key_module_bindings_org_module", "CREATE INDEX ix_api_key_module_bindings_org_module ON public.api_key_module_bindings USING btree (org_id, module_id)"),
    # api_key_records: (org_id) 是 ix_api_key_records_org_id_status (org_id, status) 的前缀
    ("ix_api_key_records_org_id", "CREATE INDEX ix_api_key_records_org_id ON public.api_key_records USING btree (org_id)"),
    # approval_decisions: (org_id) 是 ix_approval_decisions_org_id_created_at (org_id, created_at) 的前缀
    ("ix_approval_decisions_org_id", "CREATE INDEX ix_approval_decisions_org_id ON public.approval_decisions USING btree (org_id)"),
    # approval_requests: (org_id) 是 idx_approval_org_status_created (org_id, status, created_at) 的前缀
    ("ix_approval_requests_org_id", "CREATE INDEX ix_approval_requests_org_id ON public.approval_requests USING btree (org_id)"),
    # approval_requests: (org_id, category, status) 是 ix_approval_requests_org_id_category_status_created_at (org_id, category, status, created_at) 的前缀
    ("ix_approval_requests_org_id_category_status", "CREATE INDEX ix_approval_requests_org_id_category_status ON public.approval_requests USING btree (org_id, category, status)"),
    # approval_requests: (org_id, status) 是 idx_approval_org_status_created (org_id, status, created_at) 的前缀
    ("ix_approval_requests_org_id_status", "CREATE INDEX ix_approval_requests_org_id_status ON public.approval_requests USING btree (org_id, status)"),
    # approval_requests: 与 idx_approval_org_status_created 完全重复
    ("ix_approval_requests_org_id_status_created_at", "CREATE INDEX ix_approval_requests_org_id_status_created_at ON public.approval_requests USING btree (org_id, status, created_at)"),
    # approval_workflows: (org_id) 是 ix_approval_workflows_org_id_approval_id (org_id, approval_id) 的前缀
    ("ix_approval_workflows_org_id", "CREATE INDEX ix_approval_workflows_org_id ON public.approval_workflows USING btree (org_id)"),
    # arcade_high_scores: (org_id) 是 uq_arcade_high_scores_org_id_game_id (org_id, game_id) 的前缀
    ("ix_arcade_high_scores_org_id", "CREATE INDEX ix_arcade_high_scores_org_id ON public.arcade_high_scores USING btree (org_id)"),
    # artifacts: (org_id) 是 ix_artifacts_org_id_created_at (org_id, created_at) 的前缀
    ("ix_artifacts_org_id", "CREATE INDEX ix_artifacts_org_id ON public.artifacts USING btree (org_id)"),
    # audit_logs: (org_id) 是 ix_audit_logs_org_id_context_id (org_id, context_id) 的前缀
    ("ix_audit_logs_org_id", "CREATE INDEX ix_audit_logs_org_id ON public.audit_logs USING btree (org_id)"),
    # automation_jobs: (org_id) 是 ix_automation_jobs_org_id_created_at (org_id, created_at) 的前缀
    ("ix_automation_jobs_org_id", "CREATE INDEX ix_automation_jobs_org_id ON public.automation_jobs USING btree (org_id)"),
    # b2b_email_templates: (kind) 是 uq_b2b_email_templates_combo (kind, language, store_type) 的前缀
    ("ix_b2b_email_templates_kind", "CREATE INDEX ix_b2b_email_templates_kind ON public.b2b_email_templates USING btree (kind)"),
    # b2b_store_type_categories: (store_type_id) 是 uq_b2b_store_type_categories_pair (store_type_id, category_key) 的前缀
    ("ix_b2b_store_type_categories_store", "CREATE INDEX ix_b2b_store_type_categories_store ON public.b2b_store_type_categories USING btree (store_type_id)"),
    # callback_state: (org_id) 是 ix_callback_state_org_id_job_id (org_id, job_id) 的前缀
    ("ix_callback_state_org_id", "CREATE INDEX ix_callback_state_org_id ON public.callback_state USING btree (org_id)"),
    # content_fact_usage: (content_kind, content_id) 是 uq_content_fact_usage (content_kind, content_id, fact_id) 的前缀
    ("ix_content_fact_usage_content", "CREATE INDEX ix_content_fact_usage_content ON public.content_fact_usage USING btree (content_kind, content_id)"),
    # context_packets: (org_id) 是 ix_context_packets_org_id_created_at (org_id, created_at) 的前缀
    ("ix_context_packets_org_id", "CREATE INDEX ix_context_packets_org_id ON public.context_packets USING btree (org_id)"),
    # craft_fact_revisions: (fact_id) 是 uq_craft_fact_revision (fact_id, version) 的前缀
    ("ix_craft_fact_revisions_fact", "CREATE INDEX ix_craft_fact_revisions_fact ON public.craft_fact_revisions USING btree (fact_id)"),
    # dlq_state: (org_id) 是 ix_dlq_state_org_id_context_id (org_id, context_id) 的前缀
    ("ix_dlq_state_org_id", "CREATE INDEX ix_dlq_state_org_id ON public.dlq_state USING btree (org_id)"),
    # event_streams: (org_id) 是 ix_event_streams_org_id_actor_id (org_id, actor_id) 的前缀
    ("ix_event_streams_org_id", "CREATE INDEX ix_event_streams_org_id ON public.event_streams USING btree (org_id)"),
    # event_streams: (processing_status) 是 ix_event_streams_processing_status_next_retry_at (processing_status, next_retry_at) 的前缀
    ("ix_event_streams_processing_status", "CREATE INDEX ix_event_streams_processing_status ON public.event_streams USING btree (processing_status)"),
    # execution_callbacks: (org_id) 是 ix_execution_callbacks_org_id_status (org_id, status) 的前缀
    ("ix_execution_callbacks_org_id", "CREATE INDEX ix_execution_callbacks_org_id ON public.execution_callbacks USING btree (org_id)"),
    # execution_dlq: (org_id) 是 ix_execution_dlq_org_id_context_id (org_id, context_id) 的前缀
    ("ix_execution_dlq_org_id", "CREATE INDEX ix_execution_dlq_org_id ON public.execution_dlq USING btree (org_id)"),
    # execution_results: (org_id) 是 ix_execution_results_org_id_workflow_id (org_id, workflow_id) 的前缀
    ("ix_execution_results_org_id", "CREATE INDEX ix_execution_results_org_id ON public.execution_results USING btree (org_id)"),
    # geo_content_items: (cluster_id) 是 ix_geo_items_cluster_type (cluster_id, item_type) 的前缀
    ("ix_geo_items_cluster", "CREATE INDEX ix_geo_items_cluster ON public.geo_content_items USING btree (cluster_id)"),
    # geo_mined_questions: (cluster_id) 是 uq_geo_mined_questions_cluster_norm (cluster_id, normalized_question) 的前缀
    ("ix_geo_mined_questions_cluster", "CREATE INDEX ix_geo_mined_questions_cluster ON public.geo_mined_questions USING btree (cluster_id)"),
    # job_events: (org_id) 是 ix_job_events_org_id_created_at (org_id, created_at) 的前缀
    ("ix_job_events_org_id", "CREATE INDEX ix_job_events_org_id ON public.job_events USING btree (org_id)"),
    # k_product_knowledge_attributes: (product_id) 是 ix_kpk_attributes_product_key (product_id, attribute_key) 的前缀
    ("ix_kpk_attributes_product", "CREATE INDEX ix_kpk_attributes_product ON public.k_product_knowledge_attributes USING btree (product_id)"),
    # k_product_knowledge_keywords: (product_id, keyword_type) 是 ix_kpk_keywords_lookup (product_id, keyword_type, language_code, market, keyword_text) 的前缀
    ("ix_kpk_keywords_product_type", "CREATE INDEX ix_kpk_keywords_product_type ON public.k_product_knowledge_keywords USING btree (product_id, keyword_type)"),
    # k_product_knowledge_media_assets: (product_id, asset_role) 是 ix_kpk_media_assets_object_lookup (product_id, asset_role, object_key) 的前缀
    ("ix_kpk_media_assets_product_role", "CREATE INDEX ix_kpk_media_assets_product_role ON public.k_product_knowledge_media_assets USING btree (product_id, asset_role)"),
    # k_product_knowledge_risk_terms: (product_id, risk_type) 是 ix_kpk_risk_terms_lookup (product_id, risk_type, term_en) 的前缀
    ("ix_kpk_risk_terms_product_type", "CREATE INDEX ix_kpk_risk_terms_product_type ON public.k_product_knowledge_risk_terms USING btree (product_id, risk_type)"),
    # k_product_knowledge_translations: (product_id) 是 uq_kpk_translations_product_language_source (product_id, language_code, translation_type, source_text_hash) 的前缀
    ("ix_kpk_translations_product", "CREATE INDEX ix_kpk_translations_product ON public.k_product_knowledge_translations USING btree (product_id)"),
    # k_product_knowledge_translations: (product_id, language_code) 是 uq_kpk_translations_product_language_source (product_id, language_code, translation_type, source_text_hash) 的前缀
    ("ix_kpk_translations_product_language", "CREATE INDEX ix_kpk_translations_product_language ON public.k_product_knowledge_translations USING btree (product_id, language_code)"),
    # k_product_knowledge_variants: (product_id) 是 uq_kpk_variants_product_hash (product_id, variant_hash) 的前缀
    ("ix_kpk_variants_product", "CREATE INDEX ix_kpk_variants_product ON public.k_product_knowledge_variants USING btree (product_id)"),
    # k_product_knowledge_versions: (product_id) 是 uq_kpk_versions_product_version (product_id, version_number) 的前缀
    ("ix_kpk_versions_product", "CREATE INDEX ix_kpk_versions_product ON public.k_product_knowledge_versions USING btree (product_id)"),
    # memory_events: (org_id) 是 ix_memory_events_org_id_created_at (org_id, created_at) 的前缀
    ("ix_memory_events_org_id", "CREATE INDEX ix_memory_events_org_id ON public.memory_events USING btree (org_id)"),
    # memory_summaries: (org_id) 是 ix_memory_summaries_org_id_created_at (org_id, created_at) 的前缀
    ("ix_memory_summaries_org_id", "CREATE INDEX ix_memory_summaries_org_id ON public.memory_summaries USING btree (org_id)"),
    # mfg_bom_lines: (product_id) 是 uq_mfg_bom_lines_product_id (product_id, part_id) 的前缀
    ("ix_mfg_bom_lines_product_id", "CREATE INDEX ix_mfg_bom_lines_product_id ON public.mfg_bom_lines USING btree (product_id)"),
    # module_bindings: (org_id) 是 uq_module_bindings_org_id_module_id (org_id, module_id) 的前缀
    ("ix_module_bindings_org_id", "CREATE INDEX ix_module_bindings_org_id ON public.module_bindings USING btree (org_id)"),
    # module_control_states: (org_id) 是 uq_module_control_states_org_id_module_id (org_id, module_id) 的前缀
    ("ix_module_control_states_org_id", "CREATE INDEX ix_module_control_states_org_id ON public.module_control_states USING btree (org_id)"),
    # operation_logs: (org_id) 是 ix_operation_logs_org_id_created_at (org_id, created_at) 的前缀
    ("ix_operation_logs_org_id", "CREATE INDEX ix_operation_logs_org_id ON public.operation_logs USING btree (org_id)"),
    # ops_alert_deliveries: (org_id) 是 ix_ops_alert_deliveries_org_id_status (org_id, status) 的前缀
    ("ix_ops_alert_deliveries_org_id", "CREATE INDEX ix_ops_alert_deliveries_org_id ON public.ops_alert_deliveries USING btree (org_id)"),
    # ops_alerts: 与 uq_ops_alerts_dedupe_key 完全重复
    ("ix_ops_alerts_dedupe_key", "CREATE UNIQUE INDEX ix_ops_alerts_dedupe_key ON public.ops_alerts USING btree (dedupe_key)"),
    # ops_alerts: (org_id) 是 ix_ops_alerts_org_id_module_id (org_id, module_id) 的前缀
    ("ix_ops_alerts_org_id", "CREATE INDEX ix_ops_alerts_org_id ON public.ops_alerts USING btree (org_id)"),
    # ops_canary_rollouts: (org_id) 是 ix_ops_canary_rollouts_org_id_status (org_id, status) 的前缀
    ("ix_ops_canary_rollouts_org_id", "CREATE INDEX ix_ops_canary_rollouts_org_id ON public.ops_canary_rollouts USING btree (org_id)"),
    # ops_execution_unlock_tokens: (org_id) 是 ix_ops_execution_unlock_tokens_org_id_execution (org_id, execution_id, status) 的前缀
    ("ix_ops_execution_unlock_tokens_org_id", "CREATE INDEX ix_ops_execution_unlock_tokens_org_id ON public.ops_execution_unlock_tokens USING btree (org_id)"),
    # ops_live_gate_policies: (org_id) 是 ix_ops_live_gate_policies_org_id_status (org_id, status) 的前缀
    ("ix_ops_live_gate_policies_org_id", "CREATE INDEX ix_ops_live_gate_policies_org_id ON public.ops_live_gate_policies USING btree (org_id)"),
    # ops_rollback_guards: (org_id) 是 ix_ops_rollback_guards_org_id_status (org_id, status) 的前缀
    ("ix_ops_rollback_guards_org_id", "CREATE INDEX ix_ops_rollback_guards_org_id ON public.ops_rollback_guards USING btree (org_id)"),
    # org_memberships: (org_id) 是 ix_org_memberships_org_id_status (org_id, status) 的前缀
    ("ix_org_memberships_org_id", "CREATE INDEX ix_org_memberships_org_id ON public.org_memberships USING btree (org_id)"),
    # products_rw: (category_id) 是 ix_products_rw_category_id_updated (category_id, updated_at) 的前缀
    ("idx_products_rw_category_id", "CREATE INDEX idx_products_rw_category_id ON public.products_rw USING btree (category_id)"),
    # provider_config: (org_id) 是 uq_provider_config_org_module_provider (org_id, module_id, provider) 的前缀
    ("ix_provider_config_org_id", "CREATE INDEX ix_provider_config_org_id ON public.provider_config USING btree (org_id)"),
    # provider_config: (org_id, module_id) 是 uq_provider_config_org_module_provider (org_id, module_id, provider) 的前缀
    ("ix_provider_config_org_module", "CREATE INDEX ix_provider_config_org_module ON public.provider_config USING btree (org_id, module_id)"),
    # replay_jobs: (org_id) 是 ix_replay_jobs_org_id_trace_id (org_id, trace_id) 的前缀
    ("ix_replay_jobs_org_id", "CREATE INDEX ix_replay_jobs_org_id ON public.replay_jobs USING btree (org_id)"),
    # review_items: (org_id) 是 ix_review_items_org_id_created_at (org_id, created_at) 的前缀
    ("ix_review_items_org_id", "CREATE INDEX ix_review_items_org_id ON public.review_items USING btree (org_id)"),
    # shared_modules: (source_org_id) 是 uq_shared_modules_source_target_module (source_org_id, target_org_id, module_id) 的前缀
    ("ix_shared_modules_source_org_id", "CREATE INDEX ix_shared_modules_source_org_id ON public.shared_modules USING btree (source_org_id)"),
    # shared_modules: (target_org_id) 是 ix_shared_modules_target_org_id_module_id (target_org_id, module_id) 的前缀
    ("ix_shared_modules_target_org_id", "CREATE INDEX ix_shared_modules_target_org_id ON public.shared_modules USING btree (target_org_id)"),
    # storage_events: (org_id) 是 ix_storage_events_org_id_context_id (org_id, context_id) 的前缀
    ("ix_storage_events_org_id", "CREATE INDEX ix_storage_events_org_id ON public.storage_events USING btree (org_id)"),
    # system_errors: (org_id) 是 ix_system_errors_org_id_created_at (org_id, created_at) 的前缀
    ("ix_system_errors_org_id", "CREATE INDEX ix_system_errors_org_id ON public.system_errors USING btree (org_id)"),
)


def upgrade() -> None:
    # IF EXISTS：这些索引里有一部分是运行时建表逻辑（event_collector._ensure_tables）
    # 造出来的，不同环境不一定都有。缺一条不该让整条迁移链停住。
    for name, _ in REDUNDANT_INDEXES:
        op.execute(f'DROP INDEX IF EXISTS public."{name}"')


def downgrade() -> None:
    for _, create_sql in REDUNDANT_INDEXES:
        op.execute(create_sql.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ", 1))
