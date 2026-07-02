from app.api.v1.endpoints import image_preprocess
from fastapi import APIRouter

from app.api.v1.endpoints import health


# API v1에서 사용하는 전체 라우터입니다.
# 각 endpoint 파일에서 정의한 router를 이곳에서 하나로 묶습니다.
api_router = APIRouter()


# Health Check API 연결
# 최종 경로: GET /api/v1/health
api_router.include_router(
    health.router,
    prefix="/health",
    tags=["Health"],
)

# Image Preprocess API 연결
# 최종 경로: POST /api/v1/image/preprocess
api_router.include_router(
    image_preprocess.router,
    prefix="/image",
    tags=["Image Preprocess"],
)
