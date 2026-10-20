class DomainError(Exception):
    """Base class for expected domain failures."""


class ResourceNotFoundError(DomainError):
    pass


class UnauthorizedError(DomainError):
    pass


class ForbiddenError(DomainError):
    pass


class ConflictError(DomainError):
    pass


class ProviderNotConfiguredError(DomainError):
    pass


class ProviderBudgetExceededError(DomainError):
    pass


class TransientProviderError(DomainError):
    pass


class PermanentProviderError(DomainError):
    pass


class ProviderAuthenticationError(PermanentProviderError):
    pass


class SemanticProviderError(DomainError):
    pass


class InferenceOutputError(SemanticProviderError):
    """Safe validation reason with usage retained from a completed provider response."""

    def __init__(self, message: str, usage: dict[str, int] | None, provider: str, model: str) -> None:
        super().__init__(message)
        self.usage = usage
        self.provider = provider
        self.model = model


class WorkflowInterruptError(DomainError):
    def __init__(self, thread_id: str, payload: dict[str, object]) -> None:
        super().__init__("workflow waiting for user input")
        self.thread_id = thread_id
        self.payload = payload


class ClarificationCancelledError(DomainError):
    pass
