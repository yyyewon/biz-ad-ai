# HF Pipeline Reference

## 1. 목적

이 문서는 기존 OpenAI 기반 광고 생성 파이프라인에 HuggingFace Provider를 추가할 때 따라야 하는 구조와 구현 기준을 정리한다.

현재 백엔드는 provider 교체가 가능하도록 구성되어 있다.  
따라서 HF 로직을 추가할 때는 API endpoint나 frontend를 크게 수정하지 않고, provider 계층과 factory 연결을 중심으로 확장한다.

---

## 2. 전체 호출 흐름

현재 광고 생성 흐름은 아래 구조를 따른다.

```text
Frontend
→ FastAPI Endpoint
→ generate_pipeline.py
→ text_pipeline.py / image_pipeline.py
→ provider factory
→ OpenAI Provider 또는 HF Provider
```

HF를 붙인 뒤에도 흐름은 동일해야 한다.

```text
API endpoint
→ pipeline
→ factory
→ HFTextProvider / HFImageProvider
```

즉, HF 추가 작업은 pipeline 전체를 새로 만드는 작업이 아니라 provider를 확장하는 작업이다.

---

## 3. 핵심 설계 기준

HF 추가 시 지켜야 할 기준은 다음과 같다.

```text
1. API endpoint는 수정하지 않는 것을 원칙으로 한다.
2. frontend 응답 구조도 바꾸지 않는다.
3. pipeline은 provider 종류를 몰라야 한다.
4. provider 선택은 factory.py에서만 처리한다.
5. 모델명과 파라미터는 model.yaml에서 관리한다.
6. OpenAI/HF 모두 동일한 provider interface를 맞춘다.
7. 생성된 광고 문구 후처리는 공통 sanitizer를 사용한다.
8. 성능 로그는 기존 performance_logger 구조를 그대로 사용한다.
9. 이미지는 서버 디스크에 저장하지 않는다.
10. Image Provider는 list[bytes]를 반환한다.
```

---

## 4. 이미지 저장 정책

현재 백엔드는 생성 이미지를 서버 디스크에 저장하지 않는다.

처리 기준:

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

따라서 HF Image Provider도 파일 경로가 아니라 이미지 bytes를 받아서 이미지 bytes 목록을 반환해야 한다.

---

## 5. 새로 생성할 파일

HF Provider를 추가할 때 기본적으로 아래 파일을 새로 만든다.

```text
backend/app/services/providers/hf_text_provider.py
backend/app/services/providers/hf_image_provider.py
backend/tests/test_hf_provider_factory.py
backend/tests/test_hf_text_provider.py
backend/tests/test_hf_image_provider.py
```

필요하면 아래 테스트도 추가한다.

```text
backend/tests/test_hf_image_provider_memory.py
backend/tests/test_hf_text_pipeline_integration.py
backend/tests/test_hf_image_pipeline_integration.py
```

---

## 6. `hf_text_provider.py`

역할:

```text
HuggingFace 텍스트 생성 모델 호출
```

예상 책임:

```text
- model.yaml에서 전달받은 model_id 사용
- HF_TOKEN 사용
- tokenizer/model 로드
- prompt + system_instruction 처리
- 광고 문구 텍스트 반환
- HF 텍스트 생성 실패 시 AppException 발생
```

반환값:

```text
str
```

주의:

```text
공통 응답 포맷을 만들지 않는다.
markdown 후처리를 provider에서 하지 않는다.
텍스트 후처리는 text_pipeline.py에서 sanitize_generated_caption()으로 처리한다.
```

---

## 7. `hf_image_provider.py`

역할:

```text
HuggingFace 이미지 생성 모델 호출
```

예상 책임:

```text
- model.yaml에서 전달받은 model_id 사용
- HF_TOKEN 사용 여부 확인
- diffusers pipeline 로드
- text-to-image, image-to-image, inpainting 중 필요한 방식 구현
- 입력 이미지 bytes를 PIL Image로 변환
- 생성 결과 PIL Image를 PNG bytes로 변환
- 생성된 이미지 bytes 목록 반환
- HF 이미지 생성 실패 시 AppException 발생
```

반환값:

```text
list[bytes]
```

주의:

```text
결과 이미지를 output_dir에 저장하지 않는다.
저장된 이미지 path 목록을 반환하지 않는다.
download_url을 만들지 않는다.
```

