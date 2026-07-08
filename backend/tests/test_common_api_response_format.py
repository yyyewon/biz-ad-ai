from app.schemas.common import error_response, success_response


def test_success_response_format():
    response = success_response(data={"caption": "테스트 문구"})

    assert response == {
        "success": True,
        "data": {"caption": "테스트 문구"},
        "error": None,
    }


def test_error_response_format():
    response = error_response(
        code="TEST_ERROR",
        message="테스트 에러입니다.",
        detail={"field": "value"},
    )

    assert response == {
        "success": False,
        "data": None,
        "error": {
            "code": "TEST_ERROR",
            "message": "테스트 에러입니다.",
            "detail": {"field": "value"},
        },
    }


def test_endpoint_success_payload_should_be_nested_under_data():
    pipeline_result = {
        "caption": "광고 문구",
        "images": [],
        "partial_success": False,
        "warnings": [],
        "image_generation_success": None,
    }

    response = success_response(data=pipeline_result)

    assert response["success"] is True
    assert response["error"] is None
    assert response["data"]["caption"] == "광고 문구"
    assert response["data"]["images"] == []
    assert response["data"]["partial_success"] is False
