from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.exceptions import AppException, register_exception_handlers


# 예외처리 테스트 전용 FastAPI 앱입니다.
# 실제 운영 API에 실패 테스트용 endpoint를 추가하지 않기 위해,
# 테스트 파일 안에서만 임시 앱을 생성합니다.
exception_app = FastAPI()

# 공통 예외 처리 핸들러를 테스트 앱에 등록합니다.
register_exception_handlers(exception_app)


class SampleRequest(BaseModel):
    """
    validation error 테스트용 요청 스키마입니다.

    count는 int 타입이어야 하므로,
    문자열을 넣으면 FastAPI의 RequestValidationError가 발생합니다.
    """

    name: str
    count: int


@exception_app.get("/app-exception")
async def raise_app_exception():
    """
    AppException 테스트용 endpoint입니다.

    프로젝트에서 의도적으로 발생시키는 에러가
    공통 에러 응답 형식으로 변환되는지 확인합니다.
    """

    raise AppException(
        code="TEST_APP_EXCEPTION",
        message="테스트용 AppException입니다.",
        status_code=400,
        detail={"reason": "intentional test error"},
    )


@exception_app.post("/validation-error")
async def raise_validation_error(request: SampleRequest):
    """
    validation error 테스트용 endpoint입니다.

    잘못된 요청 body를 보내면 이 함수 내부까지 오기 전에
    FastAPI가 RequestValidationError를 발생시킵니다.
    """

    return {"message": "ok", "request": request.model_dump()}


@exception_app.get("/unhandled-exception")
async def raise_unhandled_exception():
    """
    예상하지 못한 서버 오류 테스트용 endpoint입니다.

    ZeroDivisionError를 일부러 발생시켜
    general_exception_handler가 500 응답으로 변환하는지 확인합니다.
    """

    result = 1 / 0
    return {"result": result}


# raise_server_exceptions=False 설정이 중요합니다.
# 이 옵션이 없으면 테스트 중 서버 내부 예외가 응답으로 변환되기 전에
# pytest 쪽으로 그대로 다시 raise될 수 있습니다.
client = TestClient(exception_app, raise_server_exceptions=False)


def test_app_exception_handler():
    """
    AppException이 공통 실패 응답 형식으로 변환되는지 테스트합니다.
    """

    response = client.get("/app-exception")

    assert response.status_code == 400

    body = response.json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "TEST_APP_EXCEPTION"
    assert body["error"]["message"] == "테스트용 AppException입니다."
    assert body["error"]["detail"] == {"reason": "intentional test error"}


def test_validation_exception_handler():
    """
    요청 데이터 타입이 잘못됐을 때
    VALIDATION_ERROR 응답이 반환되는지 테스트합니다.
    """

    response = client.post(
        "/validation-error",
        json={
            "name": "test",
            "count": "not-int",
        },
    )

    assert response.status_code == 422

    body = response.json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "요청 데이터 형식이 올바르지 않습니다."
    assert body["error"]["detail"] is not None


def test_http_exception_handler_404():
    """
    존재하지 않는 URL에 접근했을 때
    HTTP_404 응답이 반환되는지 테스트합니다.
    """

    response = client.get("/not-found")

    assert response.status_code == 404

    body = response.json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "HTTP_404"
    assert body["error"]["message"] == "Not Found"


def test_general_exception_handler():
    """
    예상하지 못한 서버 내부 오류가 발생했을 때
    INTERNAL_SERVER_ERROR 응답이 반환되는지 테스트합니다.
    """

    response = client.get("/unhandled-exception")

    assert response.status_code == 500

    body = response.json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert body["error"]["message"] == "서버 내부 오류가 발생했습니다."
    assert body["error"]["detail"] is None