---

## 8. 수정해야 하는 파일

HF 추가 시 기본 수정 대상은 아래 파일이다.

```text
backend/app/services/providers/factory.py
backend/config/model.yaml
backend/app/core/error_constants.py
backend/requirements.txt
```

필요한 경우에만 아래 파일도 수정한다.

```text
backend/app/core/config.py
backend/app/core/model_config.py
backend/Dockerfile
docs/development-rules.md
docs/common-modules.md
docs/backend-flow.md
docs/api-spec.md
```

---

## 9. `factory.py` 수정 기준

파일:

```text
backend/app/services/providers/factory.py
```

provider 선택은 factory에서만 처리한다.

### 9.1 Text Provider

기존 구조가 아래와 같다면:

```python
if provider_name == "openai":
    return OpenAITextProvider(...)

if provider_name == "hf":
    raise AppException(errors.HF_PROVIDER_NOT_AVAILABLE)
```

HF 추가 후에는 아래처럼 변경한다.

```python
if provider_name == "openai":
    return OpenAITextProvider(...)

if provider_name == "hf":
    return HFTextProvider(...)
```

---

### 9.2 Image Provider

기존 구조가 아래와 같다면:

```python
if provider_name == "openai":
    return OpenAIImageProvider(...)

if provider_name == "hf":
    raise AppException(errors.HF_PROVIDER_NOT_AVAILABLE)
```

HF 추가 후에는 아래처럼 변경한다.

```python
if provider_name == "openai":
    return OpenAIImageProvider(...)

if provider_name == "hf":
    return HFImageProvider(...)
```

---

## 10. `model.yaml` 설정 기준

파일:

```text
backend/config/model.yaml
```

HF provider 선택은 profile에서 관리한다.

```yaml
profiles:
  all_openai:
    text_generation_provider: openai
    image_generation_provider: openai

  all_hf:
    text_generation_provider: hf
    image_generation_provider: hf

  hybrid_openai_text_hf_image:
    text_generation_provider: openai
    image_generation_provider: hf

  hybrid_hf_text_openai_image:
    text_generation_provider: hf
    image_generation_provider: openai
```

`active_profile`만 바꿔서 provider 조합이 바뀌어야 한다.

```yaml
active_profile: hybrid_hf_text_openai_image
```

---

## 11. HF Text 설정 예시

```yaml
hf:
  token_env: HF_TOKEN

  text_generation:
    default_model: qwen3_4b
    models:
      qwen3_4b:
        model_id: Qwen/Qwen3-4B-Instruct-2507
        task_type: text-generation
        backend: transformers
        device: auto
        dtype: auto
        max_new_tokens: 800
        temperature: 0.7
        top_p: 0.9
        do_sample: true
```

HFTextProvider는 위 설정을 읽어 모델을 로드하고 텍스트를 생성한다.

코드 내부에 모델명을 직접 하드코딩하지 않는다.

나쁜 예:

```python
model_id = "Qwen/Qwen3-4B-Instruct-2507"
```

좋은 예:

```python
model_id = self.model_settings["model_id"]
```

---

## 12. HF Image 설정 예시

```yaml
hf:
  token_env: HF_TOKEN

  image_generation:
    default_model: sdxl_lightning
    models:
      sdxl_lightning:
        model_id: ByteDance/SDXL-Lightning
        task_type: text-to-image
        backend: diffusers
        pipeline_class: StableDiffusionXLPipeline
        width: 1024
        height: 1280
        num_inference_steps: 4
        guidance_scale: 1.0
```

HFImageProvider는 위 설정을 읽어 이미지 생성 pipeline을 구성한다.

초기에는 `text-to-image` 기준으로 구현하고, 이후 필요하면 `image-to-image` 또는 `inpainting`을 확장한다.

---

## 13. Provider Interface 기준

HF provider는 기존 OpenAI provider와 같은 interface를 맞춰야 한다.  
이 interface가 맞아야 기존 pipeline을 수정하지 않고 그대로 사용할 수 있다.

---

### 13.1 Text Provider Interface

```python
class HFTextProvider:
    def generate_text(
        self,
        *,
        prompt: str,
        system_instruction: str | None = None,
    ) -> str:
        ...
```

