from fastapi import APIRouter

from app.api.v1.endpoints import auth, generate_ad, health, image_ad, image_preprocess

api_router = APIRouter()

# Health Check API
api_router.include_router(
    health.router,
    prefix="/health",
    tags=["Health"],
)

# Image preprocess API
api_router.include_router(
    image_preprocess.router,
    prefix="/image",
    tags=["Image Preprocess"],
)

# Auth API
api_router.include_router(
    auth.router,
    prefix="/auth",
    tags=["Auth"],
)

# Combined generation API
api_router.include_router(
    generate_ad.router,
    prefix="/ad/generate",
    tags=["Generate Ad"],
)

# Image-only generation API
api_router.include_router(image_ad.router)
