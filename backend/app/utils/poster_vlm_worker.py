"""
포스터 VLM GPU 워커 — GPTQ VRAM을 프로세스 종료 시 완전히 회수하기 위해
별도 subprocess에서 실행한다.

프로토콜 (stdin JSON → stdout JSON):
  입력: {"settings": {...}, "images": [{"width": int, "height": int, "png_b64": str}, ...]}
  출력: {"ok": true, "results": [{"ok": true, "raw_text": str} | {"ok": false, "error": str}, ...]}
        또는 {"ok": false, "error": str}
"""

from __future__ import annotations

import base64
import io
import json
import sys

from PIL import Image


def _read_request() -> dict:
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict):
        raise ValueError("요청 본문은 JSON 객체여야 합니다.")
    return payload


def _decode_image(entry: dict) -> Image.Image:
    png_b64 = entry.get("png_b64")
    if not isinstance(png_b64, str) or not png_b64:
        raise ValueError("image.png_b64 필드가 필요합니다.")
    raw = base64.b64decode(png_b64)
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    expected = (entry.get("width"), entry.get("height"))
    if expected[0] and expected[1] and image.size != expected:
        image = image.resize((int(expected[0]), int(expected[1])), Image.Resampling.LANCZOS)
    return image


def run_worker(payload: dict) -> dict:
    settings = payload.get("settings")
    images_payload = payload.get("images")
    if not isinstance(settings, dict):
        return {"ok": False, "error": "settings는 객체여야 합니다."}
    if not isinstance(images_payload, list):
        return {"ok": False, "error": "images는 배열이어야 합니다."}

    from app.utils.poster_vlm import load_vlm_model_fresh, run_vlm_inference_with_model

    model_config = {"settings": settings}
    model, processor = load_vlm_model_fresh(model_config)

    results: list[dict] = []
    try:
        for entry in images_payload:
            if not isinstance(entry, dict):
                results.append({"ok": False, "error": "이미지 항목 형식이 올바르지 않습니다."})
                continue
            try:
                image = _decode_image(entry)
                raw_text = run_vlm_inference_with_model(
                    image,
                    model=model,
                    processor=processor,
                    model_config=model_config,
                )
                results.append({"ok": True, "raw_text": raw_text})
            except Exception as exc:
                results.append({"ok": False, "error": str(exc)})
    finally:
        del model, processor
        try:
            import gc

            gc.collect()
            import torch

            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
        except Exception:
            pass

    return {"ok": True, "results": results}


def main() -> int:
    try:
        payload = _read_request()
        response = run_worker(payload)
    except Exception as exc:
        response = {"ok": False, "error": str(exc)}
    json.dump(response, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    sys.stdout.flush()
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
