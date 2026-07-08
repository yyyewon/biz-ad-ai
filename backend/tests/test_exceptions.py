from app.core import error_constants as errors
from app.core.exceptions import AppException


def test_app_exception_accepts_error_spec():
    exc = AppException(
        errors.MODEL_CONFIG_NOT_FOUND,
        detail={"path": "backend/config/model.yaml"},
    )

    assert exc.code == "MODEL_CONFIG_NOT_FOUND"
    assert exc.message == "모델 설정 파일을 찾을 수 없습니다."
    assert exc.status_code == 500
    assert exc.detail == {"path": "backend/config/model.yaml"}


def test_app_exception_accepts_legacy_arguments():
    exc = AppException(
        code="LEGACY_ERROR",
        message="기존 방식 에러입니다.",
        status_code=400,
        detail={"field": "name"},
    )

    assert exc.code == "LEGACY_ERROR"
    assert exc.message == "기존 방식 에러입니다."
    assert exc.status_code == 400
    assert exc.detail == {"field": "name"}


def test_app_exception_can_override_message_and_status_code():
    exc = AppException(
        errors.MODEL_CONFIG_NOT_FOUND,
        message="커스텀 메시지",
        status_code=503,
    )

    assert exc.code == "MODEL_CONFIG_NOT_FOUND"
    assert exc.message == "커스텀 메시지"
    assert exc.status_code == 503