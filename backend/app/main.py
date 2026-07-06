import os

from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.api.v1.router import api_router
from app.core.exceptions import register_exception_handlers
from app.core.database import init_db
from app.utils.logger import setup_logger


# 프로젝트 공통 logger 설정
# 서버 시작 시 터미널 출력과 backend/logs/app.log 파일 로그를 함께 설정합니다.
setup_logger()

# 소셜 로그인 / 일일 생성 횟수 제한용 SQLite 스키마 초기화
init_db()


# FastAPI 애플리케이션 인스턴스 생성
# Swagger 문서는 /docs, ReDoc 문서는 /redoc 경로에서 확인할 수 있습니다.
app = FastAPI(
    title="Biz Ad AI Backend",
    description="AI 기반 소상공인 광고 콘텐츠 생성 백엔드 API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


# 공통 예외 처리 등록
# AppException, validation error, 404/405, 예상하지 못한 서버 오류를 공통 응답 형식으로 변환합니다.
register_exception_handlers(app)


# CORS 설정
_DEFAULT_ORIGINS = "http://localhost:8501"
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", _DEFAULT_ORIGINS).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """
    모든 HTTP 요청에 대해 기본 로그를 남기는 middleware입니다.

    기록 항목:
    - request_id
    - HTTP method
    - path
    - status_code
    - elapsed_ms

    주의:
    - 요청 body, 이미지 bytes, base64 원문은 로그에 남기지 않습니다.
    - request_id는 프론트/백엔드 디버깅 시 같은 요청을 추적하기 위한 값입니다.
    """

    request_id = str(uuid4())
    start_time = perf_counter()

    response = await call_next(request)

    elapsed_ms = round((perf_counter() - start_time) * 1000, 2)

    logger.info(
        "request_completed | request_id={} | method={} | path={} | status_code={} | elapsed_ms={}",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )

    # 프론트엔드나 테스트 도구에서 요청 추적에 사용할 수 있도록 응답 헤더에도 request_id를 포함합니다.
    response.headers["X-Request-ID"] = request_id

    return response


# API v1 라우터 연결
# 실제 API 경로는 /api/v1 하위에 구성됩니다.
# 예: /api/v1/health
app.include_router(api_router, prefix="/api/v1")


@app.get("/")
async def root():
    """
    서버 기본 상태 확인용 루트 엔드포인트입니다.

    사용 목적:
    - 서버가 정상 실행 중인지 빠르게 확인
    - Swagger 문서 경로 안내
    """

    return {
        "service": "biz-ad-ai-backend",
        "status": "running",
        "docs": "/docs",
    }
