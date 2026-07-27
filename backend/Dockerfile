FROM python:3.12-slim

# Pillow 및 기타 Python 패키지 빌드에 필요할 수 있는 리눅스 빌드 도구
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 가상환경 생성
RUN python3 -m venv /venv

ENV PATH="/venv/bin:$PATH"

# 모델 캐시를 영속 볼륨이 마운트되는 /models 하위로 고정
ENV HF_HOME=/models/hf-cache
ENV HF_HUB_CACHE=/models/hf-cache/hub
ENV U2NET_HOME=/models/u2net

# 의존성 설치 (torch 먼저 → gptqmodel은 빌드 시 torch 필요)
COPY requirements-torch.txt requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements-torch.txt && \
    pip install --no-cache-dir -r requirements.txt --no-build-isolation && \
    pip install --no-cache-dir --no-deps \
      "boogu-image @ git+https://github.com/boogu-project/Boogu-Image.git"

# 소스 전체 복사
COPY . .

# 한글 오버레이 폰트 번들
RUN python scripts/setup_fonts.py

# 엔트리포인트 스크립트 실행권한 부여
RUN chmod +x docker-entrypoint.sh

EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=5s --start-period=600s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8010/api/v1/health')" || exit 1

# 시작 시 모델 prefetch -> uvicorn 기동
ENTRYPOINT ["./docker-entrypoint.sh"]
