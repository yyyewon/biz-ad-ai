from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from loguru import logger

from backend.app.schemas.common import error_response


class AppException(Exception):
    """
    프로젝트 내부에서 의도적으로 발생시키는 공통 예외 클래스입니다.

    사용 예:
        raise AppException(
            code="TEXT_GENERATION_FAILED",
            message="광고 문구 생성에 실패했습니다.",
            status_code=500,
        )
    """

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        detail: Any | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail
        super().__init__(message)


async def app_exception_handler(
    request: Request,
    exc: AppException,
) -> JSONResponse:
    """
    AppException 전용 예외 처리 함수입니다.

    개발자가 의도적으로 발생시킨 예외를 공통 응답 형식으로 변환합니다.
    """

    logger.warning(
        "app_exception | path={} | code={} | message={}",
        request.url.path,
        exc.code,
        exc.message,
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=error_response(
            code=exc.code,
            message=exc.message,
            detail=exc.detail,
        ),
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """
    FastAPI 요청 검증 실패 예외 처리 함수입니다.

    예:
    - 필수 필드 누락
    - 잘못된 타입 입력
    - multipart/form-data 형식 오류
    """

    logger.warning(
        "validation_error | path={} | errors={}",
        request.url.path,
        exc.errors(),
    )

    return JSONResponse(
        status_code=422,
        content=error_response(
            code="VALIDATION_ERROR",
            message="요청 데이터 형식이 올바르지 않습니다.",
            detail=exc.errors(),
        ),
    )


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    """
    FastAPI/Starlette 기본 HTTP 예외 처리 함수입니다.

    예:
    - 존재하지 않는 URL 접근: 404
    - 허용되지 않는 메서드 접근: 405
    """

    logger.warning(
        "http_exception | path={} | status_code={} | detail={}",
        request.url.path,
        exc.status_code,
        exc.detail,
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=error_response(
            code=f"HTTP_{exc.status_code}",
            message=str(exc.detail),
            detail=None,
        ),
    )


async def general_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """
    예상하지 못한 서버 내부 오류 처리 함수입니다.

    실제 에러 내용은 서버 로그에 남기고,
    클라이언트에는 일반화된 메시지만 반환합니다.
    """

    logger.exception(
        "unhandled_exception | path={} | error={}",
        request.url.path,
        str(exc),
    )

    return JSONResponse(
        status_code=500,
        content=error_response(
            code="INTERNAL_SERVER_ERROR",
            message="서버 내부 오류가 발생했습니다.",
            detail=None,
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """
    FastAPI 앱에 공통 예외 처리 함수를 등록합니다.

    main.py에서 앱 생성 후 한 번 호출합니다.
    """

    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)
