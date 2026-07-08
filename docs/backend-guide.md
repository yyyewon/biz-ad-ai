# Biz Ad AI Backend Guide

## 1. 목적

이 문서는 Biz Ad AI 백엔드 개발자가 공통 구조를 일관되게 사용할 수 있도록 정리한 가이드다.

백엔드 코드를 작성할 때는 아래 기준을 따른다.

- API 응답은 공통 응답 포맷을 사용한다.
- 에러는 `AppException`과 `error_constants.py`를 사용한다.
- 모델/provider 설정은 `backend/config/model.yaml`에서 관리한다.
- API Key, JWT, Kakao Secret 같은 민감정보는 `.env`에서 관리한다.
- endpoint는 요청/응답 처리만 담당하고, 실제 로직은 pipeline/service/provider로 분리한다.
- 성능 측정이 필요한 파이프라인은 `performance_logger.py`를 사용한다.

---

## 2. 백엔드 기본 구조

주요 디렉터리 구조는 아래와 같다.

```text
backend/
├── app/
│   ├── api/
│   │   └── v1/
│   │       └── endpoints/        # FastAPI endpoint
│   ├── core/                     # 설정, 예외, 공통 의존성
│   ├── schemas/                  # request/response schema
│   ├── services/
│   │   ├── pipelines/            # 비즈니스 흐름
│   │   └── providers/            # OpenAI/HF 등 외부 모델 호출
│   └── utils/                    # 공통 유틸
├── config/
│   └── model.yaml                # 모델/provider 설정
├── logs/
│   └── .gitkeep                  # 성능 로그 디렉터리 유지용
├── tests/                        # 테스트 코드
├── .env                          # 로컬 환경변수, Git 제외
└── Dockerfile
```

---

## 3. 설정 파일 역할

백엔드 설정은 두 종류로 나눈다.

```text
.env / app/core/config.py
→ 비밀값, 배포환경값, 앱 실행 설정

backend/config/model.yaml
→ 모델 선택, provider 조합, 모델별 실험 파라미터
```

---

## 4. `.env / app/core/config.py` 사용 기준

`app/core/config.py`는 `.env`를 읽는 설정 관리자다.

주로 아래 값을 관리한다.

```text
OPENAI_API_KEY
HF_TOKEN
JWT_SECRET_KEY
KAKAO_CLIENT_ID
KAKAO_CLIENT_SECRET
KAKAO_REDIRECT_URI
FRONTEND_BASE_URL
CORS_ALLOWED_ORIGINS
OUTPUT_DIR
GENERATION_MAX_CONCURRENT
DAILY_GENERATION_LIMIT
```

사용 예시:

```python
from app.core.config import get_settings

settings = get_settings()

output_dir = settings.output_dir
openai_api_key = settings.openai_api_key
```

주의:

- API Key, Secret, Token은 절대 Git에 올리지 않는다.
- 모델명, temperature, image size 같은 실험 설정은 `.env`에 넣지 않는다.
- 모델 관련 값은 `model.yaml`에서 관리한다.

---

## 5. `backend/config/model.yaml` 사용 기준

`model.yaml`은 모델/provider 실험 설정 파일이다.

관리 대상 예시:

```text
active_profile
text_generation_provider
image_generation_provider
OpenAI text model
OpenAI image model
HF text model_id
HF image model_id
temperature
max_tokens
image size
quality
device
dtype
performance log path
```

예시:

```yaml
active_profile: all_openai

profiles:
  all_openai:
    text_generation_provider: openai
    image_generation_provider: openai

  all_hf:
    text_generation_provider: hf
    image_generation_provider: hf
```

코드에서 직접 YAML을 열지 않는다.  
반드시 `app/core/model_config.py`의 함수를 사용한다.

```python
from app.core.model_config import (
    get_active_profile_name,
    get_text_generation_settings,
    get_image_generation_settings,
    get_model_settings,
)

profile = get_active_profile_name()
text_settings = get_text_generation_settings()
image_settings = get_image_generation_settings()
model_info = get_model_settings("text_generation")
```

