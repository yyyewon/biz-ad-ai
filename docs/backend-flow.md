# Backend Flow

## 1. 문서 목적

이 문서는 Biz Ad AI 백엔드의 전체 처리 흐름을 설명한다.

핵심 기준:

```text
Endpoint
→ Pipeline
→ Provider Factory
→ Provider
→ Common Response
```

프론트는 provider가 OpenAI인지 HF인지 알 필요가 없다.  
백엔드는 `model.yaml` 설정에 따라 provider를 선택한다.

---

## 2. 전체 구조

```text
Frontend
→ FastAPI Endpoint
→ Pipeline
→ Provider Factory
→ OpenAI/HF Provider
→ Common Response
→ Frontend
```

주요 파일:

```text
backend/app/api/v1/endpoints/
backend/app/services/pipelines/
backend/app/services/providers/
backend/app/core/
backend/app/utils/
backend/config/model.yaml
```

---

## 3. 통합 광고 생성 흐름

API:

```text
POST /api/v1/ad/generate
```

전체 흐름:

```text
1. Frontend에서 form-data 전송
2. generate_ad endpoint가 요청 수신
3. UploadFile이 있으면 bytes로 읽음
4. run_generate_pipeline() 호출
5. text_pipeline에서 광고 문구 생성
6. 이미지가 있으면 image_pipeline에서 이미지 생성
8. 결과 이미지를 base64로 변환
9. success_response(data=...) 반환
```

---

## 4. 텍스트 생성 흐름

```text
generate_pipeline.py
→ run_text_pipeline()
→ get_text_provider()
→ OpenAITextProvider 또는 HFTextProvider
→ provider.generate_text()
→ sanitize_generated_caption()
→ caption 반환
```

관련 파일:

```text
backend/app/services/pipelines/generate_pipeline.py
backend/app/services/pipelines/text_pipeline.py
backend/app/services/providers/factory.py
backend/app/services/providers/openai_text_provider.py
backend/app/services/providers/hf_text_provider.py
backend/app/utils/text_sanitizer.py
```

흐름:

```text
store_name, menu_name, purpose, llm_request, tone
→ prompt 구성
→ active_profile 기준 text provider 선택
→ LLM 호출
→ markdown 후처리
→ 광고 문구 반환
```

---

## 5. 이미지 생성 흐름

현재 백엔드는 이미지를 서버 디스크에 저장하지 않는다.

```text
업로드 이미지 bytes
→ image_pipeline.py
→ OpenAIImageProvider 또는 HFImageProvider
→ 생성 이미지 bytes
→ base64 문자열
→ API 응답
```

관련 파일:

```text
backend/app/services/pipelines/generate_pipeline.py
backend/app/services/pipelines/image_pipeline.py
backend/app/services/providers/factory.py
backend/app/services/providers/openai_image_provider.py
backend/app/services/providers/hf_image_provider.py
backend/app/utils/image_bytes.py
```

---

## 6. 이미지 전처리 (개발용)

```text
UploadFile.read()
→ image_bytes
→ prepare_upload_image(image_bytes)
→ 비율 유지 리사이즈
→ PNG bytes 반환
```

배경 제거(rembg)는 사용하지 않는다. 업로드 원본 구도를 유지한다.

관련 파일:

```text
backend/app/api/v1/endpoints/dev_apis.py
backend/app/utils/image_processor.py
```

결과는 파일로 저장하지 않는다.

---

## 7. Image Pipeline 흐름

함수:

```python
generate_image_ads(
    payload: ImageAdRequest,
    source_image_bytes: bytes,
    seed: Optional[int] = None,
) -> ImageAdResponse
```

direct_poster 모드:

```text
source_image_bytes
→ PIL RGBA 변환
→ mask bytes 생성
→ poster prompt 생성
→ provider.generate(input_image_bytes, mask_image_bytes, prompt)
→ poster image bytes
→ base64 변환
→ ImageAdResponse
```

two_stage 모드:

```text
source_image_bytes
→ food generation prompt 생성
→ provider.generate()로 중간 음식 이미지 bytes 생성
→ poster prompt 생성
→ provider.generate()로 포스터 이미지 bytes 생성
→ base64 변환
→ ImageAdResponse
```

---

## 8. OpenAI Image Provider 흐름

```text
input_image_bytes
→ bytes_to_named_file()
→ OpenAI images.edit()
→ result.data[0].b64_json
→ decode_base64_to_image_bytes()
→ list[bytes] 반환
```

파일 저장 없음.

금지:

