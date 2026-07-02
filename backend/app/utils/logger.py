import os
import time
from pathlib import Path

from loguru import logger


LOG_DIR = Path("backend/logs")
LOG_FILE = LOG_DIR / "app.log"
KST_TIMEZONE = "Asia/Seoul"


def setup_logger() -> None:
    """
    프로젝트 공통 logger를 설정합니다.

    로그 저장 위치:
    - backend/logs/app.log

    시간 기준:
    - 팀원이 로그를 바로 이해할 수 있도록 한국 시간(KST, Asia/Seoul) 기준으로 기록합니다.
    - VM 기본 timezone이 UTC여도 애플리케이션 로그는 KST로 남깁니다.
    """

    # loguru의 {time} 포맷이 KST 기준으로 출력되도록 프로세스 timezone을 설정합니다.
    # Linux VM에서는 time.tzset()으로 런타임 timezone 변경이 가능합니다.
    os.environ["TZ"] = KST_TIMEZONE
    if hasattr(time, "tzset"):
        time.tzset()

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # loguru 기본 handler를 제거하고 프로젝트 기준 handler를 다시 등록합니다.
    # uvicorn reload 시 중복 로그가 찍히는 것을 줄이기 위한 처리입니다.
    logger.remove()

    # 터미널 출력용 로그
    logger.add(
        sink=lambda message: print(message, end=""),
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    )

    # 파일 저장용 로그
    logger.add(
        LOG_FILE,
        level="INFO",
        rotation="10 MB",
        retention="7 days",
        encoding="utf-8",
        enqueue=True,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    )
