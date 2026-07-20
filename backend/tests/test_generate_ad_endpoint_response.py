import asyncio
import json

from app.api.v1.endpoints import generate_ad


class DummyLimiterSlot:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class DummyLimiter:
    def slot(self):
        return DummyLimiterSlot()


def test_generate_ad_endpoint_wraps_pipeline_result_with_success_response(monkeypatch):
    async def run_test():
        monkeypatch.setattr(generate_ad, "generation_limiter", DummyLimiter())

        async def fake_run_generate_pipeline(**kwargs):
            return {
                "caption": "테스트 광고 문구",
                "images": [],
                "partial_success": False,
                "warnings": [],
                "image_generation_success": None,
            }

        monkeypatch.setattr(
            generate_ad,
            "run_generate_pipeline",
            fake_run_generate_pipeline,
        )

        response = await generate_ad.generate_ad_endpoint(
            store_name="테스트가게",
            menu_name="김밥",
            purpose="홍보",
            food="국, 찌개",
            tone="친근한",
            image_request="",
            llm_request="",
            image=None,
            current_user=None,
        )

        # 엔드포인트는 SSE StreamingResponse를 반환한다.
        # _event_stream()의 각 청크를 수집해 result 이벤트를 확인한다.
        assert hasattr(response, "body_iterator") or hasattr(response, "__call__")

        # 비동기 제너레이터에서 이벤트 수집
        chunks: list[str] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk if isinstance(chunk, str) else chunk.decode())

        raw = "".join(chunks)
        events = []
        for line in raw.split("\n"):
            line = line.strip()
            if line.startswith("data:"):
                payload_str = line[len("data:"):].strip()
                if payload_str:
                    events.append(json.loads(payload_str))

        result_event = next((e for e in events if e.get("event") == "result"), None)
        assert result_event is not None, f"No result event found. Events: {events}"

        data = result_event["data"]
        assert data["caption"] == "테스트 광고 문구"
        assert data["images"] == []
        assert data["partial_success"] is False

    asyncio.run(run_test())


def test_generate_ad_endpoint_updates_business_info_when_request_is_accepted(monkeypatch):
    async def run_test():
        calls: list[tuple] = []

        monkeypatch.setattr(generate_ad, "generation_limiter", DummyLimiter())

        async def allow_quota(_user_id):
            return None

        def fake_update_user_business_info(*, user_id, store_name, store_location):
            calls.append(("persist", user_id, store_name, store_location))

        async def fake_run_generate_pipeline(**kwargs):
            calls.append(("pipeline",))
            return {
                "caption": "테스트 광고 문구",
                "images": [],
                "partial_success": False,
                "warnings": [],
                "image_generation_success": None,
            }

        monkeypatch.setattr(generate_ad, "ensure_daily_quota_available_async", allow_quota)
        monkeypatch.setattr(
            generate_ad,
            "update_user_business_info",
            fake_update_user_business_info,
        )
        monkeypatch.setattr(generate_ad, "run_generate_pipeline", fake_run_generate_pipeline)

        response = await generate_ad.generate_ad_endpoint(
            store_name=" 수정된 가게 ",
            menu_name="김밥",
            purpose="홍보",
            food="덮밥, 볶음, 비빔",
            tone="친근한",
            price="5,000원",
            store_location=" 서울시 강서구 ",
            image_request="",
            llm_request="",
            image=None,
            current_user={"id": 42},
        )

        # StreamingResponse 소비 전, 즉 요청 수락 시점에 먼저 저장되어야 한다.
        assert calls == [("persist", 42, " 수정된 가게 ", " 서울시 강서구 ")]

        async for _ in response.body_iterator:
            pass

        assert calls == [
            ("persist", 42, " 수정된 가게 ", " 서울시 강서구 "),
            ("pipeline",),
        ]

    asyncio.run(run_test())
