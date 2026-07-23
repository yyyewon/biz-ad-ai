"""
공통 에러 코드/메시지 상수.

AppException에서 바로 사용할 수 있다.

사용 예:
    from app.core import error_constants as errors
    from app.core.exceptions import AppException

    raise AppException(errors.MODEL_CONFIG_NOT_FOUND, detail={...})
"""

from app.core.exceptions import ErrorSpec


# ============================================================
# Model config errors
# ============================================================

MODEL_CONFIG_NOT_FOUND = ErrorSpec(
    code="MODEL_CONFIG_NOT_FOUND",
    message="모델 설정 파일을 찾을 수 없습니다.",
    status_code=500,
)

MODEL_CONFIG_INVALID_YAML = ErrorSpec(
    code="MODEL_CONFIG_INVALID_YAML",
    message="모델 설정 파일의 YAML 형식이 올바르지 않습니다.",
    status_code=500,
)

MODEL_CONFIG_LOAD_FAILED = ErrorSpec(
    code="MODEL_CONFIG_LOAD_FAILED",
    message="모델 설정 파일을 읽는 중 오류가 발생했습니다.",
    status_code=500,
)

MODEL_CONFIG_INVALID_TYPE = ErrorSpec(
    code="MODEL_CONFIG_INVALID_TYPE",
    message="모델 설정 파일의 최상위 구조는 dict 형태여야 합니다.",
    status_code=500,
)

MODEL_CONFIG_MISSING_KEYS = ErrorSpec(
    code="MODEL_CONFIG_MISSING_KEYS",
    message="모델 설정 파일에 필수 항목이 누락되었습니다.",
    status_code=500,
)

MODEL_PROFILES_INVALID = ErrorSpec(
    code="MODEL_PROFILES_INVALID",
    message="profiles 설정이 올바르지 않습니다.",
    status_code=500,
)

MODEL_ACTIVE_PROFILE_NOT_FOUND = ErrorSpec(
    code="MODEL_ACTIVE_PROFILE_NOT_FOUND",
    message="active_profile에 해당하는 profile을 찾을 수 없습니다.",
    status_code=500,
)

MODEL_PROFILE_INVALID = ErrorSpec(
    code="MODEL_PROFILE_INVALID",
    message="profile 설정은 dict 형태여야 합니다.",
    status_code=500,
)

MODEL_PROVIDER_INVALID = ErrorSpec(
    code="MODEL_PROVIDER_INVALID",
    message="지원하지 않는 provider 값입니다.",
    status_code=500,
)

MODEL_ACTIVE_PROFILE_INVALID = ErrorSpec(
    code="MODEL_ACTIVE_PROFILE_INVALID",
    message="active_profile 설정이 올바르지 않습니다.",
    status_code=500,
)

MODEL_PROVIDER_NOT_SET = ErrorSpec(
    code="MODEL_PROVIDER_NOT_SET",
    message="요청한 역할에 대한 provider 설정이 없습니다.",
    status_code=500,
)

MODEL_PROVIDER_SECTION_NOT_FOUND = ErrorSpec(
    code="MODEL_PROVIDER_SECTION_NOT_FOUND",
    message="provider 설정 섹션을 찾을 수 없습니다.",
    status_code=500,
)

MODEL_ROLE_SECTION_NOT_FOUND = ErrorSpec(
    code="MODEL_ROLE_SECTION_NOT_FOUND",
    message="provider 내부에서 role 설정을 찾을 수 없습니다.",
    status_code=500,
)

MODEL_DEFAULT_MODEL_NOT_SET = ErrorSpec(
    code="MODEL_DEFAULT_MODEL_NOT_SET",
    message="기본 모델명이 설정되어 있지 않습니다.",
    status_code=500,
)

MODEL_LIST_INVALID = ErrorSpec(
    code="MODEL_LIST_INVALID",
    message="models 설정이 올바르지 않습니다.",
    status_code=500,
)

MODEL_SETTINGS_NOT_FOUND = ErrorSpec(
    code="MODEL_SETTINGS_NOT_FOUND",
    message="요청한 모델 설정을 찾을 수 없습니다.",
    status_code=500,
)

IMAGE_PREPROCESS_CONFIG_INVALID = ErrorSpec(
    code="IMAGE_PREPROCESS_CONFIG_INVALID",
    message="image_preprocess 설정이 올바르지 않습니다.",
    status_code=500,
)

