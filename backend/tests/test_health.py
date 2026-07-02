from fastapi.testclient import TestClient

from app.main import app


# FastAPI 앱을 테스트하기 위한 클라이언트입니다.
# 실제 서버를 띄우지 않고 API 요청/응답을 테스트할 수 있습니다.
client = TestClient(app)


def test_root():
    """
    루트 endpoint 테스트입니다.

    확인 항목:
    - HTTP 200 응답 여부
    - 서버 이름 반환 여부
    - 서버 실행 상태 반환 여부
    - Swagger 문서 경로 반환 여부
    """

    response = client.get("/")

    assert response.status_code == 200

    body = response.json()
    assert body["service"] == "biz-ad-ai-backend"
    assert body["status"] == "running"
    assert body["docs"] == "/docs"


def test_health_check():
    """
    Health Check API 테스트입니다.

    확인 항목:
    - HTTP 200 응답 여부
    - 공통 응답 형식 success/data/error 유지 여부
    - 서버 상태값이 ok인지 확인
    - timestamp가 응답에 포함되는지 확인
    """

    response = client.get("/api/v1/health")

    assert response.status_code == 200

    body = response.json()
    assert body["success"] is True
    assert body["error"] is None
    assert body["data"]["status"] == "ok"
    assert body["data"]["service"] == "biz-ad-ai-backend"
    assert "timestamp" in body["data"]
