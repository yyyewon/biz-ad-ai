"""
전역 설정 모듈
"""
import os

# --------------------------------------------------------------
# 백엔드 연결 정보
# --------------------------------------------------------------
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8010").rstrip("/")
API_BROWSER_BASE_URL = os.getenv("API_BROWSER_BASE_URL", API_BASE_URL).rstrip("/")
# 실제 서비스용 통합 생성 API
GENERATE_ENDPOINT = f"{API_BASE_URL}/api/v1/ad/generate"

# 개발/테스트용 API
TEXT_ENDPOINT = f"{API_BASE_URL}/api/v1/dev/ad/text"
IMAGE_ENDPOINT = f"{API_BASE_URL}/api/v1/dev/ad/image"
IMAGE_PREPROCESS_ENDPOINT = f"{API_BASE_URL}/api/v1/dev/image/preprocess"

# Health Check API
HEALTH_ENDPOINT = f"{API_BASE_URL}/api/v1/health"

# --------------------------------------------------------------
# 소셜 로그인 / 사용자 정보
# --------------------------------------------------------------
KAKAO_LOGIN_ENDPOINT = f"{API_BROWSER_BASE_URL}/api/v1/auth/kakao/login"
ME_ENDPOINT = f"{API_BASE_URL}/api/v1/auth/me"
LOGOUT_ENDPOINT = f"{API_BROWSER_BASE_URL}/api/v1/auth/logout"
DEV_RESET_QUOTA_ENDPOINT = f"{API_BASE_URL}/api/v1/auth/dev/reset-quota"

REQUEST_TIMEOUT_TEXT = 60      # 초
REQUEST_TIMEOUT_IMAGE = 120     # 초
REQUEST_TIMEOUT_GENERATE = 600  # 초 (임시 상향)
REQUEST_TIMEOUT_AUTH = 10      # 초

# --------------------------------------------------------------
# 목업(Mock) 모드
# --------------------------------------------------------------
MOCK_MODE_DEFAULT = os.getenv("RG_MOCK_MODE", "false").lower() == "true"
DEV_GUEST_MODE_DEFAULT = os.getenv("RG_DEV_GUEST_MODE", "false").lower() == "true"

# --------------------------------------------------------------
# 선택 옵션
# -------------------------------------------------------------

FOOD_OPTIONS = [
    "국, 찌개",
    "튀김",
    "덮밥, 볶음, 비빔",
    "빵, 디저트, 케이크",
    "버거, 샌드위치",
    "커피, 음료",
    "구이, 바베큐"
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
