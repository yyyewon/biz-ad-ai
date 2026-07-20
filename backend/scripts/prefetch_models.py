"""
컨테이너/VM 시작 시점에 모델 가중치를 미리 다운로드하는 스크립트.

- HF 이미지 생성 프로필: Stable Diffusion prefetch
- 포스터 파이프라인: rembg u2net + (VLM 활성 시) Qwen2-VL GPTQ
"""
from __future__ import annotations

import os
import sys
from typing import Any


def _log(message: str) -> None:
    print(f"[prefetch] {message}", flush=True)


def _hf_profile_active() -> bool:
    """active_profile 의 image_generation provider 가 'hf' 인지 확인."""
    try:
        from app.core.model_config import get_provider_name
    except Exception as exc:
        _log(f"model_config import 실패, provider 판단을 건너뜀: {exc}")
        return False

    try:
        return get_provider_name("image_generation") == "hf"
    except Exception as exc:
        _log(f"image_generation provider 조회 실패: {exc}")
        return False


def _poster_vlm_enabled() -> bool:
    try:
        from app.core.model_config import get_poster_design_model_settings

        return get_poster_design_model_settings() is not None
    except Exception as exc:
        _log(f"poster VLM 설정 조회 실패: {exc}")
        return False


def _resolve_image_model_id() -> str:
    env_model_id = os.getenv("PREFETCH_MODEL_ID", "").strip()
    if env_model_id:
        return env_model_id

    try:
        from app.core.model_config import get_image_generation_settings

        settings = get_image_generation_settings()
        model_id = (settings.get("settings") or {}).get("model_id")
        if isinstance(model_id, str) and model_id.strip():
            return model_id.strip()
    except Exception as exc:
        _log(f"model.yaml 에서 model_id 조회 실패, fallback 사용: {exc}")

    return "stabilityai/stable-diffusion-3.5-medium"


def _resolve_poster_vlm_model_id() -> str | None:
    try:
        from app.core.model_config import get_poster_design_model_settings

        settings = get_poster_design_model_settings()
        if not settings:
            return None
        model_id = (settings.get("settings") or {}).get("model_id")
        if isinstance(model_id, str) and model_id.strip():
            return model_id.strip()
    except Exception as exc:
        _log(f"poster VLM model_id 조회 실패: {exc}")
    return None


def _prefetch_diffusion_model(model_id: str, hf_token: str) -> None:
    try:
        import torch
        from diffusers import StableDiffusion3Pipeline
    except Exception as exc:
        _log(f"torch/diffusers import 실패, diffusion 모델 prefetch 생략: {exc}")
        return

    _log(f"diffusion 모델 다운로드 시작 | model_id={model_id}")
    dtype: Any = torch.bfloat16
    if not _dtype_available(torch, torch.bfloat16):
        dtype = torch.float32

    try:
        StableDiffusion3Pipeline.from_pretrained(
            model_id,
            torch_dtype=dtype,
            token=hf_token or None,
            low_cpu_mem_usage=True,
        )
        _log(f"diffusion 모델 캐시 완료 | model_id={model_id}")
    except Exception as exc:
        _log(f"diffusion 모델 prefetch 실패 (런타임에 재시도됨) | model_id={model_id} | error={exc}")


def _prefetch_poster_vlm_model(model_id: str, hf_token: str) -> None:
    try:
        from huggingface_hub import snapshot_download
    except Exception as exc:
        _log(f"huggingface_hub import 실패, VLM prefetch 생략: {exc}")
        return

    _log(f"poster VLM 가중치 다운로드 시작 | model_id={model_id}")
    try:
        snapshot_download(
            repo_id=model_id,
            token=hf_token or None,
        )
        _log(f"poster VLM 캐시 완료 | model_id={model_id}")
    except Exception as exc:
        _log(f"poster VLM prefetch 실패 (런타임에 재시도됨) | model_id={model_id} | error={exc}")


def _dtype_available(torch_module: Any, dtype: Any) -> bool:
    """현재 환경(특히 CPU)에서 해당 dtype 연산이 가능한지 최소 검증."""
    try:
        torch_module.zeros(1, dtype=dtype)
        return True
    except Exception:
        return False


def _prefetch_rembg_model() -> None:
    """rembg 기본 배경제거 모델(u2net) 을 1회 다운로드."""
    try:
        from rembg import new_session
    except Exception as exc:
        _log(f"rembg import 실패, 배경제거 모델 prefetch 생략: {exc}")
        return

    _log("rembg u2net 모델 다운로드 시작")
    try:
        new_session("u2net")
        _log("rembg u2net 모델 캐시 완료")
    except Exception as exc:
        _log(f"rembg u2net 모델 prefetch 실패 (런타임에 재시도됨) | error={exc}")


def main() -> int:
    if os.getenv("HF_HUB_OFFLINE", "0") == "1":
        _log("HF_HUB_OFFLINE=1 이므로 prefetch 를 건너뜁니다.")
        return 0

    _log(f"HF_HOME={os.getenv('HF_HOME', '(unset)')}")
    _log(f"U2NET_HOME={os.getenv('U2NET_HOME', '(unset)')}")

    hf_token = os.getenv("HF_TOKEN", "").strip()

    if _hf_profile_active():
        model_id = _resolve_image_model_id()
        if not hf_token:
            _log(
                "HF_TOKEN 이 설정되지 않았습니다. "
                "gated 모델(stable-diffusion-3.5-medium)은 다운로드에 실패할 수 있습니다."
            )
        _prefetch_diffusion_model(model_id, hf_token)
    else:
        _log("image_generation provider 가 hf 가 아닙니다. diffusion prefetch 생략.")

    _prefetch_rembg_model()

    vlm_model_id = _resolve_poster_vlm_model_id()
    if vlm_model_id:
        _prefetch_poster_vlm_model(vlm_model_id, hf_token)
    else:
        _log("poster_design_analysis 비활성 — VLM prefetch 생략.")

    _log("prefetch 완료.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
