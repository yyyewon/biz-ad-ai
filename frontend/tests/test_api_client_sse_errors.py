import json

from core import api_client


class FakeSseResponse:
    headers = {"content-type": "text/event-stream; charset=utf-8"}

    def __init__(self, events: list[dict]):
        self._events = events

    def iter_lines(self, decode_unicode=True):
        for event in self._events:
            yield "data: " + json.dumps(event)
            yield ""


def test_generate_ad_returns_common_sse_error_without_waiting_for_more_events(monkeypatch):
    response = FakeSseResponse(
        [
            {
                "event": "error",
                "data": {
                    "success": False,
                    "data": None,
                    "error": {
                        "code": "OPENAI_AUTHENTICATION_FAILED",
                        "message": "AI 서비스 인증 또는 접근 권한을 확인할 수 없습니다.",
                        "detail": None,
                    },
                },
            }
        ]
    )
    monkeypatch.setattr(
        api_client,
        "_post_generate_sse",
        lambda files, payload, cookies: response,
    )

    result = api_client.generate_ad(
        store_name="테스트가게",
        menu_name="김밥",
        purpose="홍보",
        image_bytes=b"image",
        image_name="image.png",
        food="밥",
        tone="친근한",
        image_request="",
        llm_request="",
    )

    assert result == {
        "ok": False,
        "error": "AI 서비스 인증 또는 접근 권한을 확인할 수 없습니다.",
        "error_code": "OPENAI_AUTHENTICATION_FAILED",
    }
