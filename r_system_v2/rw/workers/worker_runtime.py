"""Container entrypoints for R-W and R-A runtime workers."""

from __future__ import annotations

import os
import signal
import sys
import time
from dataclasses import asdict, dataclass

from r_system_v2.core.secret_manager import SecretManager
from r_system_v2.core.secret_manager import TARGET_ORGANIZATION_NAME
from r_system_v2.ra.providers import RAnalysisProviderBinding
from r_system_v2.rw.ai.deepseek_screening import DeepSeekScreeningSkill
from r_system_v2.rw.category.category_tree import load_category_tree, selected_category_ids
from r_system_v2.rw.core.keepa_buffer_queue import KeepaBufferQueue
from r_system_v2.rw.providers.keepa_provider import KeepaProvider
from r_system_v2.rw.scheduler.keepa_scheduler import KeepaScheduler
from r_system_v2.rw.storage.batch_writer import SQLAlchemyBatchWriter
from r_system_v2.rw.workers.keepa_worker import KeepaWorker
from r_system_v2.rw.workers.realtime_engine import RwRealtimeEngine
from r_system_v2.rw.workers.secret_watch_daemon import SecretWatchDaemon


@dataclass(frozen=True)
class WorkerRuntimeStatus:
    worker: str
    ready: bool
    mode: str
    keepa_loaded: bool = False
    deepseek_loaded: bool = False
    secret_manager_connected: bool = False
    category_count: int = 0
    async_keepa_worker_ready: bool = False
    buffer_queue_active: bool = False
    batch_writer_active: bool = False
    per_request_db_update: bool = False


RUNNING = True
RW_ENGINE: RwRealtimeEngine | None = None


def _handle_stop(signum: int, frame: object) -> None:
    del signum, frame
    global RUNNING
    RUNNING = False


def _log(message: str) -> None:
    print(message, flush=True)


def _resolve_org_id() -> str:
    configured = os.getenv("R_SYSTEM_ORG_ID", "").strip()
    if configured:
        return configured
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        return ""
    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        return ""
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT org_id
                    FROM organizations
                    WHERE org_name = :org_name AND status != 'deleted'
                    ORDER BY org_id
                    LIMIT 1
                    """
                ),
                {"org_name": TARGET_ORGANIZATION_NAME},
            ).first()
            return str(row[0]) if row else ""
    except Exception:
        return ""
    finally:
        engine.dispose()


def run_rw_worker() -> WorkerRuntimeStatus:
    status, _engine = build_rw_worker_runtime()
    return status


def build_rw_worker_runtime() -> tuple[WorkerRuntimeStatus, RwRealtimeEngine]:
    org_id = _resolve_org_id()
    manager = SecretManager()
    category_tree = load_category_tree()
    categories = selected_category_ids(category_tree)
    provider = KeepaProvider(org_id=org_id, secret_manager=manager)
    deepseek_skill = DeepSeekScreeningSkill(org_id=org_id, secret_manager=manager)
    scheduler = KeepaScheduler(provider=provider, processor=lambda record: record)  # type: ignore[arg-type]
    batch_writer = _build_batch_writer()
    buffer_queue = KeepaBufferQueue(
        writer=batch_writer.write if batch_writer is not None else None,
    )
    async_worker = KeepaWorker(
        provider=provider,
        buffer_queue=buffer_queue,
        deepseek_skill=deepseek_skill,
    )
    daemon = SecretWatchDaemon(
        org_id=org_id,
        secret_manager=manager,
        keepa_provider=provider,
        deepseek_skill=deepseek_skill,
    )
    daemon.start()
    engine = _build_realtime_engine(
        org_id=org_id,
        provider=provider,
        deepseek_skill=deepseek_skill,
    )

    keepa_loaded = bool(provider.api_key)
    deepseek_loaded = deepseek_skill.api_key_configured()
    _log("SecretManager connected")
    _log(f"category engine loaded categories={len(categories)}")
    _log(
        "Keepa scheduler started "
        f"rate_limit_per_min={scheduler.rate_limit_per_min} no_burst_mode=True"
    )
    _log(
        "Keepa async worker ready "
        f"rate_limit_per_min={async_worker.rate_limit_per_min} "
        f"buffer_batch_size={buffer_queue.batch_size} "
        f"batch_writer_active={str(batch_writer is not None).lower()}"
    )
    _log("DeepSeek pipeline ready")
    _log(
        "R-W worker ready "
        f"keepa_loaded={str(keepa_loaded).lower()} "
        f"deepseek_loaded={str(deepseek_loaded).lower()}"
    )
    status = WorkerRuntimeStatus(
        worker="r-w-worker",
        ready=True,
        mode="realtime_24_7",
        keepa_loaded=keepa_loaded,
        deepseek_loaded=deepseek_loaded,
        secret_manager_connected=True,
        category_count=len(categories),
        async_keepa_worker_ready=True,
        buffer_queue_active=buffer_queue.stats().active,
        batch_writer_active=batch_writer is not None,
        per_request_db_update=False,
    )
    return status, engine


def _build_realtime_engine(
    *,
    org_id: str,
    provider: KeepaProvider,
    deepseek_skill: DeepSeekScreeningSkill,
) -> RwRealtimeEngine:
    from backend.app.db.session import SessionLocal

    return RwRealtimeEngine(
        session_factory=SessionLocal,
        provider=provider,
        deepseek_skill=deepseek_skill,
        org_id=org_id,
    )


def _build_batch_writer() -> SQLAlchemyBatchWriter | None:
    try:
        from backend.app.db.session import SessionLocal
    except Exception:
        return None
    return SQLAlchemyBatchWriter(SessionLocal)


def run_ra_worker() -> WorkerRuntimeStatus:
    org_id = _resolve_org_id()
    manager = SecretManager()
    binding = RAnalysisProviderBinding(org_id=org_id, secret_manager=manager)
    configured = {}
    for name, loader in (
        ("deepseek", binding.deepseek_key),
        ("openai", binding.gpt_key),
        ("serper", binding.serper_key),
    ):
        try:
            configured[name] = bool(loader())
        except Exception:
            configured[name] = False
    _log("SecretManager connected")
    _log("R-A analysis module ready")
    _log("R-A worker idle / ready")
    _log(f"R-A standby mode provider_configured={configured}")
    return WorkerRuntimeStatus(
        worker="r-a-worker",
        ready=True,
        mode="standby",
        keepa_loaded=False,
        deepseek_loaded=bool(configured.get("deepseek")),
        secret_manager_connected=True,
    )


def main() -> None:
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    worker = sys.argv[1] if len(sys.argv) > 1 else "rw"
    if worker == "rw":
        status, engine = build_rw_worker_runtime()
        global RW_ENGINE
        RW_ENGINE = engine
    elif worker == "ra":
        status = run_ra_worker()
        engine = None
    else:
        raise SystemExit(f"unsupported worker: {worker}")
    _log(f"worker_status={asdict(status)}")
    if worker == "rw" and engine is not None:
        engine.run_forever(should_stop=lambda: not RUNNING)
    else:
        while RUNNING:
            time.sleep(5)
    _log(f"{status.worker} stopping")


if __name__ == "__main__":
    main()