---

## 6. 공통 응답 포맷

모든 API는 성공/실패 응답 형식을 통일한다.

### 6.1 성공 응답

성공 응답은 항상 아래 구조를 사용한다.

```json
{
  "success": true,
  "data": {},
  "error": null
}
```

사용 방법:

```python
from app.schemas.common import success_response

return success_response(
    data={
        "caption": caption,
        "images": images,
    }
)
```

endpoint에서 raw dict를 그대로 반환하지 않는다.

나쁜 예:

```python
return {
    "caption": caption,
    "images": images,
}
```

좋은 예:

```python
return success_response(
    data={
        "caption": caption,
        "images": images,
    }
)
```

---

### 6.2 실패 응답

실패 응답은 공통 exception handler가 아래 구조로 변환한다.

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "ERROR_CODE",
    "message": "에러 메시지",
    "detail": {}
  }
}
```

개발자는 endpoint나 pipeline에서 직접 실패 응답 dict를 만들지 않는다.  
대신 `AppException`을 발생시킨다.

```python
from app.core import error_constants as errors
from app.core.exceptions import AppException

raise AppException(
    errors.INVALID_IMAGE_FILE,
    detail={"content_type": file.content_type},
)
```

---

## 7. 공통 예외 처리 사용법

### 7.1 에러 상수 추가

새로운 에러가 필요하면 `app/core/error_constants.py`에 추가한다.

```python
from app.core.exceptions import ErrorSpec

INVALID_IMAGE_FILE = ErrorSpec(
    code="INVALID_IMAGE_FILE",
    message="이미지 파일만 업로드할 수 있습니다.",
    status_code=400,
)
```

### 7.2 AppException 사용

에러를 발생시킬 때는 문자열 코드 대신 `ErrorSpec`을 사용한다.

좋은 예:

```python
raise AppException(
    errors.INVALID_IMAGE_FILE,
    detail={"content_type": file.content_type},
)
```

가능하면 피할 예:

```python
raise AppException(
    code="INVALID_IMAGE_FILE",
    message="이미지 파일만 업로드할 수 있습니다.",
    status_code=400,
)
```

금지에 가까운 예:

```python
raise RuntimeError("이미지 파일이 아닙니다.")
raise ValueError("잘못된 입력입니다.")
raise HTTPException(status_code=400, detail="잘못된 요청입니다.")
```

단, 외부 라이브러리 내부에서 발생하는 예외는 `except Exception`으로 잡은 뒤 `AppException`으로 감싼다.

```python
try:
    result = external_api_call()
except Exception as exc:
    raise AppException(
        errors.OPENAI_IMAGE_GENERATION_FAILED,
        detail={
            "provider": "openai",
            "role": "image_generation",
            "error_type": exc.__class__.__name__,
            "error": str(exc),
        },
    ) from exc
```

---

## 8. Endpoint 작성 규칙

endpoint는 아래 역할만 담당한다.

```text
1. 요청값 수신
2. 파일/폼/body 파싱
3. 인증/쿼터/동시성 제한 적용
4. pipeline/service 호출
5. success_response로 응답 래핑
```

endpoint에 모델 호출 로직이나 복잡한 비즈니스 로직을 직접 넣지 않는다.

기본 템플릿:

```python
from fastapi import APIRouter, Form
from loguru import logger

from app.core import error_constants as errors
from app.core.exceptions import AppException
from app.schemas.common import APIResponse, success_response
from app.services.pipelines.some_pipeline import run_some_pipeline

router = APIRouter()


@router.post("", response_model=APIResponse)
async def some_endpoint(
    name: str = Form(...),
):
    try:
        result = run_some_pipeline(name=name)

        return success_response(data=result)

    except AppException:
        raise

    except Exception as exc:
        logger.exception("some_endpoint_failed | error={}", str(exc))
        raise AppException(
            errors.SOME_ENDPOINT_FAILED,
            detail={
                "error_type": exc.__class__.__name__,
                "error": str(exc),
            },
        ) from exc
