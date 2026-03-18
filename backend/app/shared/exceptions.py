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


class ConfigMissError(AppError):
    """Raised when a required config is missing from all sources (DB + YAML).

    CFG-01: deterministic failure for required config miss.
    Callers must not catch this silently — it indicates broken seed data
    or missing migration.
    """

    status_code = 500

    def __init__(self, vertical: str, config_type: str):
        self.vertical = vertical
        self.config_type = config_type
        super().__init__(
            f"Required config missing: ({vertical}, {config_type}). "
            f"Check migration 0004 seed data."
        )

