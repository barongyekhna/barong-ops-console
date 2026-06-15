from fastapi import APIRouter, HTTPException, status


router = APIRouter(tags=["security-firewall"])

_BLOCKED_METHODS = (
    "GET",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "OPTIONS",
    "HEAD",
)


def _blocked_direct_access() -> None:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Not found.",
    )


@router.api_route("/webhook", methods=_BLOCKED_METHODS)
@router.api_route("/webhook/{path:path}", methods=_BLOCKED_METHODS)
def block_direct_webhook_access(path: str = "") -> None:
    del path
    _blocked_direct_access()


@router.api_route("/n8n", methods=_BLOCKED_METHODS)
@router.api_route("/n8n/{path:path}", methods=_BLOCKED_METHODS)
def block_direct_n8n_access(path: str = "") -> None:
    del path
    _blocked_direct_access()