```

---

## 9. Pipeline 작성 규칙

pipeline은 비즈니스 흐름을 담당한다.

예시:

```text
텍스트 생성 pipeline
→ 프롬프트 구성
→ text provider 호출
→ 생성 문구 반환

이미지 생성 pipeline
→ 이미지 경로 확인
→ prompt 구성
→ image provider 호출
→ 결과 이미지 경로 반환

통합 생성 pipeline
→ 텍스트 생성
→ 이미지 전처리
→ 이미지 생성
→ base64 변환
→ 통합 결과 반환
```

pipeline은 API 응답 포맷을 만들지 않는다.

나쁜 예:

```python
return success_response(data=result)
```

좋은 예:

```python
return {
    "caption": caption,
    "images": images,
    "partial_success": partial_success,
}
```

API 응답 래핑은 endpoint에서 처리한다.

---

## 10. Provider 작성 규칙

provider는 외부 모델 또는 외부 API 호출을 담당한다.

예시 구조:

```text
providers/openai_text_provider.py
→ OpenAI 텍스트 생성

providers/openai_image_provider.py
→ OpenAI 이미지 생성

providers/hf_text_provider.py
→ HuggingFace 텍스트 생성

providers/hf_image_provider.py
→ HuggingFace 이미지 생성
```

provider는 모델별 파일로 나누지 않는다.

나쁜 예:

```text
gpt_4o_mini_provider.py
gpt_5_mini_provider.py
sdxl_provider.py
```

좋은 예:

```text
openai_text_provider.py
openai_image_provider.py
hf_text_provider.py
hf_image_provider.py
```

모델명과 파라미터는 `model.yaml`에서 관리한다.

---

## 11. Provider Factory 사용 규칙

provider를 직접 생성하지 말고 factory를 사용한다.

```python
from app.services.providers.factory import get_text_provider, get_image_provider

text_provider = get_text_provider()
image_provider = get_image_provider()
```

나쁜 예:

```python
provider = OpenAITextProvider()
```

좋은 예:

```python
provider = get_text_provider()
```

이유:

- `active_profile`에 따라 OpenAI/HF/Hybrid 전환이 가능해야 한다.
- provider 선택 로직이 한 곳에 있어야 한다.
- 테스트와 유지보수가 쉬워진다.

---

## 12. 이미지 생성 실패 처리 기준

통합 광고 생성에서 텍스트 생성은 성공했지만 이미지 생성만 실패할 수 있다.

이 경우 API 전체를 실패로 처리하지 않는다.

대신 아래 구조를 사용한다.

```json
{
  "success": true,
  "data": {
    "caption": "광고 문구",
    "images": ["fallback_base64", "fallback_base64", "fallback_base64"],
    "partial_success": true,
    "warnings": [
      {
        "code": "UNHANDLED_EXCEPTION",
        "message": "포스터 생성 실패로 fallback 이미지를 반환했습니다.",
        "detail": {
          "request_id": "gen-...",
          "error_type": "RuntimeError",
          "error": "..."
        }
      }
    ],
    "image_generation_success": false
  },
  "error": null
}
```

기준:

```text
success=true
→ API 요청 자체는 처리 완료

partial_success=true
→ 일부 단계 실패

image_generation_success=false
→ 이미지 생성 실패

warnings
→ 실패 원인 확인용
```

프론트에서는 `success`만 보지 말고 `partial_success`도 확인해야 한다.

---

## 13. 성능 로그 사용법

성능 로그는 `app/utils/performance_logger.py`를 사용한다.

기본 사용:

```python
from app.utils.performance_logger import measure_stage

with measure_stage(
    pipeline="ad_generate",
    stage="text_generation",
    request_id=request_id,
    profile=profile_name,
    provider="openai",
    model="gpt-4o-mini",
):
    caption = run_text_pipeline(...)
