from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from loguru import logger

from app.core.exceptions import AppException
from app.core.model_config import get_active_profile_name, get_performance_logging_settings


BACKEND_ROOT = Path(__file__).resolve().parents[2]
KST = timezone(timedelta(hours=9))


def _now_kst_iso() -> str:
    """
    KST 기준 ISO timestamp를 반환한다.
    """

    return datetime.now(KST).replace(microsecond=0).isoformat()


def format_elapsed_time(elapsed_ms: float) -> dict[str, float | str]:
    """
    elapsed_ms를 사람이 읽기 쉬운 형태로 변환한다.

    반환 예:
    {
      "elapsed_ms": 129429.323,
      "elapsed_sec": 129.429,
      "elapsed_human": "2분 9.4초"
    }
    """

    rounded_ms = round(float(elapsed_ms), 3)
    elapsed_sec = round(rounded_ms / 1000, 3)

    if elapsed_sec >= 3600:
        hours = int(elapsed_sec // 3600)
        minutes = int((elapsed_sec % 3600) // 60)
        seconds = elapsed_sec % 60
        elapsed_human = f"{hours}시간 {minutes}분 {seconds:.1f}초"

    elif elapsed_sec >= 60:
        minutes = int(elapsed_sec // 60)
        seconds = elapsed_sec % 60
        elapsed_human = f"{minutes}분 {seconds:.1f}초"

    else:
        elapsed_human = f"{elapsed_sec:.2f}초"

    return {
        "elapsed_ms": rounded_ms,
        "elapsed_sec": elapsed_sec,
        "elapsed_human": elapsed_human,
    }


def _resolve_performance_log_path() -> Path:
    """
    model.yaml의 logging.performance.path 값을 기준으로 로그 파일 경로를 결정한다.

    상대 경로이면 backend 루트 기준으로 해석한다.
    예:
    - logs/performance.jsonl
    - /app/logs/performance.jsonl
    """

    settings = get_performance_logging_settings()
    raw_path = str(settings.get("path", "logs/performance.jsonl"))
    path = Path(raw_path)

    if path.is_absolute():
        return path

    return BACKEND_ROOT / path


def is_performance_logging_enabled() -> bool:
    """
    성능 로그 활성화 여부를 반환한다.
    """

    try:
        settings = get_performance_logging_settings()
        return bool(settings.get("enabled", True))

    except Exception as exc:
        logger.warning(
            "performance_logging_config_check_failed | error={}",
            str(exc),
        )
        return False


def _safe_active_profile_name() -> str:
    """
    active_profile 이름을 안전하게 가져온다.

    성능 로그 기록 중 설정 문제가 발생해도 실제 서비스 흐름이 깨지지 않도록 unknown을 반환한다.
    """

    try:
        return get_active_profile_name()

    except Exception:
        return "unknown"


def write_performance_metric(metric: dict[str, Any]) -> None:
    """
    성능 metric을 JSONL 파일에 기록한다.

    주의:
    - 성능 로그 기록 실패가 실제 API 실패로 이어지면 안 된다.
    - 따라서 모든 예외는 logger에만 남기고 raise하지 않는다.
    """

    try:
        if not is_performance_logging_enabled():
            return

        log_path = _resolve_performance_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)

        with log_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(metric, ensure_ascii=False) + "\n")

    except Exception as exc:
        logger.exception(
            "performance_log_write_failed | error={}",
            str(exc),
        )


def record_performance_metric(
    *,
    pipeline: str,
    stage: str,
    request_id: str,
    provider: str,
    model: str,
    elapsed_ms: float,
    success: bool,
    profile: str | None = None,
    error_code: str | None = None,
    error_type: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    성능 metric을 생성하고 JSONL + 일반 로그에 기록한다.

    JSONL에는 기계 분석용 필드와 사람이 읽기 쉬운 시간 필드를 함께 기록한다.

    기록 시간 필드:
    - elapsed_ms: 밀리초
    - elapsed_sec: 초
    - elapsed_human: 사람이 읽기 쉬운 시간
    """

    elapsed = format_elapsed_time(elapsed_ms)

    metric: dict[str, Any] = {
        "event": "perf_metric",
        "timestamp": _now_kst_iso(),
        "request_id": request_id,
        "pipeline": pipeline,
        "profile": profile or _safe_active_profile_name(),
        "stage": stage,
        "provider": provider,
        "model": model,
        "elapsed_ms": elapsed["elapsed_ms"],
        "elapsed_sec": elapsed["elapsed_sec"],
        "elapsed_human": elapsed["elapsed_human"],
        "success": success,
    }

    if error_code:
        metric["error_code"] = error_code

    if error_type:
        metric["error_type"] = error_type

    if extra is not None:
        metric["extra"] = extra

    write_performance_metric(metric)

    # 일반 .log / 콘솔 로그에서도 사람이 읽기 쉽게 확인할 수 있도록 같은 시간 정보를 출력한다.
    logger.info(
        (
            "perf_metric | request_id={} | pipeline={} | profile={} | stage={} "
            "| provider={} | model={} | elapsed_ms={} | elapsed_sec={} "
            "| elapsed_human={} | success={} | error_code={} | error_type={}"
        ),
        metric["request_id"],
        metric["pipeline"],
        metric["profile"],
        metric["stage"],
        metric["provider"],
        metric["model"],
        metric["elapsed_ms"],
        metric["elapsed_sec"],
        metric["elapsed_human"],
        metric["success"],
        metric.get("error_code"),
        metric.get("error_type"),
    )

    return metric


@contextmanager
def measure_stage(
    *,
    pipeline: str,
    stage: str,
    request_id: str,
    provider: str,
    model: str,
    profile: str | None = None,
    extra: dict[str, Any] | None = None,
) -> Iterator[None]:
    """
    with 블록으로 stage 소요 시간을 측정한다.

    사용 예:
    with measure_stage(...):
        result = run_some_stage()

    성공 시:
    - success=true 기록

    AppException 발생 시:
    - success=false
    - error_code=exc.code
    - error_type=AppException
    - 예외 재발생

    일반 Exception 발생 시:
    - success=false
    - error_code=UNHANDLED_EXCEPTION
    - error_type=실제 예외 클래스명
    - 예외 재발생
    """

    started = time.perf_counter()

    try:
        yield

    except AppException as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000

        record_performance_metric(
            pipeline=pipeline,
            stage=stage,
            request_id=request_id,
            profile=profile,
            provider=provider,
            model=model,
            elapsed_ms=elapsed_ms,
            success=False,
            error_code=exc.code,
            error_type=exc.__class__.__name__,
            extra=extra,
        )

        raise

    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000

        record_performance_metric(
            pipeline=pipeline,
            stage=stage,
            request_id=request_id,
            profile=profile,
            provider=provider,
            model=model,
            elapsed_ms=elapsed_ms,
            success=False,
            error_code="UNHANDLED_EXCEPTION",
            error_type=exc.__class__.__name__,
            extra=extra,
        )

        raise

    else:
        elapsed_ms = (time.perf_counter() - started) * 1000

        record_performance_metric(
            pipeline=pipeline,
            stage=stage,
            request_id=request_id,
            profile=profile,
            provider=provider,
            model=model,
            elapsed_ms=elapsed_ms,
            success=True,
            extra=extra,
        )
