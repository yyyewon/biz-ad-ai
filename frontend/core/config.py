"""
전역 설정 모듈
"""
import os

# --------------------------------------------------------------
# 백엔드 연결 정보
# --------------------------------------------------------------
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8010").rstrip("/")
TEXT_ENDPOINT = f"{API_BASE_URL}/api/v1/ad/text"
IMAGE_ENDPOINT = f"{API_BASE_URL}/api/v1/ad/image"
GENERATE_ENDPOINT = f"{API_BASE_URL}/api/v1/ad/generate"
HEALTH_ENDPOINT = f"{API_BASE_URL}/api/v1/health"

REQUEST_TIMEOUT_TEXT = 20      # 초
REQUEST_TIMEOUT_IMAGE = 60     # 초
REQUEST_TIMEOUT_GENERATE = 60  # 초

# --------------------------------------------------------------
# 목업(Mock) 모드
# --------------------------------------------------------------
MOCK_MODE_DEFAULT = os.getenv("RG_MOCK_MODE", "true").lower() == "true"

# --------------------------------------------------------------
# 선택 옵션
# --------------------------------------------------------------
MOOD_OPTIONS = [
    "감성 카페",
    "빈티지 레트로",
    "모던 미니멀",
    "화사한 브런치",
    "우드톤 내추럴",
    "밤분위기 무드",
    "비비드 팝",
]

TONE_OPTIONS = [
    "친근한",
    "고급스러운",
    "위트있는",
    "정중한",
]

PURPOSE_OPTIONS = [
    "신메뉴 홍보",
    "재방문 유도",
    "브랜드 인지도 강화",
    "이벤트/프로모션",
    "매장 분위기 소개",
    "오픈 소식 알림",
]

MAX_UPLOAD_MB = 15
ALLOWED_IMAGE_TYPES = ["jpg", "jpeg", "png", "webp"]