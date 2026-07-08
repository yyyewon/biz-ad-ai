# Logging Reference

## 1. 목적

이 문서는 현재 백엔드에서 기록하는 공통 로그 항목을 정리한다.

현재 로그는 크게 두 종류로 나뉜다.

```text
1. 일반 실행 로그
   - loguru logger.info / logger.warning / logger.exception 기반
   - 서버 실행 흐름, 요청 완료, provider 시작/완료/실패 등을 확인

2. 성능 분석 로그
   - logs/performance.jsonl
   - pipeline/stage별 소요 시간, provider, model, 성공 여부를 JSONL로 기록
```

---

## 2. 일반 로그

일반 로그는 `loguru logger`를 통해 기록한다.

주로 아래 상황에서 찍힌다.

```text
- API 요청 완료
- generate pipeline 시작/완료/실패
- text provider 시작/완료/실패
- image provider 시작/완료/실패
- image preprocess 시작/완료/실패
- image pipeline 시작/완료/실패
- fallback 발생
```

---

## 3. 일반 로그 주요 항목

### 3.1 `request_completed`

FastAPI middleware에서 API 요청 완료 시 기록된다.

예시:

```text
request_completed | request_id=... | method=POST | path=/api/v1/ad/generate | status_code=200 | elapsed_ms=1234.56
```

| 항목 | 설명 |
|---|---|
| `request_id` | 요청 단위 식별자 |
| `method` | HTTP method |
| `path` | 요청 path |
| `status_code` | HTTP 응답 코드 |
| `elapsed_ms` | 요청 처리 시간(ms) |

---

### 3.2 `generate_pipeline_started`

통합 광고 생성 pipeline 시작 시 기록된다.

예시:

```text
generate_pipeline_started | request_id=gen-xxxx | profile=all_openai | store_name=만월 | menu_name=케이크 | has_image=True
```

| 항목 | 설명 |
|---|---|
| `request_id` | 통합 생성 pipeline 식별자 |
| `profile` | 현재 `model.yaml` active_profile |
| `store_name` | 가게명 |
| `menu_name` | 메뉴명 |
| `has_image` | 이미지 포함 여부 |

---

### 3.3 `generate_pipeline_completed`

통합 광고 생성 pipeline 완료 시 기록된다.

예시:

```text
generate_pipeline_completed | request_id=gen-xxxx | partial_success=False | image_generation_success=True
```

| 항목 | 설명 |
|---|---|
| `request_id` | 통합 생성 pipeline 식별자 |
| `partial_success` | 일부 실패 후 fallback 여부 |
| `image_generation_success` | 이미지 생성 성공 여부 |

---

### 3.4 `image_preprocess` 로그

이미지 전처리 과정에서 기록된다.

예시:

```text
image_preprocess_started | input_bytes=123456 | target_size=(512, 512)
image_preprocess_opened | format=PNG | mode=RGBA | size=(1024, 1024)
image_preprocess_remove_background_started
image_preprocess_resize_started | target_size=(512, 512)
image_preprocess_completed | output_bytes=45678 | output_size=(512, 512)
```

| 항목 | 설명 |
|---|---|
| `input_bytes` | 입력 이미지 크기(bytes) |
| `target_size` | 리사이즈 목표 크기 |
| `format` | PIL이 인식한 이미지 포맷 |
| `mode` | 이미지 모드 |
| `size` | 원본 이미지 크기 |
| `output_bytes` | 전처리 결과 크기(bytes) |
| `output_size` | 전처리 결과 이미지 크기 |

실패 시:

```text
image_preprocess_failed | input_bytes=... | target_size=... | error_type=... | error=...
```

---

### 3.5 OpenAI Text Provider 로그

텍스트 생성 시작/완료/실패 시 기록된다.

예시:

```text
openai_text_generation_started | model=gpt-5.4 | api_type=responses
openai_text_generation_completed | model=gpt-5.4 | api_type=responses | output_chars=305
```

| 항목 | 설명 |
|---|---|
| `model` | 요청한 OpenAI 텍스트 모델 |
| `api_type` | `chat_completions` 또는 `responses` |
| `output_chars` | 생성된 텍스트 글자 수 |

---

### 3.6 OpenAI Image Provider 로그

이미지 생성 시작/완료/실패 시 기록된다.

예시:

```text
openai_image_generation_started | model=gpt-image-1-mini | size=1024x1536 | quality=medium | num_images=1 | has_mask=True
openai_image_generation_completed | model=gpt-image-1-mini | generated_count=1
```

