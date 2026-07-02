from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router


# FastAPI 애플리케이션 인스턴스 생성
# Swagger 문서는 /docs, ReDoc 문서는 /redoc 경로에서 확인할 수 있습니다.
app = FastAPI(
    title="Biz Ad AI Backend",
    description="AI 기반 소상공인 광고 콘텐츠 생성 백엔드 API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


# CORS 설정
# 현재 개발 단계에서는 프론트엔드 Streamlit과 연동 테스트를 쉽게 하기 위해 전체 허용합니다.
# 배포 단계에서 허용 도메인이 확정되면 allow_origins 값을 구체적인 URL로 제한하는 것이 좋습니다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
