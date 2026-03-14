from __future__ import annotations


class AppError(Exception):
    """Base error for domain/application exceptions."""

    status_code: int = 500

    def __init__(self, detail: str = "Internal error"):
        self.detail = detail
        super().__init__(detail)


class NotAuthorized(AppError):
    """Raised when actor lacks permissions or fund access."""

    status_code = 403


class NotFound(AppError):
    """Raised when entity is missing or not visible within fund scope."""

    status_code = 404


class ValidationError(AppError):
    """Raised for domain-level validation beyond schema validation."""

    status_code = 422

