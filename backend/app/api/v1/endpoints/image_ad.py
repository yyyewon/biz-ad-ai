from fastapi import APIRouter, HTTPException, status

from app.core.config import get_settings
from app.schemas.image_ad import ImageAdRequest, ImageAdResponse
from app.services.pipelines.image_pipeline import generate_image_ads

router = APIRouter(prefix="/ad", tags=["ad-image"])


@router.post("/image", response_model=ImageAdResponse, status_code=status.HTTP_200_OK)
async def create_image_ad(payload: ImageAdRequest) -> ImageAdResponse:
    settings = get_settings()
    try:
        return generate_image_ads(
            payload=payload,
            output_root=settings.output_dir,
            public_prefix="/outputs",
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"이미지 생성 중 오류가 발생했습니다: {exc}",
        ) from exc
