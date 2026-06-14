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
from ..deps import get_current_user

router = APIRouter(prefix="/external-dependencies", tags=["external-dependencies"])


@router.get("/registry", response_model=ExternalServiceRegistryResponse)
def external_service_registry(
    user: User = Depends(get_current_user),
) -> ExternalServiceRegistryResponse:
    del user
    services = list_external_services()
    return ExternalServiceRegistryResponse(items=services, count=len(services))


@router.get("/proposals", response_model=ExternalServiceProposalListResponse)
def external_service_registration_proposals(
    user: User = Depends(get_current_user),
) -> ExternalServiceProposalListResponse:
    del user
    proposals = list_registration_proposals()
    return ExternalServiceProposalListResponse(
        items=proposals,
        count=len(proposals),
    )


@router.get("/bindings", response_model=ExternalDependencyBindingListResponse)
def external_dependency_bindings(
    user: User = Depends(get_current_user),
) -> ExternalDependencyBindingListResponse:
    del user
    bindings = build_dependency_binding_decisions()
    return ExternalDependencyBindingListResponse(
        items=bindings,
        count=len(bindings),
    )


@router.get("/binding-rules", response_model=DependencyBindingRuleSetResponse)
def external_dependency_binding_rules(
    user: User = Depends(get_current_user),
) -> DependencyBindingRuleSetResponse:
    del user
    return list_dependency_binding_rules()


@router.get("/dependency-graph", response_model=DependencyGraphResponse)
def external_dependency_graph(
    user: User = Depends(get_current_user),
) -> DependencyGraphResponse:
    del user
    return build_dependency_graph_response()


@router.get(
    "/binding-validation",
    response_model=DependencyBindingValidationResult,
)
def external_dependency_binding_validation(
    user: User = Depends(get_current_user),
) -> DependencyBindingValidationResult:
    del user
    return validate_dependency_binding_rules()


@router.get("/binding-audit", response_model=DependencyBindingAuditResponse)
def external_dependency_binding_audit(
    user: User = Depends(get_current_user),
) -> DependencyBindingAuditResponse:
    del user
    return build_dependency_binding_audit_response()
