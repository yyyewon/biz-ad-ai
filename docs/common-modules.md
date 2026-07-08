# Common Modules

## 1. 문서 목적

이 문서는 Biz Ad AI 백엔드에서 공통으로 사용하는 모듈과 함수의 역할, 사용법, 주의사항을 정리한다.

공통 모듈은 여러 endpoint, pipeline, provider에서 재사용한다.  
새 기능을 추가할 때 기존 공통 모듈을 먼저 확인하고, 중복 구현을 피한다.

---

## 2. `app.core.config`

파일:

```text
backend/app/core/config.py
```

역할:

```text
.env 기반 환경 설정 관리
API key, secret, CORS, 서비스 이름 등 환경별 설정 제공
```

사용 예:

```python
from app.core.config import get_settings

settings = get_settings()
openai_api_key = settings.openai_api_key
```

주의:

```text
생성 이미지는 서버 디스크에 저장하지 않으므로 output_dir 기반 이미지 저장 흐름을 사용하지 않는다.
API key와 secret은 config.py를 통해 읽고, 코드에 직접 작성하지 않는다.
```

---

## 3. `app.core.model_config`

파일:

```text
backend/app/core/model_config.py
```

역할:

```text
backend/config/model.yaml 로드
active_profile 확인
provider 선택
role별 모델 설정 조회
```

주요 함수:

```python
get_model_config()
get_active_profile_name()
get_active_profile()
get_provider_name(role)
get_model_settings(role, provider_name=None, model_name=None)
get_text_generation_settings()
get_image_generation_settings()
get_image_preprocess_settings()
get_output_image_settings()
get_performance_logging_settings()
```

사용 예:

```python
from app.core.model_config import get_model_settings

model_info = get_model_settings(role="text_generation")
provider = model_info["provider"]
model_name = model_info["model_name"]
settings = model_info["settings"]
```

주의:

```text
model.yaml이 provider/model 선택의 기준이다.
코드에 모델명을 직접 하드코딩하지 않는다.
```

---

## 4. `app.core.error_constants`

파일:

```text
backend/app/core/error_constants.py
```

역할:

```text
공통 에러 코드와 메시지 정의
```

사용 예:

```python
from app.core import error_constants as errors
from app.core.exceptions import AppException

raise AppException(
    errors.IMAGE_PIPELINE_FAILED,
    detail={"request_id": request_id},
)
```

새 에러 추가 예:

```python
HF_IMAGE_GENERATION_FAILED = ErrorSpec(
    code="HF_IMAGE_GENERATION_FAILED",
    message="HuggingFace 이미지 생성 중 오류가 발생했습니다.",
    status_code=500,
)
```

---

## 5. `app.core.exceptions`

파일:

```text
backend/app/core/exceptions.py
```

역할:

```text
AppException 정의
FastAPI 공통 exception handler 등록
validation error 공통 응답 변환
HTTPException 공통 응답 변환
예상하지 못한 exception 공통 응답 변환
```

사용 예:

```python
raise AppException(
    errors.OPENAI_IMAGE_GENERATION_FAILED,
    detail={
        "provider": "openai",
        "model": model_name,
        "error": str(exc),
    },
)
```

Endpoint에서는 일반 예외를 잡아 `AppException`으로 변환한다.

---

## 6. `app.schemas.common`

파일:

```text
backend/app/schemas/common.py
```

역할:

```text
공통 API 응답 schema
success_response()
error_response()
```

성공 응답 예:

```python
from app.schemas.common import success_response

return success_response(data=result)
```

응답 구조:

```json
{
  "success": true,
  "data": {},
  "error": null
}
```

---

## 7. `app.utils.image_bytes`

파일:

```text
backend/app/utils/image_bytes.py
```

역할:

```text
서버 디스크에 이미지 파일을 저장하지 않고 bytes/base64/PIL/BytesIO 변환을 처리한다.
```

현재 이미지 처리 기준:

```text
입력: bytes
전처리 결과: bytes
provider 결과: list[bytes]
API 응답: base64 string
```

### 7.1 `encode_image_bytes_to_base64`

```python
def encode_image_bytes_to_base64(image_bytes: bytes) -> str:
    ...
```

이미지 bytes를 API 응답용 base64 문자열로 변환한다.

### 7.2 `decode_base64_to_image_bytes`

