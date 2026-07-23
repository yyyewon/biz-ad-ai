import asyncio
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient

from app import main
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
    - 요청 추적용 X-Request-ID 헤더 포함 여부
    """

    response = client.get("/")

    assert response.status_code == 200
    assert "X-Request-ID" in response.headers

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
    - timezone이 Asia/Seoul인지 확인
    - 요청 추적용 X-Request-ID 헤더 포함 여부
    """

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert "X-Request-ID" in response.headers

    body = response.json()
    assert body["success"] is True
    assert body["error"] is None
    assert body["data"]["status"] == "ok"
    assert body["data"]["service"] == "biz-ad-ai-backend"
    assert body["data"]["model_warmup_status"] in {
        "not_started",
        "disabled",
        "warming_up",
        "ready",
        "completed_with_errors",
        "failed",
        "cancelled",
    }
    assert "timestamp" in body["data"]
    assert body["data"]["timezone"] == "Asia/Seoul"


def test_lifespan_does_not_wait_for_model_warmup(monkeypatch):
    """A long model warmup must not delay HTTP server startup."""

    async def run_test():
        warmup_started = asyncio.Event()
        warmup_cancelled = asyncio.Event()
        never_finishes = asyncio.Event()

        async def fake_warm_up_models(test_app):
            warmup_started.set()
            try:
                await never_finishes.wait()
            except asyncio.CancelledError:
                warmup_cancelled.set()
                raise

        monkeypatch.setattr(main, "_warm_up_models", fake_warm_up_models)
        monkeypatch.setattr(main.settings, "model_warmup_enabled", True)

        async with main.lifespan(app):
            await asyncio.wait_for(warmup_started.wait(), timeout=0.5)
            assert app.state.model_warmup_status == "warming_up"
            assert not app.state.model_warmup_task.done()

        assert warmup_cancelled.is_set()

    asyncio.run(run_test())


def test_model_warmup_reports_ready_after_all_stages(monkeypatch):
    async def successful_warmup():
        return True

    monkeypatch.setattr(main, "_warm_up_hf_image_pipeline", successful_warmup)
    monkeypatch.setattr(main, "_warm_up_poster_layout", successful_warmup)
    monkeypatch.setattr(main, "_warm_up_poster_vlm", successful_warmup)
    monkeypatch.setattr(main, "_warm_up_food_classifier", successful_warmup)
    monkeypatch.setattr(main.settings, "warmup_hf_image_enabled", True)
    monkeypatch.setattr(main.settings, "warmup_poster_layout_enabled", True)
    monkeypatch.setattr(main.settings, "warmup_poster_vlm_enabled", True)
    monkeypatch.setattr(main.settings, "warmup_food_classifier_enabled", True)

    asyncio.run(main._warm_up_models(app))

    assert app.state.model_warmup_status == "ready"


def test_lifespan_skips_all_model_loaders_when_warmup_is_disabled(monkeypatch):
    async def run_test():
        called = False

        async def should_not_run(_app):
            nonlocal called
            called = True

        monkeypatch.setattr(main, "_warm_up_models", should_not_run)
        monkeypatch.setattr(main.settings, "model_warmup_enabled", False)

        async with main.lifespan(app):
            assert app.state.model_warmup_status == "disabled"
            assert app.state.model_warmup_task is None

        assert called is False

    asyncio.run(run_test())


def test_model_warmup_honors_per_model_flags(monkeypatch):
    calls: list[str] = []

    def stage(name):
        async def run():
            calls.append(name)
            return True

        return run

    monkeypatch.setattr(main, "_warm_up_hf_image_pipeline", stage("hf_image"))
    monkeypatch.setattr(main, "_warm_up_poster_layout", stage("poster_layout"))
    monkeypatch.setattr(main, "_warm_up_poster_vlm", stage("poster_vlm"))
    monkeypatch.setattr(main, "_warm_up_food_classifier", stage("food_classifier"))
    monkeypatch.setattr(main.settings, "warmup_hf_image_enabled", True)
    monkeypatch.setattr(main.settings, "warmup_poster_layout_enabled", True)
    monkeypatch.setattr(main.settings, "warmup_poster_vlm_enabled", False)
    monkeypatch.setattr(main.settings, "warmup_food_classifier_enabled", False)

    asyncio.run(main._warm_up_models(app))

    assert calls == ["hf_image", "poster_layout"]
    assert app.state.model_warmup_status == "ready"


def test_model_warmup_reports_completed_with_errors(monkeypatch):
    async def successful_warmup():
        return True

    async def failed_warmup():
        return False

    monkeypatch.setattr(main, "_warm_up_hf_image_pipeline", successful_warmup)
    monkeypatch.setattr(main, "_warm_up_poster_layout", failed_warmup)
    monkeypatch.setattr(main.settings, "warmup_hf_image_enabled", True)
    monkeypatch.setattr(main.settings, "warmup_poster_layout_enabled", True)
    monkeypatch.setattr(main.settings, "warmup_poster_vlm_enabled", False)
    monkeypatch.setattr(main.settings, "warmup_food_classifier_enabled", False)

    asyncio.run(main._warm_up_models(app))

    assert app.state.model_warmup_status == "completed_with_errors"


def test_model_warmup_exception_marks_failed_without_escaping(monkeypatch):
    async def unexpected_failure():
        raise RuntimeError("warmup failed")

    monkeypatch.setattr(main, "_warm_up_hf_image_pipeline", unexpected_failure)
    monkeypatch.setattr(main.settings, "warmup_hf_image_enabled", True)
    monkeypatch.setattr(main.settings, "warmup_poster_layout_enabled", False)
    monkeypatch.setattr(main.settings, "warmup_poster_vlm_enabled", False)
    monkeypatch.setattr(main.settings, "warmup_food_classifier_enabled", False)

    asyncio.run(main._warm_up_models(app))

    assert app.state.model_warmup_status == "failed"


def test_provider_factory_does_not_import_heavy_providers_eagerly():
    """HTTP startup must not import PyTorch/HF providers before they are selected."""

    backend_dir = Path(__file__).resolve().parents[1]
    probe = (
        "import sys; "
        "import app.services.providers.factory; "
        "assert 'app.services.providers.hf_image_provider' not in sys.modules; "
        "assert 'app.services.providers.hf_sdxl_lightning_provider' not in sys.modules; "
        "assert 'torch' not in sys.modules"
    )

    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=backend_dir,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
