from backend.app.schemas.common import error_response, success_response


def test_success_response():
    """
    성공 응답 helper 테스트입니다.
    """

    response = success_response(data={"message": "ok"})

    assert response["success"] is True
    assert response["data"] == {"message": "ok"}
    assert response["error"] is None


def test_error_response():
    """
    실패 응답 helper 테스트입니다.
    """

    response = error_response(
        code="TEST_ERROR",
        message="테스트 에러입니다.",
        detail={"field": "name"},
    )

    assert response["success"] is False
    assert response["data"] is None
    assert response["error"]["code"] == "TEST_ERROR"
    assert response["error"]["message"] == "테스트 에러입니다."
    assert response["error"]["detail"] == {"field": "name"}
