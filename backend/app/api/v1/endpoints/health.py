from datetime import datetime, timezone

from fastapi import APIRouter


# health endpoint 전용 라우터입니다.
# router.py에서 prefix="/health"로 연결됩니다.
router = APIRouter()


@router.get("")
async def health_check():
    """
    서버 상태 확인 API입니다.

    사용 목적:
    - FastAPI 서버가 정상 실행 중인지 확인
    - 배포 후 로드밸런서, Docker, 프론트엔드에서 서버 상태 체크
    - 백엔드 기본 연결 테스트

    응답 형식:
    {
        "success": true,
        "data": {...},
        "error": null
    }
    """

    return {
        "success": True,
        "data": {
            "status": "ok",
            "service": "biz-ad-ai-backend",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "error": None,
    }
