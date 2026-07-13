FROM python:3.12-slim

# Pillow 및 기타 Python 패키지 빌드에 필요할 수 있는 리눅스 빌드 도구
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 소스 전체 복사
COPY . .

# 한글 오버레이 폰트 번들
RUN python scripts/setup_fonts.py

EXPOSE 8010

# /api/v1/health 로 헬스체크
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8010/api/v1/health')" || exit 1

ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]