from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AppError(Exception):
    error_code: str
    message: str
    detail: str | None = None

    def __str__(self) -> str:
        if self.detail:
            return f"{self.message} ({self.error_code}): {self.detail}"
        return f"{self.message} ({self.error_code})"


def ensure_app_error(
    exc: Exception,
    *,
    default_code: str,
    default_message: str,
) -> AppError:
    if isinstance(exc, AppError):
        return exc
    return AppError(
        error_code=default_code,
        message=default_message,
        detail=str(exc),
    )
