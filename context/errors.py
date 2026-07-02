class ExternalServiceError(Exception):
    def __init__(self, provider: str, operation: str, error: object):
        self.provider = provider
        self.operation = operation
        super().__init__(f"{provider} {operation} failed: {error}")


def log_external_failure(provider: str, operation: str, error: object) -> str:
    message = f"{provider} {operation} failed: {error}"
    print(f"[External API] {message}")
    return message
