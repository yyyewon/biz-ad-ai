from typing import Any

from pydantic import BaseModel, Field


class ErrorInfo(BaseModel):
    """
    API 에러 응답에 사용되는 공통 에러 정보입니다.

    code:
        프론트엔드에서 분기 처리할 수 있는 에러 코드입니다.
        예: VALIDATION_ERROR, INTERNAL_SERVER_ERROR

    message:
        사용자 또는 개발자가 확인할 수 있는 에러 메시지입니다.

    detail:
        디버깅에 필요한 추가 정보입니다.
        운영 환경에서는 민감한 정보가 들어가지 않도록 주의해야 합니다.
    """

    code: str = Field(..., description="에러 코드")
    message: str = Field(..., description="에러 메시지")
    detail: Any | None = Field(default=None, description="추가 에러 상세 정보")


class APIResponse(BaseModel):
    """
    모든 API에서 공통으로 사용할 응답 형식입니다.

    성공 응답:
    {
        "success": true,
        "data": {...},
        "error": null
    }

    실패 응답:
    {
        "success": false,
        "data": null,
        "error": {...}
    }
    """

    success: bool = Field(..., description="API 처리 성공 여부")
    data: Any | None = Field(default=None, description="성공 시 응답 데이터")
    error: ErrorInfo | None = Field(default=None, description="실패 시 에러 정보")


def success_response(data: Any | None = None) -> dict[str, Any]:
    """
    성공 응답을 dict 형태로 생성합니다.

    FastAPI endpoint에서 Pydantic 모델을 직접 반환해도 되지만,
    현재 프로젝트에서는 간단하고 일관된 응답 생성을 위해 helper 함수를 사용합니다.
    """

    return {
        "success": True,
        "data": data,
        "error": None,
    }


def error_response(
    code: str,
    message: str,
    detail: Any | None = None,
) -> dict[str, Any]:
    """
    실패 응답을 dict 형태로 생성합니다.

    공통 예외 처리 함수에서 사용합니다.
    """

    return {
        "success": False,
        "data": None,
        "error": {
            "code": code,
            "message": message,
            "detail": detail,
        },
    }
