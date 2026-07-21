from __future__ import annotations

from app.core import error_constants as errors
from app.core.exceptions import AppException


def validate_openai_api_key(
    api_key: str | None,
    *,
    role: str,
    model: str,
) -> str:
    normalized = (api_key or "").strip()
    if not normalized:
        raise AppException(
            errors.OPENAI_API_KEY_MISSING,
            detail={
                "provider": "openai",
                "role": role,
                "model": model,
            },
        )

    try:
        normalized.encode("ascii")
    except UnicodeEncodeError as exc:
        raise AppException(
            errors.OPENAI_AUTHENTICATION_FAILED,
            detail={
                "provider": "openai",
                "role": role,
                "model": model,
                "reason": "api_key_must_be_ascii",
            },
        ) from exc

    return normalized