반환값은 반드시 string이어야 한다.

```python
return generated_text
```

공통 응답 포맷은 provider에서 만들지 않는다.

나쁜 예:

```python
return {
    "success": True,
    "data": generated_text,
}
```

좋은 예:

```python
return generated_text
```

---

### 13.2 Image Provider Interface

```python
class HFImageProvider:
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

반환값은 반드시 생성된 이미지 bytes 목록이어야 한다.

```python
return image_bytes_list
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

### 13.3 Background Generation Interface

현재 base interface에 맞추려면 background 생성 메서드도 구현한다.

```python
class HFImageProvider:
    def generate_backgrounds(
        self,
        *,
        prompt: str,
        num_images: int,
    ) -> list[bytes]:
        ...
```

초기 HF 구현에서 background 생성을 사용하지 않더라도 interface 일관성을 위해 구현한다.

---

## 14. 이미지 bytes 공통 유틸 사용 기준

파일:

```text
backend/app/utils/image_bytes.py
```

HF Image Provider에서는 직접 base64/PIL/BytesIO 변환 로직을 중복 구현하지 않고 공통 유틸을 사용한다.

주요 함수:

```python
encode_image_bytes_to_base64(image_bytes: bytes) -> str
decode_base64_to_image_bytes(image_base64: str) -> bytes
pil_image_to_png_bytes(image: Image.Image) -> bytes
image_bytes_to_pil(image_bytes: bytes) -> Image.Image
bytes_to_named_file(image_bytes: bytes, filename: str = "image.png")
```

HF Image Provider 사용 예:

```python
from app.utils.image_bytes import image_bytes_to_pil, pil_image_to_png_bytes

source_image = image_bytes_to_pil(input_image_bytes).convert("RGB")
result_image = pipe(prompt=prompt, image=source_image).images[0]
result_bytes = pil_image_to_png_bytes(result_image)

return [result_bytes]
```

---

## 15. 기존 pipeline 수정 기준

HF 추가 후에도 아래 파일은 거의 수정하지 않는 것을 원칙으로 한다.

```text
backend/app/services/pipelines/text_pipeline.py
backend/app/services/pipelines/image_pipeline.py
backend/app/services/pipelines/generate_pipeline.py
```

---

### 15.1 `text_pipeline.py`

현재 구조:

```python
provider = get_text_provider()

raw_result = provider.generate_text(
    prompt=prompt,
    system_instruction=system_instruction,
)

result = sanitize_generated_caption(raw_result)
```

HF 추가 후에도 이 구조는 그대로 유지한다.

OpenAI 사용 시:

```text
get_text_provider()
→ OpenAITextProvider
```

HF 사용 시:

```text
get_text_provider()
→ HFTextProvider
```

---

### 15.2 `image_pipeline.py`

현재 구조:

```python
provider = get_image_provider()

image_bytes_list = provider.generate(
    input_image_bytes=source_image_bytes,
    mask_image_bytes=mask_image_bytes,
    prompt=poster_prompt,
    num_images=1,
)
```

HFImageProvider가 같은 `generate()` interface를 제공하면 `image_pipeline.py`는 provider 종류를 몰라도 된다.

---

### 15.3 `generate_pipeline.py`

현재 구조:

```python
caption = run_text_pipeline(...)
image_result = generate_image_ads(
    payload=image_payload,
    source_image_bytes=processed_bytes,
)
```

텍스트와 이미지는 각각 내부에서 provider factory를 사용한다.  
따라서 HF 추가 때문에 통합 pipeline을 크게 수정하지 않는다.

---

## 16. Endpoint 수정 기준

아래 endpoint는 HF 추가 때문에 수정하지 않는 것을 원칙으로 한다.

```text
backend/app/api/v1/endpoints/generate_ad.py
backend/app/api/v1/endpoints/text_ad.py
backend/app/api/v1/endpoints/image_ad.py
```

이유:

```text
endpoint는 요청/응답만 담당한다.
모델 선택은 factory가 담당한다.
실제 모델 호출은 provider가 담당한다.
```

HF를 추가하면서 endpoint에 OpenAI/HF 분기문이 들어가면 구조가 잘못된 것이다.

나쁜 예:

```python
if provider == "hf":
    ...
else:
    ...
```

endpoint에는 이런 분기문을 넣지 않는다.