OUTPUT_IMAGE_CONFIG_INVALID = ErrorSpec(
    code="OUTPUT_IMAGE_CONFIG_INVALID",
    message="output_image 설정이 올바르지 않습니다.",
    status_code=500,
)

PERFORMANCE_LOGGING_CONFIG_INVALID = ErrorSpec(
    code="PERFORMANCE_LOGGING_CONFIG_INVALID",
    message="performance logging 설정이 올바르지 않습니다.",
    status_code=500,
)


# ============================================================
# Provider errors
# ============================================================

OPENAI_API_KEY_MISSING = ErrorSpec(
    code="OPENAI_API_KEY_MISSING",
    message="OpenAI API Key가 설정되어 있지 않습니다.",
    status_code=500,
)

OPENAI_AUTHENTICATION_FAILED = ErrorSpec(
    code="OPENAI_AUTHENTICATION_FAILED",
    message="AI 서비스 인증 또는 접근 권한을 확인할 수 없습니다.",
    status_code=500,
)

OPENAI_TEXT_GENERATION_FAILED = ErrorSpec(
    code="OPENAI_TEXT_GENERATION_FAILED",
    message="OpenAI 텍스트 생성 중 오류가 발생했습니다.",
    status_code=500,
)

OPENAI_IMAGE_GENERATION_FAILED = ErrorSpec(
    code="OPENAI_IMAGE_GENERATION_FAILED",
    message="OpenAI 이미지 생성 중 오류가 발생했습니다.",
    status_code=500,
)

HF_PROVIDER_NOT_AVAILABLE = ErrorSpec(
    code="HF_PROVIDER_NOT_AVAILABLE",
    message="HuggingFace provider를 사용할 수 없습니다.",
    status_code=500,
)

HF_TEXT_GENERATION_FAILED = ErrorSpec(
    code="HF_TEXT_GENERATION_FAILED",
    message="HuggingFace 텍스트 생성 중 오류가 발생했습니다.",
    status_code=500,
)

HF_IMAGE_GENERATION_FAILED = ErrorSpec(
    code="HF_IMAGE_GENERATION_FAILED",
    message="HuggingFace 이미지 생성 중 오류가 발생했습니다.",
    status_code=500,
)

HF_TOKEN_MISSING = ErrorSpec(
    code="HF_TOKEN_MISSING",
    message="HuggingFace token이 설정되어 있지 않습니다.",
    status_code=500,
)

HF_IMAGE_PIPELINE_DEPENDENCY_ERROR = ErrorSpec(
    code="HF_IMAGE_PIPELINE_DEPENDENCY_ERROR",
    message="HuggingFace 이미지 생성 의존성(torch, diffusers)이 올바르게 설치되지 않았습니다.",
    status_code=500,
)

HF_IMAGE_MODEL_LOAD_FAILED = ErrorSpec(
    code="HF_IMAGE_MODEL_LOAD_FAILED",
    message="HuggingFace 이미지 모델을 불러오는 중 오류가 발생했습니다.",
    status_code=500,
)

MODEL_LOAD_INSUFFICIENT_SYSTEM_MEMORY = ErrorSpec(
    code="MODEL_LOAD_INSUFFICIENT_SYSTEM_MEMORY",
    message="모델을 안전하게 불러오기 위한 시스템 메모리가 부족합니다.",
    status_code=503,
)


# ============================================================
# Performance logging errors
# ============================================================

PERFORMANCE_LOG_WRITE_FAILED = ErrorSpec(
    code="PERFORMANCE_LOG_WRITE_FAILED",
    message="성능 로그를 기록하는 중 오류가 발생했습니다.",
    status_code=500,
)

# ============================================================
# Provider routing / input errors
# ============================================================

PROVIDER_NOT_SUPPORTED = ErrorSpec(
    code="PROVIDER_NOT_SUPPORTED",
    message="지원하지 않는 provider입니다.",
    status_code=500,
)

IMAGE_INPUT_FILE_NOT_FOUND = ErrorSpec(
    code="IMAGE_INPUT_FILE_NOT_FOUND",
    message="입력 이미지 파일을 찾을 수 없습니다.",
    status_code=400,
)

