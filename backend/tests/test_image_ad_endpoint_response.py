import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.schemas.image_ad import ImageAdResponse
from app.utils.image_bytes import encode_image_bytes_to_base64, pil_image_to_png_bytes

client = TestClient(app)


class DummyLimiterSlot:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class DummyLimiter:
    def slot(self):
        return DummyLimiterSlot()


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def _sample_png_base64(color: str = "white") -> str:
    image = Image.new("RGB", (16, 16), color)
    return encode_image_bytes_to_base64(pil_image_to_png_bytes(image))


def _override_login_user(user_id: int = 1):
    from app.api.v1.endpoints import dev_apis as image_ad_endpoint

    app.dependency_overrides[image_ad_endpoint.get_current_user] = lambda: {
        "id": user_id,
        "provider": "test",
        "email": "test@example.com",
        "nickname": "테스트유저",
    }


def test_image_ad_endpoint_returns_common_success_response(monkeypatch):
    from app.api.v1.endpoints import dev_apis as image_ad_endpoint

    _override_login_user(user_id=123)

    input_b64 = _sample_png_base64("white")
    output_b64 = _sample_png_base64("green")

    calls = {
        "quota_user_ids": [],
        "payload": None,
        "source_image_bytes_len": 0,
    }

    async def fake_check_and_increment_daily_usage_async(user_id: int):
        calls["quota_user_ids"].append(user_id)
        return 1

    async def fake_generate_image_ads(*, payload, source_image_bytes, seed=None):
        calls["payload"] = payload
        calls["source_image_bytes_len"] = len(source_image_bytes)

        return ImageAdResponse(
            request_id="img-test",
            mood=payload.mood,
            prompt_used="poster prompt",
            num_images=1,
            latency_ms=100,
            generation_mode=payload.generation_mode,
            stage_latencies_ms={
                "food_generation_ms": 0,
                "poster_generation_ms": 100,
                "total_ms": 100,
            },
            images=[output_b64],
            poster_images=[output_b64],
            applied_moods=[payload.mood],
        )

    monkeypatch.setattr(image_ad_endpoint, "generation_limiter", DummyLimiter())
    monkeypatch.setattr(
        image_ad_endpoint,
        "check_and_increment_daily_usage_async",
        fake_check_and_increment_daily_usage_async,
    )
    monkeypatch.setattr(
        image_ad_endpoint,
        "generate_image_ads",
        fake_generate_image_ads,
    )

    response = client.post(
        "/api/v1/dev/ad/image",
        json={
            "input_image_base64": input_b64,
            "store_name": "만월",
            "menu_name": "데몬헌터스 케이크",
            "mood": "cozy",
            "num_images": 1,
            "generation_mode": "direct_poster",
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["success"] is True
    assert body["error"] is None
    assert body["data"]["request_id"] == "img-test"
    assert body["data"]["images"] == [output_b64]
    assert body["data"]["poster_images"] == [output_b64]

    assert calls["quota_user_ids"] == [123]
    assert calls["payload"].input_image_base64 == input_b64
    assert calls["payload"].input_image_path is None
    assert calls["payload"].image_path is None
    assert calls["source_image_bytes_len"] > 0


def test_image_ad_endpoint_requires_login():
    input_b64 = _sample_png_base64("white")

    response = client.post(
        "/api/v1/dev/ad/image",
        json={
            "input_image_base64": input_b64,
            "store_name": "만월",
            "menu_name": "데몬헌터스 케이크",
            "mood": "cozy",
            "num_images": 1,
            "generation_mode": "direct_poster",
        },
    )

    body = response.json()

    assert response.status_code == 401
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "UNAUTHORIZED"


def test_image_ad_endpoint_requires_input_image_base64():
    _override_login_user(user_id=123)

    response = client.post(
        "/api/v1/dev/ad/image",
        json={
            "store_name": "만월",
            "menu_name": "데몬헌터스 케이크",
            "mood": "cozy",
            "num_images": 1,
            "generation_mode": "direct_poster",
        },
    )

    body = response.json()

    assert response.status_code == 400
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "EMPTY_IMAGE_FILE"


def test_image_ad_endpoint_rejects_invalid_base64():
    _override_login_user(user_id=123)

    response = client.post(
        "/api/v1/dev/ad/image",
        json={
            "input_image_base64": "not-valid-base64@@@",
            "store_name": "만월",
            "menu_name": "데몬헌터스 케이크",
            "mood": "cozy",
            "num_images": 1,
            "generation_mode": "direct_poster",
        },
    )

    body = response.json()

    assert response.status_code == 400
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "INVALID_IMAGE_FILE"


class TrackingLimiterSlot:
    def __init__(self, calls):
        self.calls = calls

    async def __aenter__(self):
        self.calls["entered"] += 1
        return None

    async def __aexit__(self, exc_type, exc, traceback):
        self.calls["exited"] += 1
        return False


class TrackingLimiter:
    def __init__(self):
        self.calls = {
            "entered": 0,
            "exited": 0,
        }

    def slot(self):
        return TrackingLimiterSlot(self.calls)


class RejectingLimiterSlot:
    async def __aenter__(self):
        from app.core.exceptions import AppException

        raise AppException(
            code="GENERATION_BUSY",
            message="현재 생성 요청이 많아 처리할 수 없어요. 잠시 후 다시 시도해 주세요.",
            status_code=429,
            detail={"max_concurrent": 1},
        )

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class RejectingLimiter:
    def slot(self):
        return RejectingLimiterSlot()


def test_image_ad_endpoint_returns_quota_exceeded_when_daily_limit_exceeded(monkeypatch):
    from app.api.v1.endpoints import dev_apis as image_ad_endpoint
    from app.core.exceptions import AppException

    _override_login_user(user_id=123)

    input_b64 = _sample_png_base64("white")

    calls = {
        "quota_called": 0,
        "generate_called": 0,
    }

    async def fake_quota_exceeded(user_id: int):
        calls["quota_called"] += 1

        raise AppException(
            code="DAILY_LIMIT_EXCEEDED",
            message="하루 생성 가능 횟수(3회)를 모두 사용했어요. 내일 다시 시도해 주세요.",
            status_code=429,
            detail={
                "daily_limit": 3,
                "used": 3,
            },
        )

    async def fake_generate_image_ads(*, payload, source_image_bytes, seed=None):
        calls["generate_called"] += 1
        raise AssertionError("quota 초과 시 generate_image_ads가 호출되면 안 됩니다.")

    monkeypatch.setattr(image_ad_endpoint, "generation_limiter", DummyLimiter())
    monkeypatch.setattr(
        image_ad_endpoint,
        "check_and_increment_daily_usage_async",
        fake_quota_exceeded,
    )
    monkeypatch.setattr(
        image_ad_endpoint,
        "generate_image_ads",
        fake_generate_image_ads,
    )

    response = client.post(
        "/api/v1/dev/ad/image",
        json={
            "input_image_base64": input_b64,
            "store_name": "만월",
            "menu_name": "데몬헌터스 케이크",
            "mood": "cozy",
            "num_images": 1,
            "generation_mode": "direct_poster",
        },
    )

    body = response.json()

    assert response.status_code == 429
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "DAILY_LIMIT_EXCEEDED"
    assert body["error"]["detail"]["daily_limit"] == 3
    assert body["error"]["detail"]["used"] == 3

    assert calls["quota_called"] == 1
    assert calls["generate_called"] == 0


def test_image_ad_endpoint_uses_generation_limiter(monkeypatch):
    from app.api.v1.endpoints import dev_apis as image_ad_endpoint

    _override_login_user(user_id=123)

    input_b64 = _sample_png_base64("white")
    output_b64 = _sample_png_base64("green")

    limiter = TrackingLimiter()

    calls = {
        "quota_called": 0,
        "generate_called": 0,
    }

    async def fake_check_and_increment_daily_usage_async(user_id: int):
        calls["quota_called"] += 1
        return 1

    async def fake_generate_image_ads(*, payload, source_image_bytes, seed=None):
        calls["generate_called"] += 1

        return ImageAdResponse(
            request_id="img-limiter-test",
            mood=payload.mood,
            prompt_used="poster prompt",
            num_images=1,
            latency_ms=100,
            generation_mode=payload.generation_mode,
            stage_latencies_ms={
                "food_generation_ms": 0,
                "poster_generation_ms": 100,
                "total_ms": 100,
            },
            images=[output_b64],
            poster_images=[output_b64],
            applied_moods=[payload.mood],
        )

    monkeypatch.setattr(image_ad_endpoint, "generation_limiter", limiter)
    monkeypatch.setattr(
        image_ad_endpoint,
        "check_and_increment_daily_usage_async",
        fake_check_and_increment_daily_usage_async,
    )
    monkeypatch.setattr(
        image_ad_endpoint,
        "generate_image_ads",
        fake_generate_image_ads,
    )

    response = client.post(
        "/api/v1/dev/ad/image",
        json={
            "input_image_base64": input_b64,
            "store_name": "만월",
            "menu_name": "데몬헌터스 케이크",
            "mood": "cozy",
            "num_images": 1,
            "generation_mode": "direct_poster",
        },
    )

    body = response.json()

    assert response.status_code == 200
    assert body["success"] is True
    assert body["data"]["request_id"] == "img-limiter-test"

    assert limiter.calls["entered"] == 1
    assert limiter.calls["exited"] == 1
    assert calls["quota_called"] == 1
    assert calls["generate_called"] == 1


def test_image_ad_endpoint_returns_generation_busy_when_limiter_rejects(monkeypatch):
    from app.api.v1.endpoints import dev_apis as image_ad_endpoint

    _override_login_user(user_id=123)

    input_b64 = _sample_png_base64("white")

    calls = {
        "quota_called": 0,
        "generate_called": 0,
    }

    async def fake_check_and_increment_daily_usage_async(user_id: int):
        calls["quota_called"] += 1
        return 1

    async def fake_generate_image_ads(*, payload, source_image_bytes, seed=None):
        calls["generate_called"] += 1
        raise AssertionError("limiter가 막으면 generate_image_ads가 호출되면 안 됩니다.")

    monkeypatch.setattr(image_ad_endpoint, "generation_limiter", RejectingLimiter())
    monkeypatch.setattr(
        image_ad_endpoint,
        "check_and_increment_daily_usage_async",
        fake_check_and_increment_daily_usage_async,
    )
    monkeypatch.setattr(
        image_ad_endpoint,
        "generate_image_ads",
        fake_generate_image_ads,
    )

    response = client.post(
        "/api/v1/dev/ad/image",
        json={
            "input_image_base64": input_b64,
            "store_name": "만월",
            "menu_name": "데몬헌터스 케이크",
            "mood": "cozy",
            "num_images": 1,
            "generation_mode": "direct_poster",
        },
    )

    body = response.json()

    assert response.status_code == 429
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "GENERATION_BUSY"

    assert calls["quota_called"] == 0
    assert calls["generate_called"] == 0


class TrackingLimiterSlot:
    def __init__(self, calls):
        self.calls = calls

    async def __aenter__(self):
        self.calls["entered"] += 1
        return None

    async def __aexit__(self, exc_type, exc, traceback):
        self.calls["exited"] += 1
        return False


class TrackingLimiter:
    def __init__(self):
        self.calls = {
            "entered": 0,
            "exited": 0,
        }

    def slot(self):
        return TrackingLimiterSlot(self.calls)


class RejectingLimiterSlot:
    async def __aenter__(self):
        from app.core.exceptions import AppException

        raise AppException(
            code="GENERATION_BUSY",
            message="현재 생성 요청이 많아 처리할 수 없어요. 잠시 후 다시 시도해 주세요.",
            status_code=429,
            detail={"max_concurrent": 1},
        )

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class RejectingLimiter:
    def slot(self):
        return RejectingLimiterSlot()


def test_image_ad_endpoint_returns_quota_exceeded_when_daily_limit_exceeded(monkeypatch):
    from app.api.v1.endpoints import dev_apis as image_ad_endpoint
    from app.core.exceptions import AppException

    _override_login_user(user_id=123)

    input_b64 = _sample_png_base64("white")

    calls = {
        "quota_called": 0,
        "generate_called": 0,
    }

    async def fake_quota_exceeded(user_id: int):
        calls["quota_called"] += 1

        raise AppException(
            code="DAILY_LIMIT_EXCEEDED",
            message="하루 생성 가능 횟수(3회)를 모두 사용했어요. 내일 다시 시도해 주세요.",
            status_code=429,
            detail={
                "daily_limit": 3,
                "used": 3,
            },
        )

    async def fake_generate_image_ads(*, payload, source_image_bytes, seed=None):
        calls["generate_called"] += 1
        raise AssertionError("quota 초과 시 generate_image_ads가 호출되면 안 됩니다.")

    monkeypatch.setattr(image_ad_endpoint, "generation_limiter", DummyLimiter())
    monkeypatch.setattr(
        image_ad_endpoint,
        "check_and_increment_daily_usage_async",
        fake_quota_exceeded,
    )
    monkeypatch.setattr(
        image_ad_endpoint,
        "generate_image_ads",
        fake_generate_image_ads,
    )

    response = client.post(
        "/api/v1/dev/ad/image",
        json={
            "input_image_base64": input_b64,
            "store_name": "만월",
            "menu_name": "데몬헌터스 케이크",
            "mood": "cozy",
            "num_images": 1,
            "generation_mode": "direct_poster",
        },
    )

    body = response.json()

    assert response.status_code == 429
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "DAILY_LIMIT_EXCEEDED"
    assert body["error"]["detail"]["daily_limit"] == 3
    assert body["error"]["detail"]["used"] == 3

    assert calls["quota_called"] == 1
    assert calls["generate_called"] == 0


def test_image_ad_endpoint_uses_generation_limiter(monkeypatch):
    from app.api.v1.endpoints import dev_apis as image_ad_endpoint

    _override_login_user(user_id=123)

    input_b64 = _sample_png_base64("white")
    output_b64 = _sample_png_base64("green")

    limiter = TrackingLimiter()

    calls = {
        "quota_called": 0,
        "generate_called": 0,
    }

    async def fake_check_and_increment_daily_usage_async(user_id: int):
        calls["quota_called"] += 1
        return 1

    async def fake_generate_image_ads(*, payload, source_image_bytes, seed=None):
        calls["generate_called"] += 1

        return ImageAdResponse(
            request_id="img-limiter-test",
            mood=payload.mood,
            prompt_used="poster prompt",
            num_images=1,
            latency_ms=100,
            generation_mode=payload.generation_mode,
            stage_latencies_ms={
                "food_generation_ms": 0,
                "poster_generation_ms": 100,
                "total_ms": 100,
            },
            images=[output_b64],
            poster_images=[output_b64],
            applied_moods=[payload.mood],
        )

    monkeypatch.setattr(image_ad_endpoint, "generation_limiter", limiter)
    monkeypatch.setattr(
        image_ad_endpoint,
        "check_and_increment_daily_usage_async",
        fake_check_and_increment_daily_usage_async,
    )
    monkeypatch.setattr(
        image_ad_endpoint,
        "generate_image_ads",
        fake_generate_image_ads,
    )

    response = client.post(
        "/api/v1/dev/ad/image",
        json={
            "input_image_base64": input_b64,
            "store_name": "만월",
            "menu_name": "데몬헌터스 케이크",
            "mood": "cozy",
            "num_images": 1,
            "generation_mode": "direct_poster",
        },
    )

    body = response.json()

    assert response.status_code == 200
    assert body["success"] is True
    assert body["data"]["request_id"] == "img-limiter-test"

    assert limiter.calls["entered"] == 1
    assert limiter.calls["exited"] == 1
    assert calls["quota_called"] == 1
    assert calls["generate_called"] == 1


def test_image_ad_endpoint_returns_generation_busy_when_limiter_rejects(monkeypatch):
    from app.api.v1.endpoints import dev_apis as image_ad_endpoint

    _override_login_user(user_id=123)

    input_b64 = _sample_png_base64("white")

    calls = {
        "quota_called": 0,
        "generate_called": 0,
    }

    async def fake_check_and_increment_daily_usage_async(user_id: int):
        calls["quota_called"] += 1
        return 1

    async def fake_generate_image_ads(*, payload, source_image_bytes, seed=None):
        calls["generate_called"] += 1
        raise AssertionError("limiter가 막으면 generate_image_ads가 호출되면 안 됩니다.")

    monkeypatch.setattr(image_ad_endpoint, "generation_limiter", RejectingLimiter())
    monkeypatch.setattr(
        image_ad_endpoint,
        "check_and_increment_daily_usage_async",
        fake_check_and_increment_daily_usage_async,
    )
    monkeypatch.setattr(
        image_ad_endpoint,
        "generate_image_ads",
        fake_generate_image_ads,
    )

    response = client.post(
        "/api/v1/dev/ad/image",
        json={
            "input_image_base64": input_b64,
            "store_name": "만월",
            "menu_name": "데몬헌터스 케이크",
            "mood": "cozy",
            "num_images": 1,
            "generation_mode": "direct_poster",
        },
    )

    body = response.json()

    assert response.status_code == 429
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "GENERATION_BUSY"

    assert calls["quota_called"] == 0
    assert calls["generate_called"] == 0
