from fastapi.testclient import TestClient

from app.api.v1.endpoints import business_info
from app.core.deps import get_current_user
from app.main import app


client = TestClient(app)


def test_business_info_endpoint_reads_form_body_and_updates_user(monkeypatch):
    calls: list[dict] = []

    def fake_update_user_business_info(**kwargs):
        calls.append(kwargs)

    app.dependency_overrides[get_current_user] = lambda: {"id": 7}
    monkeypatch.setattr(
        business_info,
        "update_user_business_info",
        fake_update_user_business_info,
    )

    try:
        response = client.post(
            "/api/v1/auth/business-info",
            data={
                "store_name": "  온기식당  ",
                "store_location": "  서울시 강서구  ",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert calls == [
        {
            "user_id": 7,
            "store_name": "온기식당",
            "store_location": "서울시 강서구",
        }
    ]
    assert response.json()["data"] == {
        "store_name": "온기식당",
        "store_location": "서울시 강서구",
    }
