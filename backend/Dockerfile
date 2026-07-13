FROM nvidia/cuda:13.0.0-cudnn-runtime-ubuntu24.04

# rembg, onnxruntime 컴파일을 위한 필수 리눅스 빌드 도구 설치
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    build-essential \
    gcc \
    g++ \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 가상환경 생성
RUN python3 -m venv /venv

ENV PATH="/venv/bin:$PATH"

# 모델 캐시를 영속 볼륨이 마운트되는 /models 하위로 고정
ENV HF_HOME=/models/hf-cache
ENV HF_HUB_CACHE=/models/hf-cache/hub
ENV U2NET_HOME=/models/u2net

# 의존성 설치
COPY requirements.txt .

RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# 소스 전체 복사
COPY . .

# 엔트리포인트 스크립트 실행권한 부여
RUN chmod +x docker-entrypoint.sh

EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=5s --start-period=600s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8010/api/v1/health')" || exit 1

# 시작 시 모델 prefetch -> uvicorn 기동
ENTRYPOINT ["./docker-entrypoint.sh"]