```

직접 기록이 필요할 때:

```python
from app.utils.performance_logger import record_performance_metric

record_performance_metric(
    pipeline="ad_generate",
    stage="total_pipeline",
    request_id=request_id,
    profile="all_openai",
    provider="mixed",
    model="mixed",
    elapsed_ms=1234.56,
    success=True,
)
```

성능 로그 파일 경로:

```text
backend/logs/performance.jsonl
```

주의:

- `performance.jsonl`은 Git에 올리지 않는다.
- `backend/logs/.gitkeep`만 Git에 포함한다.
- 로그 경로는 `model.yaml`의 `logging.performance.path`에서 관리한다.

---

## 14. 성능 로그 확인

```bash
ls -lh logs/performance.jsonl
tail -n 20 logs/performance.jsonl
```

요약 확인:

```bash
python - <<'PY'
import json
from collections import Counter
from pathlib import Path

path = Path("logs/performance.jsonl")

if not path.exists():
    print("performance.jsonl not found")
    raise SystemExit

rows = [
    json.loads(line)
    for line in path.read_text(encoding="utf-8").splitlines()
    if line.strip()
]

print("rows:", len(rows))
print("stages:", Counter(row["stage"] for row in rows))

for row in rows[-20:]:
    print({
        "stage": row["stage"],
        "profile": row.get("profile"),
        "provider": row.get("provider"),
        "model": row.get("model"),
        "elapsed_ms": row.get("elapsed_ms"),
        "success": row.get("success"),
        "error_code": row.get("error_code"),
        "error_type": row.get("error_type"),
    })
PY
```

---

## 15. Docker 실행 방법

프로젝트 루트에서 실행한다.

```bash
cd ~/biz-ad-ai
```

backend build:

```bash
docker compose build backend
```

backend 실행:

```bash
docker compose up -d backend
```

Docker 내부 config 확인:

```bash
docker compose exec -T backend python - <<'PY'
from app.core.model_config import (
    resolve_model_config_path,
    get_active_profile_name,
    get_text_generation_settings,
    get_image_generation_settings,
)

print("config path:", resolve_model_config_path())
print("active_profile:", get_active_profile_name())
print("text:", get_text_generation_settings())
print("image:", get_image_generation_settings())
PY
```

정상 기준:

```text
config path: /app/config/model.yaml
active_profile: all_openai
```

Docker 종료:

```bash
docker compose down
```

---

## 16. 테스트 실행

backend 경로에서 실행한다.

```bash
cd ~/biz-ad-ai/backend
python -m pytest -q
```

특정 테스트만 실행:

```bash
python -m pytest tests/test_model_config.py -q
python -m pytest tests/test_performance_logger.py -q
python -m pytest tests/test_common_api_response_format.py -q
```

---

## 17. 새 API 추가 시 체크리스트

새 endpoint를 추가할 때 아래를 확인한다.

```text
1. endpoint에서 success_response(data=...)를 사용하는가?
2. 실패 시 AppException을 사용하는가?
3. 새로운 에러는 error_constants.py에 ErrorSpec으로 추가했는가?
4. endpoint에 비즈니스 로직을 직접 넣지 않았는가?
5. pipeline/service/provider로 역할을 분리했는가?
6. 모델/provider 설정을 직접 하드코딩하지 않았는가?
7. model.yaml 또는 config.py 중 올바른 위치에 설정을 추가했는가?
```

---

## 18. 프론트 연동 시 주의사항

백엔드 응답은 항상 공통 포맷이다.

프론트에서는 항상 `response["data"]` 내부를 읽는다.

```python
if response["success"]:
    data = response["data"]
    caption = data.get("caption")
    images = data.get("images")
else:
    error = response["error"]
    message = error.get("message")
```

통합 생성 API는 `partial_success`도 확인해야 한다.

```python
data = response["data"]

if data.get("partial_success"):
    warnings = data.get("warnings", [])
```

