import base64
import io
from types import SimpleNamespace

from PIL import Image

from components import step_upload
from components import ui_kit
from components.ui_kit import _preview_data_uri
from core import api_client


class _SessionState(dict):
    def __getattr__(self, name):
        return self[name]


class _Response:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"success": True, "data": {"predicted_food": "커피, 음료"}}


def test_food_classification_uses_cold_start_timeout(monkeypatch):
    captured = {}

    def fake_post(*args, **kwargs):
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr(api_client.requests, "post", fake_post)

    result = api_client.classify_food(b"image", "menu.jpg")

    assert result == {"ok": True, "predicted_food": "커피, 음료"}
    assert captured["timeout"] == 60


def test_failed_classification_is_not_marked_complete(monkeypatch):
    fake_st = SimpleNamespace(
        session_state=_SessionState(upload={"food": None}),
    )
    monkeypatch.setattr(step_upload, "st", fake_st)

    selected = step_upload._store_classification_result(
        "file-1",
        {"ok": False, "error": "분류 시간 초과", "error_code": "NETWORK_DISCONNECTED"},
    )

    assert selected is None
    assert "_classified_file_id" not in fake_st.session_state
    assert fake_st.session_state["_food_classification"] == {
        "file_id": "file-1",
        "status": "error",
        "message": "분류 시간 초과",
    }


def test_successful_classification_updates_food_selection(monkeypatch):
    fake_st = SimpleNamespace(
        session_state=_SessionState(upload={"food": None}),
    )
    monkeypatch.setattr(step_upload, "st", fake_st)

    selected = step_upload._store_classification_result(
        "file-2",
        {"ok": True, "predicted_food": "빵, 디저트, 케이크"},
    )

    assert selected == "빵, 디저트, 케이크"
    assert fake_st.session_state["_classified_file_id"] == "file-2"
    assert fake_st.session_state["upload_food_type"] == selected
    assert fake_st.session_state["upload"]["food"] == selected


def test_preview_data_uri_downscales_large_png():
    source = Image.effect_noise((1024, 1536), 100).convert("RGB")
    source_buffer = io.BytesIO()
    source.save(source_buffer, format="PNG")
    source_bytes = source_buffer.getvalue()

    data_uri = _preview_data_uri(
        source_bytes,
        max_size=(320, 400),
        quality=72,
    )

    assert data_uri is not None
    prefix, encoded = data_uri.split(",", 1)
    preview_bytes = base64.b64decode(encoded)
    assert prefix == "data:image/jpeg;base64"
    assert len(preview_bytes) < len(source_bytes) / 4
    with Image.open(io.BytesIO(preview_bytes)) as preview:
        assert preview.width <= 320
        assert preview.height <= 400


def test_preview_widgets_keep_each_websocket_html_message_under_one_megabyte(monkeypatch):
    images = []
    for size in ((1024, 1024), (1024, 1536), (1024, 1536)):
        source = Image.effect_noise(size, 100).convert("RGB")
        source_buffer = io.BytesIO()
        source.save(source_buffer, format="PNG")
        images.append(source_buffer.getvalue())

    messages = []
    monkeypatch.setattr(
        ui_kit,
        "st",
        SimpleNamespace(markdown=lambda html, **kwargs: messages.append(html)),
    )

    ui_kit.phone_preview("새벽", "치즈케이크", images[2])
    ui_kit.feed_grid(images)

    assert len(messages) == 2
    assert max(len(message.encode("utf-8")) for message in messages) < 1_000_000