```python
def decode_base64_to_image_bytes(image_base64: str) -> bytes:
    ...
```

base64 문자열을 이미지 bytes로 변환한다.  
`data:image/png;base64,...` 형식도 처리한다.

### 7.3 `pil_image_to_png_bytes`

```python
def pil_image_to_png_bytes(image: Image.Image) -> bytes:
    ...
```

PIL Image 객체를 PNG bytes로 변환한다.

### 7.4 `image_bytes_to_pil`

```python
def image_bytes_to_pil(image_bytes: bytes) -> Image.Image:
    ...
```

이미지 bytes를 PIL Image 객체로 변환한다.

### 7.5 `bytes_to_named_file`

```python
def bytes_to_named_file(
    image_bytes: bytes,
    filename: str = "image.png",
) -> BinaryIO:
    ...
```

이미지 bytes를 SDK에 넘길 수 있는 file-like object로 변환한다.

OpenAI Images API는 file 객체의 `name` 속성을 참조할 수 있으므로 `BytesIO` 객체에 이름을 지정한다.

금지:

```text
bytes를 임시 파일로 저장한 뒤 open(path, "rb")로 다시 읽는 구조
```

---

## 8. `app.utils.text_sanitizer`

파일:

```text
backend/app/utils/text_sanitizer.py
```

역할:

```text
LLM이 생성한 광고 문구에서 불필요한 markdown 표시를 제거한다.
```

주요 함수:

```python
sanitize_generated_caption(text: str) -> str
```

제거 대상:

```text
**bold**
__bold__
`inline code`
markdown heading
markdown list marker
과도한 빈 줄
```

제거하지 않는 것:

```text
느낌표
마침표
물결표
해시태그
이모지
```

사용 위치:

```text
backend/app/services/pipelines/text_pipeline.py
```

Provider 내부에서 후처리하지 않는다.

---

## 9. `app.utils.performance_logger`

파일:

```text
backend/app/utils/performance_logger.py
```

역할:

```text
pipeline/stage별 성능 로그 기록
JSONL 로그 저장
elapsed_ms, elapsed_sec, elapsed_human 변환
```

주요 함수:

```python
format_elapsed_time(elapsed_ms)
record_performance_metric(...)
measure_stage(...)
```

사용 예:

```python
with measure_stage(
    pipeline="ad_generate",
    stage="text_generation",
    request_id=request_id,
    profile=profile_name,
    provider="openai",
    model="gpt-5.4",
):
    caption = run_text_pipeline(...)
```

---

## 10. `app.services.providers.factory`

파일:

```text
backend/app/services/providers/factory.py
```

역할:

```text
model.yaml active_profile 기준 provider 반환
```

사용 예:

```python
from app.services.providers.factory import get_text_provider, get_image_provider

text_provider = get_text_provider()
image_provider = get_image_provider()
```

규칙:

```text
pipeline은 OpenAI/HF provider를 직접 import하지 않는다.
pipeline은 factory를 통해 provider를 얻는다.
```

---

## 11. Provider Interface

파일:

```text
backend/app/services/providers/base.py
```

### 11.1 Text Provider

```python
class TextGenerationProvider:
    def generate_text(
        self,
        *,
        prompt: str,
        system_instruction: str | None = None,
    ) -> str:
        ...
```

반환:

```text
str
```

### 11.2 Image Provider

```python
class ImageGenerationProvider:
    def generate(
        self,
        *,
        input_image_bytes: bytes,
        prompt: str,
        num_images: int,
        mask_image_bytes: bytes | None = None,
    ) -> list[bytes]:
        ...
```

반환:

```text
list[bytes]
```

이미지 파일 path를 반환하지 않는다.

---

## 12. 공통 모듈 사용 체크리스트

새 기능 구현 전 확인:

```text
1. 설정값은 config.py 또는 model_config.py로 읽는가?
2. 에러는 error_constants.py에 정의되어 있는가?
3. 실패는 AppException으로 처리하는가?
4. 성공 응답은 success_response를 쓰는가?
5. 이미지 변환은 image_bytes.py를 쓰는가?
6. 텍스트 후처리는 text_sanitizer.py를 쓰는가?
7. 성능 측정은 performance_logger.py를 쓰는가?
8. provider 선택은 factory.py를 쓰는가?
```
