from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.registry import AgentRegistry, ModuleRegistry, WorkflowRegistry
from ..schemas.registry import AgentCreate, ModuleCreate, WorkflowCreate
from ..services.event_collector import emit_event


def list_modules(
    db: Session, *, limit: int, offset: int
) -> list[ModuleRegistry]:
    modules = list(
        db.scalars(
            select(ModuleRegistry)
            .order_by(ModuleRegistry.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    emit_event(
        event_type="category_tree.read",
        module="system",
        action="category_tree.read",
        source="system",
        status="success",
        payload={"operation": "list_modules", "count": len(modules)},
    )
    return modules


def get_module(db: Session, module_key: str) -> ModuleRegistry | None:
    return db.scalar(
        select(ModuleRegistry).where(ModuleRegistry.module_id == module_key)
    )


def create_module(db: Session, payload: ModuleCreate) -> ModuleRegistry:
    values = payload.model_dump(exclude={"module_key"})
    module = ModuleRegistry(module_id=payload.module_key, **values)
    db.add(module)
    emit_event(
        event_type="category_tree.update",
        module="system",
        action="category_tree.update",
        source="system",
        status="success",
        payload={
            "operation": "create_module",
            "module_key": payload.module_key,
            "status": payload.status,
        },
    )
    return module


def list_agents(
    db: Session, *, limit: int, offset: int
) -> list[AgentRegistry]:
    return list(
        db.scalars(
            select(AgentRegistry)
            .order_by(AgentRegistry.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )


def get_agent(db: Session, agent_key: str) -> AgentRegistry | None:
    return db.scalar(
        select(AgentRegistry).where(AgentRegistry.agent_id == agent_key)
    )


def create_agent(db: Session, payload: AgentCreate) -> AgentRegistry:
    values = payload.model_dump(
        exclude={
            "agent_key",
            "allowed_module_keys",
            "allowed_workflow_keys",
        }
    )
    agent = AgentRegistry(
        agent_id=payload.agent_key,
        allowed_module_ids=payload.allowed_module_keys,
        allowed_workflow_ids=payload.allowed_workflow_keys,
        **values,
    )
    db.add(agent)
    return agent


def list_workflows(
    db: Session, *, limit: int, offset: int
) -> list[WorkflowRegistry]:
    return list(
        db.scalars(
            select(WorkflowRegistry)
            .order_by(WorkflowRegistry.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )


def get_workflow(
    db: Session, workflow_key: str
) -> WorkflowRegistry | None:
    return db.scalar(
        select(WorkflowRegistry).where(
            WorkflowRegistry.workflow_id == workflow_key
        )
    )


def create_workflow(
    db: Session, payload: WorkflowCreate
) -> WorkflowRegistry:
    values = payload.model_dump(exclude={"workflow_key"})
    workflow = WorkflowRegistry(
        workflow_id=payload.workflow_key,
        **values,
    )
    db.add(workflow)
    return workflow
