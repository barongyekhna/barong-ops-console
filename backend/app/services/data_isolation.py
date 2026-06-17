from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, event, inspect, select
from sqlalchemy.orm import Session, ORMExecuteState, with_loader_criteria
from sqlalchemy.sql.dml import Delete, Update
from sqlalchemy.sql.elements import TextClause

from ..db.base import Base
from ..schemas.organization import ORG_ID_PATTERN
from .event_collector import emit_event

ORG_DATA_ISOLATION_SKIP_OPTION = "skip_org_data_isolation"
ORG_ID_FIELD = "org_id"


class OrgDataIsolationError(PermissionError):
    pass


class OrgDataIsolationMissingContextError(OrgDataIsolationError):
    pass


class OrgDataIsolationMissingOrgIdError(OrgDataIsolationError):
    pass


class OrgDataIsolationCrossOrgError(OrgDataIsolationError):
    pass


class OrgDataIsolationOrgNotFoundError(OrgDataIsolationError):
    pass


class OrgDataIsolationManualSqlError(OrgDataIsolationError):
    pass


@dataclass(frozen=True)
class OrgDataIsolationUserContext:
    org_id: str | None
    user_id: str | None
    role: str
    source: str = "unknown"
    strict: bool = True

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"


_current_user_context: ContextVar[OrgDataIsolationUserContext | None] = ContextVar(
    "c18g_org_data_isolation_user_context",
    default=None,
)


def current_org_data_isolation_context() -> OrgDataIsolationUserContext | None:
    return _current_user_context.get()


def set_org_data_isolation_context(
    context: OrgDataIsolationUserContext,
) -> Token[OrgDataIsolationUserContext | None]:
    return _current_user_context.set(context)


def reset_org_data_isolation_context(
    token: Token[OrgDataIsolationUserContext | None],
) -> None:
    _current_user_context.reset(token)


@contextmanager
def org_data_isolation_context(context: OrgDataIsolationUserContext):
    token = set_org_data_isolation_context(context)
    try:
        yield
    finally:
        reset_org_data_isolation_context(token)


@contextmanager
def without_org_data_isolation():
    token = _current_user_context.set(None)
    try:
        yield
    finally:
        _current_user_context.reset(token)


def _normalize_org_id(org_id: str | None) -> str | None:
    if org_id is None:
        return None
    normalized = org_id.strip()
    if not normalized:
        return None
    return normalized


def _valid_org_id(org_id: str | None) -> bool:
    return org_id is not None and ORG_ID_PATTERN.fullmatch(org_id) is not None


def _event_payload(
    *,
    reason: str,
    context: OrgDataIsolationUserContext | None,
    model: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "reason": reason,
        "org_id": context.org_id if context is not None else None,
        "user_id": context.user_id if context is not None else None,
        "role": context.role if context is not None else None,
        "context_source": context.source if context is not None else None,
        "model": model,
    }
    if extra:
        payload.update(extra)
    return payload


