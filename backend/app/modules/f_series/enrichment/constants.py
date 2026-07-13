"""Module-local constants for the F category enrichment module."""

MODULE_KEY = "f.enrichment"
API_PREFIX = "/f"

# 死命令：F/W/H/视觉这批独立站模块只属于国际贸易一个组织。
TARGET_ORGANIZATION_NAME = "涌龙麟（深圳）国际贸易有限公司"

PERMISSION_READ = "f.enrichment.read"
PERMISSION_EXECUTE = "f.enrichment.execute"
PERMISSION_REVIEW = "f.enrichment.review"

PERMISSION_KEYS = frozenset(
    {
        PERMISSION_READ,
        PERMISSION_EXECUTE,
        PERMISSION_REVIEW,
    }
)

OPERATION_RUN_STARTED = "f.enrichment.run.started"
OPERATION_CANDIDATE_CREATED = "f.enrichment.candidate.created"
OPERATION_CANDIDATE_REVIEWED = "f.enrichment.candidate.reviewed"
OPERATION_IMPORTED_TO_K = "f.enrichment.imported_to_k"

# 一次运行最多爬多少个类目节点（选了过大的父类目时拒绝，请用户收窄）。
MAX_NODES_PER_RUN = 150

# running 状态超过这个时长没有任何进度更新按失联收尸（惰性，list 时执行）。
RUN_STALE_MINUTES = 30
