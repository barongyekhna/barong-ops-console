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
