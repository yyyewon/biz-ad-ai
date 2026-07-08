# Development Rules

## 1. 문서 목적

이 문서는 Biz Ad AI 백엔드 개발 시 지켜야 하는 공통 개발 규칙을 정리한다.

현재 백엔드는 다음 구조를 기준으로 한다.

```text
Endpoint
→ Pipeline
→ Provider Factory
→ Provider
→ Common Response
```

개발자는 endpoint, pipeline, provider의 책임을 분리해서 구현한다.

---

## 2. 계층별 책임

### 2.1 Endpoint

Endpoint는 요청과 응답만 담당한다.

해야 할 일:

```text
- Request parameter 수신
- UploadFile 또는 JSON body 읽기
- Pipeline 호출
- success_response(data=...) 반환
- 예상하지 못한 예외를 AppException으로 변환
```

하지 말아야 할 일:

```text
- OpenAI/HF 모델 직접 호출
- provider 직접 생성
- model.yaml 직접 파싱
- 이미지 파일 저장
- /outputs URL 생성
- 복잡한 비즈니스 로직 작성
```

### 2.2 Pipeline

Pipeline은 비즈니스 흐름을 담당한다.

예시:

```text
generate_pipeline.py
→ 텍스트 생성
→ 이미지 전처리
→ 이미지 생성
→ fallback 처리
→ 성능 로그 기록
→ 통합 응답 dict 구성
```

Pipeline은 provider 종류를 몰라야 한다.

나쁜 예:

```python
if provider == "openai":
    ...
elif provider == "hf":
    ...
```

좋은 예:

```python
provider = get_image_provider()
result = provider.generate(...)
```

### 2.3 Provider Factory

Provider Factory는 provider 선택만 담당한다.

파일:

```text
backend/app/services/providers/factory.py
```

역할:

```text
model.yaml active_profile 확인
→ text_generation_provider 결정
→ image_generation_provider 결정
→ OpenAI 또는 HF provider 반환
```

### 2.4 Provider

Provider는 외부 모델 호출만 담당한다.

예시:

```text
OpenAITextProvider
OpenAIImageProvider
HFTextProvider
HFImageProvider
```

Provider에서 하지 말아야 할 일:

```text
- API 공통 응답 포맷 생성
- FastAPI response 직접 반환
- 서버 디스크에 이미지 저장
- endpoint 전용 로직 처리
```

---

## 3. 공통 응답 규칙

모든 API 응답은 아래 형식을 따른다.

### 3.1 성공 응답

```json
{
  "success": true,
  "data": {},
  "error": null
}
```

성공 응답은 `success_response(data=...)`를 사용한다.

```python
from app.schemas.common import success_response

return success_response(data=result)
```

### 3.2 실패 응답

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

실패는 `AppException`을 사용한다.

```python
from app.core.exceptions import AppException
from app.core import error_constants as errors

raise AppException(
    errors.IMAGE_PIPELINE_FAILED,
    detail={"request_id": request_id},
)
```

---

## 4. 예외 처리 규칙

### 4.1 직접 문자열 예외 금지

나쁜 예:

```python
raise RuntimeError("image failed")
raise ValueError("invalid config")
```

좋은 예:

```python
raise AppException(
    errors.IMAGE_PIPELINE_FAILED,
    detail={"error": str(exc)},
)
```

### 4.2 에러 상수 사용

에러 코드는 `backend/app/core/error_constants.py`에서 관리한다.

새로운 에러가 필요하면 `ErrorSpec`을 추가한다.

```python
MY_ERROR = ErrorSpec(
    code="MY_ERROR",
    message="에러 메시지",
    status_code=500,
)
```

---

## 5. 이미지 저장 정책

현재 백엔드는 생성 이미지를 서버 디스크에 저장하지 않는다.

기준:

```text
업로드 이미지 bytes
→ 전처리 bytes
→ 이미지 생성 bytes
→ base64 응답
```

금지 사항:

```text
outputs/ 폴더에 생성 이미지 저장 금지
source_rgba.png 저장 금지
inpaint_mask.png 저장 금지
poster_*.png 저장 금지
/outputs 정적 파일 URL 사용 금지
download_url 기반 신규 응답 금지
Path 기반 이미지 반환 금지
```

---

## 6. Image Provider 규칙

Image Provider는 반드시 `list[bytes]`를 반환한다.

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

나쁜 예:

```python
return [Path("outputs/poster_1.png")]
```

좋은 예:

```python
return [image_bytes]
```

---

## 7. Text Provider 규칙

Text Provider는 반드시 `str`을 반환한다.

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

Provider가 markdown 후처리를 직접 담당하지 않는다.  
생성 문구 후처리는 `text_pipeline.py`에서 `sanitize_generated_caption()`을 사용한다.

---

## 8. 모델 설정 규칙

모델명, provider 선택, 모델 파라미터는 `backend/config/model.yaml`에서 관리한다.

나쁜 예:

```python
model = "gpt-image-1-mini"
```

좋은 예:

```python
model_info = get_model_settings(role="image_generation")
model = model_info["model_name"]
```

---

## 9. 환경변수 규칙

`.env`에는 secret과 환경별 설정만 둔다.

예시:

```env
OPENAI_API_KEY=...
HF_TOKEN=...
KAKAO_CLIENT_ID=...
JWT_SECRET_KEY=...
```

금지 사항:

```text
API key를 코드에 하드코딩 금지
API key를 model.yaml에 직접 작성 금지
API key를 문서에 기록 금지
```

---

## 10. 성능 로그 규칙

성능 로그는 `performance_logger.py`를 사용한다.

주요 stage:

```text
text_generation
image_preprocess
image_generation
food_generation
poster_generation
image_pipeline_total
total_pipeline
```

로그에는 최소한 아래 정보가 들어가야 한다.

```text
request_id
pipeline
profile
stage
provider
model
elapsed_ms
elapsed_sec
elapsed_human
success
error_code
error_type
```

---

## 11. 테스트 규칙

새 로직을 추가하면 테스트를 함께 추가한다.

권장 기준:

```text
Provider 추가 → provider 단위 테스트
Factory 분기 추가 → factory 테스트
Pipeline 수정 → pipeline 테스트
Endpoint 수정 → endpoint response 테스트
공통 유틸 추가 → utils 테스트
```

실제 외부 API를 호출하는 테스트는 기본 단위 테스트에 넣지 않는다.  
OpenAI/HF 호출은 mock 또는 fake client를 사용한다.

---

## 12. HF 추가 규칙

HF를 추가해도 endpoint와 frontend 응답 구조는 바꾸지 않는다.

HF 추가 시 핵심 수정 파일:

```text
backend/app/services/providers/hf_text_provider.py
backend/app/services/providers/hf_image_provider.py
backend/app/services/providers/factory.py
backend/config/model.yaml
backend/app/core/error_constants.py
backend/requirements.txt
```

HF Image Provider도 `list[bytes]`를 반환해야 한다.

---

## 13. PR 전 체크리스트

PR 전 아래 항목을 확인한다.

```text
1. pytest 통과
2. API 응답 포맷 유지
3. AppException 사용
4. 이미지 파일 저장 없음
5. /outputs URL 의존 없음
6. provider가 bytes/string만 반환
7. model.yaml 기반 provider/model 선택
8. performance.jsonl 기록 정상
9. frontend 응답 처리 호환
10. 문서 최신화
```
