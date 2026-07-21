#!/usr/bin/env sh
#!/bin/bash
# 컨테이너 시작 시점에 모델 가중치를 미리 다운로드한 뒤 uvicorn 을 실행
set -e

if [ "${PREFETCH_SKIP:-0}" = "1" ]; then
  echo "[entrypoint] PREFETCH_SKIP=1 -> prefetch 단계를 건너뜁니다."
else
  echo "[entrypoint] 모델 prefetch 시작..."
  python scripts/prefetch_models.py || echo "[entrypoint] prefetch 중 오류 발생(무시하고 기동)."
fi

echo "[entrypoint] uvicorn 기동..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8010 "$@"