OPENAI_TEXT_RESPONSE_EMPTY = ErrorSpec(
    code="OPENAI_TEXT_RESPONSE_EMPTY",
    message="OpenAI 텍스트 응답이 비어 있습니다.",
    status_code=500,
)

OPENAI_IMAGE_RESPONSE_EMPTY = ErrorSpec(
    code="OPENAI_IMAGE_RESPONSE_EMPTY",
    message="OpenAI 이미지 응답이 비어 있습니다.",
    status_code=500,
)


# ============================================================
# Image pipeline errors
# ============================================================

IMAGE_GENERATION_EMPTY_RESULT = ErrorSpec(
    code="IMAGE_GENERATION_EMPTY_RESULT",
    message="이미지 생성 결과가 비어 있습니다.",
    status_code=500,
)

IMAGE_POSTER_RETRY_FAILED = ErrorSpec(
    code="IMAGE_POSTER_RETRY_FAILED",
    message="포스터 이미지 생성 재시도에 실패했습니다.",
    status_code=500,
)

IMAGE_PIPELINE_FAILED = ErrorSpec(
    code="IMAGE_PIPELINE_FAILED",
    message="이미지 생성 파이프라인 처리 중 오류가 발생했습니다.",
    status_code=500,
)

GENERATE_PIPELINE_IMAGE_FAILED = ErrorSpec(
    code="GENERATE_PIPELINE_IMAGE_FAILED",
    message="통합 파이프라인의 이미지 생성 단계에서 오류가 발생했습니다.",
    status_code=500,
)

INVALID_FOOD_TYPE = ErrorSpec(
    code="INVALID_FOOD_TYPE",
    message="지원하지 않는 음식 유형입니다.",
    status_code=400,
)

MISSING_FOOD_TYPE = ErrorSpec(
    code="MISSING_FOOD_TYPE",
    message="이미지 생성 시 음식 유형 선택이 필요합니다.",
    status_code=400,
)

# ============================================================
# Endpoint / preprocess errors
# ============================================================
IMAGE_PREPROCESS_DEPENDENCY_ERROR = ErrorSpec(
    code="IMAGE_PREPROCESS_DEPENDENCY_ERROR",
    message="이미지 전처리 의존성이 올바르게 설치되지 않았습니다.",
    status_code=500,
)

INVALID_IMAGE_FILE = ErrorSpec(
    code="INVALID_IMAGE_FILE",
    message="이미지 파일만 업로드할 수 있습니다.",
    status_code=400,
)

EMPTY_IMAGE_FILE = ErrorSpec(
    code="EMPTY_IMAGE_FILE",
    message="업로드된 이미지 파일이 비어 있습니다.",
    status_code=400,
)

IMAGE_PREPROCESS_FAILED = ErrorSpec(
    code="IMAGE_PREPROCESS_FAILED",
    message="이미지 전처리 중 오류가 발생했습니다.",
    status_code=500,
)

IMAGE_PREPROCESS_EMPTY_RESULT = ErrorSpec(
    code="IMAGE_PREPROCESS_EMPTY_RESULT",
    message="이미지 전처리 결과가 비어 있습니다.",
    status_code=500,
)

GENERATE_ENDPOINT_FAILED = ErrorSpec(
    code="GENERATE_ENDPOINT_FAILED",
    message="통합 광고 생성 API 처리 중 오류가 발생했습니다.",
    status_code=500,
)

FOOD_CLASSIFICATION_ENDPOINT_FAILED = ErrorSpec(
    code="FOOD_CLASSIFICATION_ENDPOINT_FAILED",
    message="음식 이미지 분류 API 처리 중 오류가 발생했습니다.",
    status_code=500,
)

# ============================================================
# Upload validation errors
# ============================================================
IMAGE_FILE_TOO_LARGE = ErrorSpec(
    code="IMAGE_FILE_TOO_LARGE",
    message="이미지 파일 용량이 너무 큽니다. 15MB 이하의 이미지를 업로드해 주세요.",
    status_code=413,
)

UNSUPPORTED_IMAGE_FORMAT = ErrorSpec(
    code="UNSUPPORTED_IMAGE_FORMAT",
    message="지원하지 않는 이미지 형식입니다. JPG, PNG, WEBP 이미지만 업로드해 주세요.",
    status_code=415,
)