```text
output_dir 사용
Path 반환
write_bytes 사용
download_url 생성
```

---

## 9. Provider Factory 흐름

`model.yaml`의 `active_profile`에 따라 provider를 선택한다.

예시:

```yaml
active_profile: all_openai

profiles:
  all_openai:
    text_generation_provider: openai
    image_generation_provider: openai
```

factory 흐름:

```text
get_text_provider()
→ get_provider_name("text_generation")
→ openai 또는 hf 확인
→ 해당 Text Provider 반환

get_image_provider()
→ get_provider_name("image_generation")
→ openai 또는 hf 확인
→ 해당 Image Provider 반환
```

---

## 10. 지원 profile 구조

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

profile 변경만으로 provider 조합이 바뀌어야 한다.

---

## 11. 모델 설정 흐름

파일:

```text
backend/config/model.yaml
```

역할:

```text
active_profile
provider 조합
OpenAI text model
OpenAI image model
HF text model
HF image model
image_preprocess 설정
performance logging 설정
```

코드는 모델명을 직접 알지 않는다.  
`model_config.py`를 통해 설정을 읽는다.

---

## 12. 성능 로그 흐름

관련 파일:

```text
backend/app/utils/performance_logger.py
backend/logs/performance.jsonl
```

generate_pipeline은 주요 단계에서 성능 로그를 남긴다.

```text
text_generation
image_preprocess
image_generation
food_generation
poster_generation
image_pipeline_total
total_pipeline
```

fallback 발생 시:

```text
API 응답 success=true
data.partial_success=true
performance total_pipeline success=false
```

---

## 13. fallback 흐름

이미지 생성 실패 시 전체 API를 실패로 처리하지 않는다.  
광고 문구 생성이 성공했다면 fallback 이미지를 반환한다.

```text
text_generation 성공
image_preprocess 성공
image_generation 실패
→ fallback image base64 반환
→ partial_success=true
→ image_generation_success=false
→ warnings에 실패 사유 기록
```

fallback 우선순위:

```text
1. 전처리 성공 시 processed_bytes 사용
2. 전처리 실패 시 원본 image_bytes 사용
```

---

## 14. 단독 이미지 API 흐름

API:

```text
POST /api/v1/dev/ad/image
```

흐름:

```text
JSON input_image_base64 수신
→ decode_base64_to_image_bytes()
→ generate_image_ads(payload, source_image_bytes)
→ ImageAdResponse
→ success_response(data=...)
```

이 API도 서버에 이미지를 저장하지 않는다.

---

## 15. API 응답 흐름

Endpoint는 pipeline 결과를 공통 응답으로 감싼다.

```python
result = run_generate_pipeline(...)
return success_response(data=result)
```

결과:

```json
{
  "success": true,
  "data": {
    "caption": "...",
    "images": ["base64..."]
  },
  "error": null
}
```

---

## 16. 에러 처리 흐름

예상 가능한 실패:

```text
AppException 발생
→ common exception handler
→ error_response
```

예상하지 못한 실패:

```text
Exception 발생
→ endpoint에서 AppException으로 변환
→ common exception handler
→ error_response
```

---

## 17. HF 추가 흐름

HF Text Provider 추가 시:

```text
hf_text_provider.py 생성
factory.py에 hf text 분기 연결
model.yaml hf.text_generation 설정 확인
active_profile=hybrid_hf_text_openai_image 테스트
```

HF Image Provider 추가 시:

```text
hf_image_provider.py 생성
factory.py에 hf image 분기 연결
model.yaml hf.image_generation 설정 확인
active_profile=hybrid_openai_text_hf_image 테스트
```

HF Image Provider도 OpenAI Image Provider와 같은 interface를 따라야 한다.

```python
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

---

## 18. 저장 금지 구조 확인

아래 구조가 다시 생기면 안 된다.

```text
outputs/
source_rgba.png
inpaint_mask.png
poster_*.png
StaticFiles(directory=settings.output_dir)
app.mount("/outputs", ...)
download_url
Path 기반 이미지 반환
```

확인 명령어:

```bash
grep -R \
  "StaticFiles\|app.mount(\"/outputs\"\|/outputs\|output_root\|public_prefix\|source_rgba.png\|inpaint_mask.png\|poster_.*\.png\|settings.output_dir" \
  -n backend/app backend/tests docs docker-compose.yml || true
```

정상 기준:

```text
실제 코드에서 저장 로직이 나오면 안 된다.
문서에서 설명용으로만 나오는 것은 허용한다.
```
