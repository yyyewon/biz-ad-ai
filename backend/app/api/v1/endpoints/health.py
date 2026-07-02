from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from backend.app.schemas.common import success_response


# health endpoint 전용 라우터입니다.
# router.py에서 prefix="/health"로 연결됩니다.
router = APIRouter()

KST = ZoneInfo("Asia/Seoul")


@router.get("")
async def health_check():
    """
    서버 상태 확인 API입니다.

    사용 목적:
    - FastAPI 서버가 정상 실행 중인지 확인
    - 배포 후 로드밸런서, Docker, 프론트엔드에서 서버 상태 체크
    - 백엔드 기본 연결 테스트

    현재 단계에서는 DB, 모델, 외부 API 연결을 확인하지 않습니다.
    단순히 서버 프로세스와 라우터가 정상 동작하는지만 확인합니다.
    """

    return success_response(
        data={
            "status": "ok",
            "service": "biz-ad-ai-backend",
            "timestamp": datetime.now(KST).isoformat(),
            "timezone": "Asia/Seoul",
        }
    )
