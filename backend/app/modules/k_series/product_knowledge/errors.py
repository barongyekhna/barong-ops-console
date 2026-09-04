"""Module-local errors for the K Product Knowledge skeleton."""

from fastapi import HTTPException, status


class KProductKnowledgeError(Exception):
    code = "KProductKnowledgeError"
    status_code = status.HTTP_400_BAD_REQUEST
    default_message = "K Product Knowledge error."

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)

    def to_http_exception(self) -> HTTPException:
        return HTTPException(
            status_code=self.status_code,
            detail={
                "code": self.code,
                "message": self.message,
            },
        )


class KProductKnowledgeDisabledError(KProductKnowledgeError):
    code = "KFeatureDisabled"
    status_code = status.HTTP_404_NOT_FOUND
    default_message = "K Product Knowledge API is disabled."


class KProductNotFoundError(KProductKnowledgeError):
    code = "KProductNotFound"
    status_code = status.HTTP_404_NOT_FOUND
    default_message = "K Product Knowledge record was not found."


class KScopeNotReadyError(KProductKnowledgeError):
    code = "KScopeNotReady"
    status_code = status.HTTP_403_FORBIDDEN
    default_message = "K formal scope adapter is not ready."


class KValidationError(KProductKnowledgeError):
    code = "KValidationError"
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_message = "K Product Knowledge payload is invalid."


class KConflictError(KProductKnowledgeError):
    code = "KConflict"
    status_code = status.HTTP_409_CONFLICT
    default_message = "K Product Knowledge data conflicts with existing data."


class KInvalidStateError(KProductKnowledgeError):
    code = "KInvalidState"
    status_code = status.HTTP_409_CONFLICT
    default_message = "K Product Knowledge state transition is not allowed."


class KProductTypeVariantsMismatchError(KConflictError):
    """产品类型与现有变体行对不上(多变体却只有 default 行 / 单产品却有多行)。

    2026-09-04 起 PATCH /products/{id} 不再默默接受这种半残状态——
    切类型请走 PUT /products/{id}/variants,由服务端一起收敛变体行。
    """

    code = "PRODUCT_TYPE_VARIANTS_MISMATCH"
    default_message = "产品类型与变体行不一致,请在「基础档案」里保存变体来切换类型。"


class KVariantHasMediaError(KConflictError):
    """要删的变体还绑着图片。fail-closed:让人先在图片管理里删图,绝不留孤儿。"""

    code = "VARIANT_HAS_MEDIA"
    default_message = "该变体还绑着图片,先删图再删变体。"