---

## 17. Frontend 수정 기준

HF 추가 후에도 frontend는 수정하지 않는 것을 원칙으로 한다.

응답 포맷이 동일하기 때문이다.

```json
{
  "success": true,
  "data": {
    "caption": "...",
    "images": [
      "base64_encoded_image_1",
      "base64_encoded_image_2"
    ]
  },
  "error": null
}
```

프론트는 provider가 OpenAI인지 HF인지 몰라도 된다.

---

## 18. 에러 상수 추가 기준

파일:

```text
backend/app/core/error_constants.py
```

HF 관련 에러는 ErrorSpec으로 추가한다.

예시:

```python
HF_TOKEN_MISSING = ErrorSpec(
    code="HF_TOKEN_MISSING",
    message="HuggingFace token이 설정되지 않았습니다.",
    status_code=500,
)

HF_TEXT_MODEL_LOAD_FAILED = ErrorSpec(
    code="HF_TEXT_MODEL_LOAD_FAILED",
    message="HuggingFace 텍스트 모델 로드에 실패했습니다.",
    status_code=500,
)

HF_TEXT_GENERATION_FAILED = ErrorSpec(
    code="HF_TEXT_GENERATION_FAILED",
    message="HuggingFace 텍스트 생성 중 오류가 발생했습니다.",
    status_code=500,
)

HF_IMAGE_MODEL_LOAD_FAILED = ErrorSpec(
    code="HF_IMAGE_MODEL_LOAD_FAILED",
    message="HuggingFace 이미지 모델 로드에 실패했습니다.",
    status_code=500,
)

HF_IMAGE_GENERATION_FAILED = ErrorSpec(
    code="HF_IMAGE_GENERATION_FAILED",
    message="HuggingFace 이미지 생성 중 오류가 발생했습니다.",
    status_code=500,
)
```

이미 같은 의미의 상수가 있으면 중복 추가하지 않는다.

---

## 19. requirements.txt 추가 기준

HF를 실제로 실행하려면 의존성이 필요하다.

텍스트 모델용 예시:

```text
transformers
accelerate
sentencepiece
protobuf
safetensors
```

이미지 모델용 예시:

```text
diffusers
torch
torchvision
Pillow
```

주의:

```text
torch는 실행 환경에 따라 설치 방식이 달라질 수 있다.
Mac 로컬, CPU 서버, CUDA 서버에서 설치 전략이 다를 수 있다.
```

초기에는 import와 mock 테스트를 먼저 통과시키고, 이후 실제 모델 로드 테스트를 진행한다.

---

## 20. config.py 수정 기준

파일:

```text
backend/app/core/config.py
```

`HF_TOKEN`이 이미 있으면 수정하지 않는다.

없다면 아래 필드를 추가한다.

```python
hf_token: str | None = Field(default=None, alias="HF_TOKEN")
```

HF token은 `.env`에 둔다.

```env
HF_TOKEN=...
```

API Key나 token은 `model.yaml`에 직접 적지 않는다.

---

## 21. 구현 순서

한 번에 HF Text/Image를 모두 붙이면 디버깅 범위가 커진다.  
아래 순서로 진행한다.

---

### Step 1. HF Text Provider 추가

작업 파일:

```text
backend/app/services/providers/hf_text_provider.py
backend/app/services/providers/factory.py
backend/config/model.yaml
backend/app/core/error_constants.py
backend/requirements.txt
```

테스트 profile:

```yaml
active_profile: hybrid_hf_text_openai_image
```

기대 결과:

```text
text_generation provider=hf
image_generation provider=openai
```

---

### Step 2. HF Text 성능 로그 확인

확인 파일:

```text
backend/logs/performance.jsonl
```

기대 로그:

```json
{
  "stage": "text_generation",
  "provider": "hf",
  "model": "qwen3_4b",
  "success": true,
  "elapsed_human": "..."
}
```

---

### Step 3. HF Image Provider 추가

작업 파일:

```text
backend/app/services/providers/hf_image_provider.py
backend/app/services/providers/factory.py
backend/config/model.yaml
backend/app/core/error_constants.py
backend/requirements.txt
```

테스트 profile:

```yaml
active_profile: hybrid_openai_text_hf_image
```

기대 결과:

```text
text_generation provider=openai
image_generation provider=hf
```