def _emit_violation(
    *,
    reason: str,
    context: OrgDataIsolationUserContext | None,
    model: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    emit_event(
        event_type="org_data_isolation.violation",
        module="system",
        action="c18g.data_isolation",
        source="backend",
        status="failed",
        user_id=context.user_id if context is not None else None,
        payload=_event_payload(
            reason=reason,
            context=context,
            model=model,
            extra=extra,
        ),
    )


def _is_skip_enabled(execution_options: Any) -> bool:
    try:
        return bool(execution_options.get(ORG_DATA_ISOLATION_SKIP_OPTION))
    except AttributeError:
        return False


def _context_requires_scope(context: OrgDataIsolationUserContext | None) -> bool:
    return context is not None and context.strict


def _context_requires_write_org(context: OrgDataIsolationUserContext | None) -> bool:
    return context is not None and context.strict


def _org_scoped_mapper(mapper: Any) -> bool:
    return ORG_ID_FIELD in mapper.columns


def _org_scoped_classes() -> tuple[type[Any], ...]:
    classes: list[type[Any]] = []
    for mapper in Base.registry.mappers:
        if _org_scoped_mapper(mapper):
            classes.append(mapper.class_)
    return tuple(classes)


def get_org_scoped_model_names() -> tuple[str, ...]:
    return tuple(sorted(cls.__name__ for cls in _org_scoped_classes()))


def get_models_missing_org_id() -> tuple[str, ...]:
    missing: list[str] = []
    for mapper in Base.registry.mappers:
        if not _org_scoped_mapper(mapper):
            missing.append(mapper.class_.__name__)
    return tuple(sorted(missing))


def _mapped_class_for_table(table: Any) -> type[Any] | None:
    for mapper in Base.registry.mappers:
        if mapper.local_table is table:
            return mapper.class_
    return None


def _object_org_id(obj: Any) -> str | None:
    return _normalize_org_id(getattr(obj, ORG_ID_FIELD, None))


def _set_object_org_id(obj: Any, org_id: str) -> None:
    setattr(obj, ORG_ID_FIELD, org_id)


def _object_model_name(obj: Any) -> str:
    return obj.__class__.__name__


def _object_is_org_scoped(obj: Any) -> bool:
    try:
        mapper = inspect(obj).mapper
    except Exception:
        return False
    return _org_scoped_mapper(mapper)


def _ensure_context_org_id(context: OrgDataIsolationUserContext) -> str:
    org_id = _normalize_org_id(context.org_id)
    if not _valid_org_id(org_id):
        _emit_violation(
            reason="missing_or_invalid_context_org_id",
            context=context,
        )
        raise OrgDataIsolationMissingContextError(
            "C18G requires a valid org_id in the current user context."
        )
    return org_id


def _organization_exists_in_session_new(session: Session, org_id: str) -> bool:
    for obj in session.new:
        if (
            obj.__class__.__name__ == "OrganizationRecord"
            and _object_org_id(obj) == org_id
        ):
            return True
    return False


def _organization_exists(session: Session, org_id: str) -> bool:
    cache = session.info.setdefault("c18g_existing_org_ids", set())
    if org_id in cache:
        return True
    if _organization_exists_in_session_new(session, org_id):
        cache.add(org_id)
        return True

    from ..models.organization import OrganizationRecord

    connection = session.connection(
        execution_options={ORG_DATA_ISOLATION_SKIP_OPTION: True}
    )
    row = connection.execute(
        select(OrganizationRecord.org_id)
        .where(OrganizationRecord.org_id == org_id)
        .execution_options(**{ORG_DATA_ISOLATION_SKIP_OPTION: True})
    ).first()
    if row is None:
        return False
    cache.add(org_id)
    return True


def _validate_existing_org(
    session: Session,
    org_id: str,
    context: OrgDataIsolationUserContext,
) -> None:
    if _organization_exists(session, org_id):
        return
    _emit_violation(
        reason="organization_not_found",
        context=context,
        extra={"validated_org_id": org_id},
    )
    raise OrgDataIsolationOrgNotFoundError(
        "C18G write rejected because org_id does not reference an organization."
    )


def _protect_insert(
    session: Session,
    obj: Any,
    context: OrgDataIsolationUserContext,
) -> None:
    org_id = _ensure_context_org_id(context)
    supplied_org_id = _object_org_id(obj)
    model = _object_model_name(obj)
    if supplied_org_id is None:
        _set_object_org_id(obj, org_id)
    elif supplied_org_id != org_id:
        _emit_violation(
            reason="conflicting_insert_org_id",
            context=context,
            model=model,
            extra={"supplied_org_id": supplied_org_id},
        )
        raise OrgDataIsolationCrossOrgError(
            "C18G rejected an insert with an org_id outside the current context."
        )
    _validate_existing_org(session, org_id, context)


def _protect_update_or_delete(
    session: Session,
    obj: Any,
    context: OrgDataIsolationUserContext,
    *,
    operation: str,
) -> None:
    org_id = _ensure_context_org_id(context)
    object_org_id = _object_org_id(obj)
    model = _object_model_name(obj)
    if object_org_id is None:
        _emit_violation(
            reason=f"{operation}_missing_org_id",
            context=context,
            model=model,
        )
        raise OrgDataIsolationMissingOrgIdError(
            f"C18G rejected {operation} because the object has no org_id."
        )
    if object_org_id != org_id:
        _emit_violation(
            reason=f"cross_org_{operation}",
            context=context,
            model=model,
            extra={"object_org_id": object_org_id},
        )
        raise OrgDataIsolationCrossOrgError(
            f"C18G rejected cross-org {operation}."
        )
    _validate_existing_org(session, org_id, context)


class OrgDataIsolationLayer:
    @staticmethod
    def apply_scope(
        query: Select[Any],
        user_context: OrgDataIsolationUserContext,
    ) -> Select[Any]:
        org_id = _ensure_context_org_id(user_context)
        scoped_query = query
        for mapped_class in _org_scoped_classes():
            scoped_query = scoped_query.options(
                with_loader_criteria(
                    mapped_class,
                    lambda model: model.org_id == org_id,
                    include_aliases=True,
                )
            )
        return scoped_query


class OrgDataIsolationSession(Session):
    def execute(
        self,
        statement: Any,
        params: Any | None = None,
        *,
        execution_options: Any | None = None,
        bind_arguments: Any | None = None,
        **kw: Any,
    ) -> Any:
        if not _is_skip_enabled(execution_options or {}):
            self._enforce_raw_sql_guard(statement)
        return super().execute(
            statement,
            params=params,
            execution_options=execution_options or {},
            bind_arguments=bind_arguments,
            **kw,
        )

    def get(self, entity: Any, ident: Any, **kwargs: Any) -> Any:
        obj = super().get(entity, ident, **kwargs)
        context = current_org_data_isolation_context()
        if (
            obj is not None
            and _context_requires_scope(context)
            and _object_is_org_scoped(obj)
            and _object_org_id(obj) != _ensure_context_org_id(context)
        ):
            _emit_violation(
                reason="cross_org_identity_map_get",
                context=context,
                model=_object_model_name(obj),
                extra={"object_org_id": _object_org_id(obj)},
            )
            return None
        return obj

    def _enforce_raw_sql_guard(self, statement: Any) -> None:
        context = current_org_data_isolation_context()
        if not _context_requires_scope(context):
            return
        if isinstance(statement, TextClause):
            sql = statement.text
        elif isinstance(statement, str):
            sql = statement
        else:
            return

        normalized = sql.lower()
        guarded_statement = normalized.lstrip().startswith(
            ("select", "insert", "update", "delete")
        )
        if guarded_statement and ORG_ID_FIELD not in normalized:
            _emit_violation(
                reason="manual_sql_missing_org_id_filter",
                context=context,
            )
            raise OrgDataIsolationManualSqlError(
                "C18G rejected raw SQL without an org_id filter."
            )


def _handle_orm_execute(execute_state: ORMExecuteState) -> None:
    if _is_skip_enabled(execute_state.execution_options):
        return

    context = current_org_data_isolation_context()
    if not _context_requires_scope(context):
        return

    org_id = _ensure_context_org_id(context)
    statement = execute_state.statement

    if execute_state.is_select:
        execute_state.statement = OrgDataIsolationLayer.apply_scope(
            statement,
            context,
        )
        return

    if isinstance(statement, (Update, Delete)):
        mapped_class = _mapped_class_for_table(statement.table)
        if mapped_class is None:
            return
        if not _org_scoped_mapper(inspect(mapped_class)):
            return
        execute_state.statement = statement.where(
            getattr(mapped_class, ORG_ID_FIELD) == org_id
        )


def _handle_before_flush(
    session: Session,
    flush_context: Any,
    instances: Any,
) -> None:
    del flush_context, instances
    context = current_org_data_isolation_context()
    if not _context_requires_write_org(context):
        return

    for obj in list(session.new):
        if _object_is_org_scoped(obj):
            _protect_insert(session, obj, context)

    for obj in list(session.dirty):
        if _object_is_org_scoped(obj) and obj not in session.new:
            _protect_update_or_delete(
                session,
                obj,
                context,
                operation="update",
            )

    for obj in list(session.deleted):
        if _object_is_org_scoped(obj):
            _protect_update_or_delete(
                session,
                obj,
                context,
                operation="delete",
            )


_events_installed = False


def install_org_data_isolation_events() -> None:
    global _events_installed
    if _events_installed:
        return
    event.listen(OrgDataIsolationSession, "do_orm_execute", _handle_orm_execute)
    event.listen(OrgDataIsolationSession, "before_flush", _handle_before_flush)
    _events_installed = True