| 항목 | 설명 |
|---|---|
| `model` | 요청한 OpenAI 이미지 모델 |
| `size` | 이미지 생성 크기 |
| `quality` | 이미지 품질 옵션 |
| `num_images` | 생성 요청 수 |
| `has_mask` | mask 이미지 사용 여부 |
| `generated_count` | 실제 생성된 이미지 수 |

실패 시:

```text
openai_image_generation_failed | model=... | size=... | error=...
```

---

## 4. JSONL 성능 로그

성능 로그는 아래 파일에 기록된다.

```text
backend/logs/performance.jsonl
```

JSONL은 한 줄에 JSON 객체 하나씩 기록되는 형식이다.

예시:

```json
{
  "event": "perf_metric",
  "timestamp": "2026-07-07T20:24:34+09:00",
  "request_id": "gen-xxxxxxxx",
  "pipeline": "ad_generate",
  "profile": "all_openai",
  "stage": "text_generation",
  "provider": "openai",
  "model": "gpt-5.4",
  "elapsed_ms": 5899.873,
  "elapsed_sec": 5.9,
  "elapsed_human": "5.90초",
  "success": true
}
```

---

## 5. `performance.jsonl` 공통 필드

| 필드 | 설명 |
|---|---|
| `event` | 로그 이벤트 이름. 보통 `perf_metric` |
| `timestamp` | KST 기준 기록 시각 |
| `request_id` | pipeline 단위 요청 ID |
| `pipeline` | pipeline 이름. 예: `ad_generate` |
| `profile` | `model.yaml` active_profile |
| `stage` | 측정 단계 |
| `provider` | 사용 provider. 예: `openai`, `hf`, `rembg`, `mixed` |
| `model` | 사용 모델명 |
| `elapsed_ms` | 소요 시간(ms) |
| `elapsed_sec` | 소요 시간(sec) |
| `elapsed_human` | 사람이 읽기 쉬운 소요 시간 |
| `success` | 해당 stage 성공 여부 |
| `error_code` | 실패 시 에러 코드 |
| `error_type` | 실패 시 예외 타입 |
| `extra` | 추가 메타데이터 |

---

## 6. stage 종류

현재 주요 stage는 아래와 같다.

| stage | 설명 |
|---|---|
| `text_generation` | 광고 문구 생성 |
| `image_preprocess` | 이미지 배경 제거 및 리사이징 |
| `image_generation` | 이미지 생성 전체 호출 |
| `food_generation` | `two_stage` 모드에서 중간 음식 이미지 생성 |
| `poster_generation` | 최종 포스터 이미지 생성 |
| `image_pipeline_total` | `image_pipeline` 전체 소요 시간 |
| `total_pipeline` | 통합 광고 생성 전체 소요 시간 |

---

## 7. `success` 값 기준

| 상황 | API 응답 | performance success |
|---|---|---|
| 전체 성공 | `success=true` | `true` |
| 텍스트 성공 + 이미지 성공 | `success=true` | `true` |
| 텍스트 성공 + 이미지 실패 fallback | `success=true`, `partial_success=true` | `total_pipeline success=false` |
| 텍스트 생성 실패 | `success=false` | `false` |
| 전처리 실패 | fallback 가능 시 `success=true`, `partial_success=true` | `false` |

---

## 8. fallback 로그 기준

이미지 생성 실패 후 fallback이 발생하면 API는 성공 응답을 반환할 수 있다.

응답 예:

```json
{
  "success": true,
  "data": {
    "partial_success": true,
    "image_generation_success": false,
    "warnings": [
      {
        "code": "IMAGE_POSTER_RETRY_FAILED",
        "message": "포스터 생성 실패로 fallback 이미지를 반환했습니다."
      }
    ]
  },
  "error": null
}
```

성능 로그에서는 전체 pipeline을 실패로 남긴다.

```json
{
  "stage": "total_pipeline",
  "success": false,
  "error_code": "IMAGE_POSTER_RETRY_FAILED",
  "extra": {
    "partial_success": true
  }
}
```

---

## 9. 로그 확인 명령어

일반 로그 확인:

```bash
tail -n 100 logs/app.log
```

성능 JSONL 확인:

```bash
tail -n 20 logs/performance.jsonl
```

성능 로그 요약 확인:

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

## 10. 개발 시 주의사항

```text
1. print 사용 금지
2. logger.info / logger.warning / logger.exception 사용
3. 성능 측정은 performance_logger.py 사용
4. 단계별 소요 시간은 elapsed_ms, elapsed_sec, elapsed_human 모두 기록
5. 실패 시 error_code, error_type을 남긴다
6. API key, token, secret은 로그에 남기지 않는다
```