---

### Step 4. only HF 테스트

테스트 profile:

```yaml
active_profile: all_hf
```

기대 결과:

```text
text_generation provider=hf
image_generation provider=hf
total_pipeline success=true
```

---

## 22. 테스트 체크리스트

HF 추가 후 아래 항목을 확인한다.

```text
1. pytest 전체 통과
2. model.yaml active_profile 변경 시 provider가 바뀌는지 확인
3. HF Text Provider가 generate_text()를 제공하는지 확인
4. HF Image Provider가 generate()를 제공하는지 확인
5. HF Image Provider가 list[bytes]를 반환하는지 확인
6. text_pipeline.py 수정 없이 HF text가 동작하는지 확인
7. image_pipeline.py 수정 없이 HF image가 동작하는지 확인
8. /api/v1/ad/generate 응답 포맷이 기존과 동일한지 확인
9. performance.jsonl에 provider=hf, model=... 이 찍히는지 확인
10. frontend 수정 없이 결과가 표시되는지 확인
11. outputs/ 또는 /outputs URL 의존이 생기지 않았는지 확인
```

---

## 23. 테스트 명령어 예시

provider factory 테스트:

```bash
python -m pytest tests/test_hf_provider_factory.py -q
```

HF text provider 테스트:

```bash
python -m pytest tests/test_hf_text_provider.py -q
```

HF image provider 테스트:

```bash
python -m pytest tests/test_hf_image_provider.py -q
```

전체 테스트:

```bash
python -m pytest -q
```

저장 의존성 확인:

```bash
grep -R \
  "StaticFiles\|app.mount(\"/outputs\"\|/outputs\|output_root\|public_prefix\|source_rgba.png\|inpaint_mask.png\|poster_.*\.png\|settings.output_dir" \
  -n backend/app backend/tests docs docker-compose.yml || true
```

---

## 24. 성능 로그 확인

광고 생성 API 호출 후 성능 로그를 확인한다.

```bash
tail -n 20 logs/performance.jsonl
```

요약 확인:

```bash
python - <<'PY'
import json
from pathlib import Path

path = Path("logs/performance.jsonl")

rows = [
    json.loads(line)
    for line in path.read_text(encoding="utf-8").splitlines()
    if line.strip()
]

for row in rows[-20:]:
    print({
        "stage": row.get("stage"),
        "provider": row.get("provider"),
        "model": row.get("model"),
        "elapsed_human": row.get("elapsed_human"),
        "success": row.get("success"),
        "error_code": row.get("error_code"),
        "error_type": row.get("error_type"),
    })
PY
```

---

## 25. 최종 목표 구조

HF 추가 후에도 최종 구조는 아래처럼 유지한다.

```text
endpoint
→ pipeline
→ factory
→ provider
```

provider만 바꾸면 OpenAI/HF/Hybrid 조합이 바뀌어야 한다.

```text
all_openai
→ text: OpenAI
→ image: OpenAI

all_hf
→ text: HF
→ image: HF

hybrid_openai_text_hf_image
→ text: OpenAI
→ image: HF

hybrid_hf_text_openai_image
→ text: HF
→ image: OpenAI
```

---

## 26. 주의사항

HF 추가 시 피해야 할 구조:

```text
1. endpoint에 OpenAI/HF 분기문 추가
2. frontend에서 provider 종류에 따라 응답 처리 분기
3. pipeline에서 특정 모델명을 하드코딩
4. provider가 API 공통 응답 포맷을 직접 생성
5. model.yaml 대신 코드에 model_id 직접 입력
6. HF token을 model.yaml이나 코드에 직접 입력
7. OpenAI provider와 HF provider의 method signature가 달라지는 구조
8. 이미지 생성 결과를 output_dir에 저장
9. Path 목록 반환
10. download_url 생성
11. /outputs URL 반환
```

권장 구조:

```text
1. provider는 외부 모델 호출만 담당
2. factory는 provider 선택만 담당
3. pipeline은 비즈니스 흐름만 담당
4. endpoint는 요청/응답만 담당
5. model.yaml은 모델 선택과 실험 파라미터 담당
6. .env는 token과 secret 담당
7. 이미지 입력/출력은 bytes 기반으로 처리
8. API 응답 이미지는 base64 string으로 반환
```
