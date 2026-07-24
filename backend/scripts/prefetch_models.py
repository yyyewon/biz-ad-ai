"""
컨테이너/VM 시작 시점에 모델 가중치를 미리 다운로드하는 스크립트.

다운로드 대상:
- HF 이미지 생성 프로필: Boogu Edit-fp8, SDXL Lightning(+base/IP-Adapter), SD1.5 ControlNet Tile 또는 SD3.5
- 포스터 파이프라인: rembg u2net + (VLM 활성 시) Qwen2-VL GPTQ
- 음식 자동분류: CLIP (openai/clip-vit-base-patch32)

OpenAI 이미지 프로필(all_openai)에서는 diffusion 가중치는 건너뛴다.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any, Literal

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

PrefetchStatus = Literal["ok", "skip", "fail"]

FOOD_CLASSIFIER_MODEL_ID = "openai/clip-vit-base-patch32"
SDXL_FP16_ALLOW_PATTERNS = [
    "*.json",
    "*.txt",
    "*.model",
    "*.fp16.safetensors",
]


def _log(message: str) -> None:
    print(f"[prefetch] {message}", flush=True)


def _record(
    results: dict[str, PrefetchStatus],
    key: str,
    status: PrefetchStatus,
) -> None:
    results[key] = status


def _hf_cache_root() -> Path:
    configured = os.getenv("HF_HOME", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".cache" / "huggingface"


def _directory_size_gb(path: Path) -> float:
    total_bytes = 0
    if path.exists():
        for root, _directories, files in os.walk(path):
            for filename in files:
                try:
                    total_bytes += (Path(root) / filename).stat().st_size
                except OSError:
                    continue
    return round(total_bytes / 1024**3, 3)


def _log_hf_cache_usage(stage: str) -> None:
    cache_root = _hf_cache_root()
    disk_probe = cache_root if cache_root.exists() else cache_root.parent
    try:
        free_gb = round(shutil.disk_usage(disk_probe).free / 1024**3, 3)
    except OSError:
        free_gb = None
    _log(
        f"HF cache usage | stage={stage} | path={cache_root} | "
        f"size_gb={_directory_size_gb(cache_root)} | disk_free_gb={free_gb}"
    )


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


def _resolve_image_generation_settings() -> dict[str, Any]:
    try:
        from app.core.model_config import get_image_generation_settings

        payload = get_image_generation_settings()
        if isinstance(payload, dict):
            settings = payload.get("settings")
            if isinstance(settings, dict):
                return settings
    except Exception as exc:
        _log(f"image_generation settings 조회 실패: {exc}")
    return {}


def _resolve_image_model_id() -> str:
    env_model_id = os.getenv("PREFETCH_MODEL_ID", "").strip()
    if env_model_id:
        return env_model_id

    model_settings = _resolve_image_generation_settings()
    model_id = model_settings.get("model_id")
    if isinstance(model_id, str) and model_id.strip():
        return model_id.strip()

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


def _prefetch_diffusion_model(model_id: str, hf_token: str) -> bool:
    try:
        import torch
        from diffusers import StableDiffusion3Pipeline
    except Exception as exc:
        _log(f"torch/diffusers import 실패, diffusion 모델 prefetch 생략: {exc}")
        return False

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
        return True
    except Exception as exc:
        _log(f"diffusion 모델 prefetch 실패 (런타임에 재시도됨) | model_id={model_id} | error={exc}")
        return False


def _prefetch_sdxl_lightning_models(hf_token: str) -> bool:
    try:
        from huggingface_hub import hf_hub_download, snapshot_download
    except Exception as exc:
        _log(f"huggingface_hub import 실패, SDXL prefetch 생략: {exc}")
        return False

    model_settings = _resolve_image_generation_settings()
    base_model_id = str(
        model_settings.get("base_model_id") or "stabilityai/stable-diffusion-xl-base-1.0"
    ).strip()
    lightning_repo_id = str(
        model_settings.get("model_id") or "ByteDance/SDXL-Lightning"
    ).strip()
    lightning_checkpoint = str(
        model_settings.get("lightning_checkpoint") or "sdxl_lightning_4step_unet.safetensors"
    ).strip()
    ip_adapter = model_settings.get("ip_adapter") if isinstance(model_settings.get("ip_adapter"), dict) else {}

    ok = True
    _log(f"SDXL base 다운로드 시작 | model_id={base_model_id}")
    try:
        snapshot_download(repo_id=base_model_id, token=hf_token or None)
        _log(f"SDXL base 캐시 완료 | model_id={base_model_id}")
    except Exception as exc:
        ok = False
        _log(f"SDXL base prefetch 실패 | model_id={base_model_id} | error={exc}")

    _log(
        f"SDXL Lightning checkpoint 다운로드 시작 | repo_id={lightning_repo_id} | file={lightning_checkpoint}"
    )
    try:
        hf_hub_download(
            repo_id=lightning_repo_id,
            filename=lightning_checkpoint,
            token=hf_token or None,
        )
        _log(f"SDXL Lightning checkpoint 캐시 완료 | repo_id={lightning_repo_id}")
    except Exception as exc:
        ok = False
        _log(f"SDXL Lightning checkpoint prefetch 실패 | error={exc}")

    if ip_adapter.get("enabled"):
        repo_id = str(ip_adapter.get("repo_id") or "h94/IP-Adapter").strip()
        _log(f"IP-Adapter 다운로드 시작 | repo_id={repo_id}")
        try:
            snapshot_download(repo_id=repo_id, token=hf_token or None)
            _log(f"IP-Adapter 캐시 완료 | repo_id={repo_id}")
        except Exception as exc:
            ok = False
            _log(f"IP-Adapter prefetch 실패 | repo_id={repo_id} | error={exc}")

    return ok


def _prefetch_sdxl_ip_adapter_models(hf_token: str) -> bool:
    """Cache only the FP16 SDXL files and exact IP-Adapter Plus artifacts."""
    try:
        from huggingface_hub import hf_hub_download, snapshot_download
    except Exception as exc:
        _log(f"huggingface_hub import failed, skipping SDXL IP-Adapter prefetch: {exc}")
        return False

    model_settings = _resolve_image_generation_settings()
    base_model_id = str(
        model_settings.get("base_model_id")
        or "stabilityai/stable-diffusion-xl-base-1.0"
    ).strip()
    inpaint_model_id = str(
        model_settings.get("inpaint_model_id")
        or "diffusers/stable-diffusion-xl-1.0-inpainting-0.1"
    ).strip()
    raw_ip_adapter = model_settings.get("ip_adapter")
    ip_adapter = raw_ip_adapter if isinstance(raw_ip_adapter, dict) else {}
    repo_id = str(ip_adapter.get("repo_id") or "h94/IP-Adapter").strip()
    subfolder = str(ip_adapter.get("subfolder") or "sdxl_models").strip()
    weight_name = str(
        ip_adapter.get("weight_name")
        or "ip-adapter-plus_sdxl_vit-h.safetensors"
    ).strip()
    image_encoder_folder = str(
        ip_adapter.get("image_encoder_folder") or "models/image_encoder"
    ).strip()

    ok = True
    for label, model_id in (
        ("SDXL Base", base_model_id),
        ("SDXL Inpaint", inpaint_model_id),
    ):
        _log(f"{label} FP16 download started | model_id={model_id}")
        try:
            cache_path = snapshot_download(
                repo_id=model_id,
                allow_patterns=SDXL_FP16_ALLOW_PATTERNS,
                token=hf_token or None,
            )
            _log(f"{label} cache complete | model_id={model_id} | path={cache_path}")
        except Exception as exc:
            ok = False
            _log(f"{label} prefetch failed | model_id={model_id} | error={exc}")

    adapter_files = (
        (subfolder, weight_name, "IP-Adapter Plus weight"),
        (image_encoder_folder, "config.json", "IP-Adapter image encoder config"),
        (
            image_encoder_folder,
            "model.safetensors",
            "IP-Adapter image encoder weight",
        ),
    )
    for file_subfolder, filename, label in adapter_files:
        _log(
            f"{label} download started | repo_id={repo_id} | "
            f"subfolder={file_subfolder} | file={filename}"
        )
        try:
            cache_path = hf_hub_download(
                repo_id=repo_id,
                subfolder=file_subfolder,
                filename=filename,
                token=hf_token or None,
            )
            _log(f"{label} cache complete | path={cache_path}")
        except Exception as exc:
            ok = False
            _log(f"{label} prefetch failed | error={exc}")

    return ok


def _prefetch_sd15_controlnet_tile_models(hf_token: str) -> bool:
    """SD 1.5 Base 모델과 ControlNet Tile v1.1 가중치를 미리 캐시한다."""
    try:
        from huggingface_hub import snapshot_download
    except Exception as exc:
        _log(f"huggingface_hub import 실패, SD1.5 ControlNet prefetch 생략: {exc}")
        return False

    model_settings = _resolve_image_generation_settings()
    base_model_id = str(
        model_settings.get("base_model_id") or "runwayml/stable-diffusion-v1-5"
    ).strip()
    controlnet_model_id = str(
        model_settings.get("controlnet_model_id") or "lllyasviel/control_v11f1e_sd15_tile"
    ).strip()

    ok = True
    _log(f"SD1.5 base 다운로드 시작 | model_id={base_model_id}")
    try:
        snapshot_download(repo_id=base_model_id, token=hf_token or None)
        _log(f"SD1.5 base 캐시 완료 | model_id={base_model_id}")
    except Exception as exc:
        ok = False
        _log(f"SD1.5 base prefetch 실패 | model_id={base_model_id} | error={exc}")

    _log(f"ControlNet Tile 모델 다운로드 시작 | model_id={controlnet_model_id}")
    try:
        snapshot_download(repo_id=controlnet_model_id, token=hf_token or None)
        _log(f"ControlNet Tile 모델 캐시 완료 | model_id={controlnet_model_id}")
    except Exception as exc:
        ok = False
        _log(f"ControlNet Tile prefetch 실패 | model_id={controlnet_model_id} | error={exc}")

    return ok


def _prefetch_boogu_edit_models(hf_token: str) -> bool:
    try:
        from huggingface_hub import snapshot_download
    except Exception as exc:
        _log(f"huggingface_hub import failed, skipping Boogu Edit prefetch: {exc}")
        return False

    model_settings = _resolve_image_generation_settings()
    model_id = str(
        model_settings.get("model_id") or "Boogu/Boogu-Image-0.1-Edit-fp8"
    ).strip()

    _log(f"Boogu Edit pipeline download started | model_id={model_id}")
    try:
        snapshot_download(repo_id=model_id, token=hf_token or None)
        _log(f"Boogu Edit pipeline cached | model_id={model_id}")
        return True
    except Exception as exc:
        _log(f"Boogu Edit prefetch failed | model_id={model_id} | error={exc}")
        return False


def _prefetch_hf_image_models(hf_token: str) -> bool:
    model_settings = _resolve_image_generation_settings()
    provider_type = str(model_settings.get("provider_type") or "").strip()

    if provider_type == "sdxl_lightning":
        return _prefetch_sdxl_lightning_models(hf_token)

    if provider_type == "sdxl_ip_adapter":
        return _prefetch_sdxl_ip_adapter_models(hf_token)

    if provider_type == "sd15_controlnet_tile":
        return _prefetch_sd15_controlnet_tile_models(hf_token)

    if provider_type == "boogu_edit":
        return _prefetch_boogu_edit_models(hf_token)

    model_id = _resolve_image_model_id()
    return _prefetch_diffusion_model(model_id, hf_token)


def _prefetch_poster_vlm_model(model_id: str, hf_token: str) -> bool:
    try:
        from huggingface_hub import snapshot_download
    except Exception as exc:
        _log(f"huggingface_hub import 실패, VLM prefetch 생략: {exc}")
        return False

    _log(f"poster VLM 가중치 다운로드 시작 | model_id={model_id}")
    try:
        snapshot_download(
            repo_id=model_id,
            token=hf_token or None,
        )
        _log(f"poster VLM 캐시 완료 | model_id={model_id}")
        return True
    except Exception as exc:
        _log(f"poster VLM prefetch 실패 (런타임에 재시도됨) | model_id={model_id} | error={exc}")
        return False


def _prefetch_food_classifier_model(hf_token: str) -> bool:
    try:
        from huggingface_hub import snapshot_download
    except Exception as exc:
        _log(f"huggingface_hub import 실패, food classifier prefetch 생략: {exc}")
        return False

    _log(f"food classifier 다운로드 시작 | model_id={FOOD_CLASSIFIER_MODEL_ID}")
    try:
        snapshot_download(
            repo_id=FOOD_CLASSIFIER_MODEL_ID,
            token=hf_token or None,
        )
        _log(f"food classifier 캐시 완료 | model_id={FOOD_CLASSIFIER_MODEL_ID}")
        return True
    except Exception as exc:
        _log(f"food classifier prefetch 실패 (런타임에 재시도됨) | error={exc}")
        return False


def _dtype_available(torch_module: Any, dtype: Any) -> bool:
    """현재 환경(특히 CPU)에서 해당 dtype 연산이 가능한지 최소 검증."""
    try:
        torch_module.zeros(1, dtype=dtype)
        return True
    except Exception:
        return False


def _prefetch_rembg_model() -> bool:
    """rembg 기본 배경제거 모델(u2net) 을 1회 다운로드."""
    try:
        from rembg import new_session
    except Exception as exc:
        _log(f"rembg import 실패, 배경제거 모델 prefetch 생략: {exc}")
        return False

    _log("rembg u2net 모델 다운로드 시작")
    try:
        new_session("u2net")
        _log("rembg u2net 모델 캐시 완료")
        return True
    except Exception as exc:
        _log(f"rembg u2net 모델 prefetch 실패 (런타임에 재시도됨) | error={exc}")
        return False


def _log_summary(results: dict[str, PrefetchStatus]) -> None:
    _log("--- prefetch 요약 ---")
    for key, status in results.items():
        label = {"ok": "완료", "skip": "건너뜀", "fail": "실패"}[status]
        _log(f"  {key}: {label}")
    _log("--------------------")


def main() -> int:
    if os.getenv("HF_HUB_OFFLINE", "0") == "1":
        _log("HF_HUB_OFFLINE=1 이므로 prefetch 를 건너뜁니다.")
        return 0

    results: dict[str, PrefetchStatus] = {}

    _log(f"HF_HOME={os.getenv('HF_HOME', '(unset)')}")
    _log(f"U2NET_HOME={os.getenv('U2NET_HOME', '(unset)')}")
    _log_hf_cache_usage("before")

    hf_token = os.getenv("HF_TOKEN", "").strip()

    if _hf_profile_active():
        if not hf_token:
            _log(
                "HF_TOKEN 이 설정되지 않았습니다. "
                "gated 모델은 다운로드에 실패할 수 있습니다."
            )
        results["hf_image_generation"] = (
            "ok" if _prefetch_hf_image_models(hf_token) else "fail"
        )
    else:
        _log("image_generation provider 가 hf 가 아닙니다.")
        results["hf_image_generation"] = "skip"

    results["rembg_u2net"] = "ok" if _prefetch_rembg_model() else "fail"

    vlm_model_id = _resolve_poster_vlm_model_id()
    if vlm_model_id:
        results["poster_vlm"] = (
            "ok" if _prefetch_poster_vlm_model(vlm_model_id, hf_token) else "fail"
        )
    else:
        _log("poster_design_analysis 비활성 - VLM prefetch 생략.")
        results["poster_vlm"] = "skip"

    results["food_classifier_clip"] = (
        "ok" if _prefetch_food_classifier_model(hf_token) else "fail"
    )

    _log_summary(results)
    _log_hf_cache_usage("after")
    _log("prefetch 완료.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
