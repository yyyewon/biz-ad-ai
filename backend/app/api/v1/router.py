from fastapi import APIRouter

from app.api.v1.endpoints import auth, business_info, dev_apis, generate_ad, health

api_router = APIRouter()

# Health Check API
api_router.include_router(
    health.router,
    prefix="/health",
    tags=["Health"],
)

# Auth API
api_router.include_router(
    auth.router,
    prefix="/auth",
    tags=["Auth"],
)

# 실제 서비스용 통합 광고 이미지 생성 API
api_router.include_router(
    generate_ad.router,
    prefix="/ad",
    tags=["Generate Ad"],
)

# 개발/테스트용 API 묶음
api_router.include_router(
    dev_apis.router,
    prefix="/dev",
)

# 가게 정보 저장 API
api_router.include_router(
    business_info.router,
    prefix="/auth",
    tags=["Business Info"],
)