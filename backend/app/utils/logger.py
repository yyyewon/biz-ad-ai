import os
import time
from pathlib import Path

from loguru import logger


# 현재 파일 위치:
# backend/app/utils/logger.py
#
# parents[0] = backend/app/utils
# parents[1] = backend/app
# parents[2] = backend
BACKEND_ROOT = Path(__file__).resolve().parents[2]

LOG_DIR = BACKEND_ROOT / "logs"
LOG_FILE = LOG_DIR / "app.log"
KST_TIMEZONE = "Asia/Seoul"


def setup_logger() -> None:
    """
    프로젝트 공통 logger를 설정합니다.

    로그 저장 위치:
    - backend/logs/app.log

    시간 기준:
    - 한국 시간(KST, Asia/Seoul) 기준으로 기록합니다.

    """

    os.environ["TZ"] = KST_TIMEZONE
    if hasattr(time, "tzset"):
        time.tzset()

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger.remove()

    logger.add(
        sink=lambda message: print(message, end=""),
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    )

    logger.add(
        LOG_FILE,
        level="INFO",
        rotation="10 MB",
        retention="7 days",
        encoding="utf-8",
        enqueue=True,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    )
