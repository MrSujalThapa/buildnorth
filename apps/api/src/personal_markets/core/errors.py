class DomainError(Exception):
    """Base class for expected domain failures."""


class ResourceNotFoundError(DomainError):
    pass


class ProviderNotConfiguredError(DomainError):
    pass


class ProviderBudgetExceededError(DomainError):
    pass


class TransientProviderError(DomainError):
    pass


class PermanentProviderError(DomainError):
    pass


class SemanticProviderError(DomainError):
    pass


class WorkflowInterruptError(DomainError):
    def __init__(self, thread_id: str, payload: dict[str, object]) -> None:
        super().__init__("workflow waiting for user input")
        self.thread_id = thread_id
        self.payload = payload


class ClarificationCancelledError(DomainError):
    pass
