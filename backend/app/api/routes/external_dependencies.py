from fastapi import APIRouter, Depends

from ...models.user import User
from ...schemas.dependency_binding import (
    DependencyBindingAuditResponse,
    DependencyBindingRuleSetResponse,
    DependencyBindingValidationResult,
    DependencyGraphResponse,
)
from ...schemas.external_dependency import (
    ExternalDependencyBindingListResponse,
    ExternalServiceProposalListResponse,
    ExternalServiceRegistryResponse,
)
from ...services.dependency_binding_rules import (
    build_dependency_binding_audit_response,
    build_dependency_graph_response,
    list_dependency_binding_rules,
    validate_dependency_binding_rules,
)
from ...services.external_dependency_governance import (
    build_dependency_binding_decisions,
    list_external_services,
    list_registration_proposals,
)
from ..deps import require_rbac

router = APIRouter(prefix="/external-dependencies", tags=["external-dependencies"])


@router.get("/registry", response_model=ExternalServiceRegistryResponse)
def external_service_registry(
    user: User = Depends(require_rbac("C14", "admin")),
) -> ExternalServiceRegistryResponse:
    del user
    services = list_external_services()
    return ExternalServiceRegistryResponse(items=services, count=len(services))


@router.get("/proposals", response_model=ExternalServiceProposalListResponse)
def external_service_registration_proposals(
    user: User = Depends(require_rbac("C14", "admin")),
) -> ExternalServiceProposalListResponse:
    del user
    proposals = list_registration_proposals()
    return ExternalServiceProposalListResponse(
        items=proposals,
        count=len(proposals),
    )


@router.get("/bindings", response_model=ExternalDependencyBindingListResponse)
def external_dependency_bindings(
    user: User = Depends(require_rbac("C14", "admin")),
) -> ExternalDependencyBindingListResponse:
    del user
    bindings = build_dependency_binding_decisions()
    return ExternalDependencyBindingListResponse(
        items=bindings,
        count=len(bindings),
    )


@router.get("/binding-rules", response_model=DependencyBindingRuleSetResponse)
def external_dependency_binding_rules(
    user: User = Depends(require_rbac("C14", "admin")),
) -> DependencyBindingRuleSetResponse:
    del user
    return list_dependency_binding_rules()


@router.get("/dependency-graph", response_model=DependencyGraphResponse)
def external_dependency_graph(
    user: User = Depends(require_rbac("C14", "admin")),
) -> DependencyGraphResponse:
    del user
    return build_dependency_graph_response()


@router.get(
    "/binding-validation",
    response_model=DependencyBindingValidationResult,
)
def external_dependency_binding_validation(
    user: User = Depends(require_rbac("C14", "admin")),
) -> DependencyBindingValidationResult:
    del user
    return validate_dependency_binding_rules()


@router.get("/binding-audit", response_model=DependencyBindingAuditResponse)
def external_dependency_binding_audit(
    user: User = Depends(require_rbac("C14", "admin")),
) -> DependencyBindingAuditResponse:
    del user
    return build_dependency_binding_audit_response()
