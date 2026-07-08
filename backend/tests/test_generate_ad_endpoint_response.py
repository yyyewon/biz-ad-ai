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
            request_note="",
            moods="cozy,fresh",
            tone="친근한",
            image=None,
            current_user=None,
        )

        assert response["success"] is True
        assert response["error"] is None
        assert response["data"]["caption"] == "테스트 광고 문구"
        assert response["data"]["images"] == []
        assert response["data"]["partial_success"] is False

    import asyncio

    asyncio.run(run_test())
