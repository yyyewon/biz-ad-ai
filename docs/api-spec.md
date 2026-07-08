# API Spec

## 1. 기본 정보

이 문서는 현재 백엔드에서 사용하는 주요 API 호출 방식을 정리한다.

Base URL 예:

```text
로컬 백엔드:
http://127.0.0.1:8010

Docker Compose 브라우저 접근:
http://localhost:8010

Docker Compose 내부:
http://backend:8010
```

API Prefix:

```text
/api/v1
```

---

## 2. 공통 응답 포맷

### 2.1 성공 응답

```json
{
  "success": true,
  "data": {},
  "error": null
}
```

### 2.2 실패 응답

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

프론트 처리 기준:

```python
body = response.json()

if body["success"]:
    data = body["data"]
else:
    error = body["error"]
```

---

## 3. 인증 방식

로그인이 필요한 API는 Authorization header를 사용한다.

```http
Authorization: Bearer {access_token}
```

---

# 4. Auth API

## 4.1 카카오 로그인 시작

```http
GET /api/v1/auth/kakao/login
```

카카오 로그인 페이지로 이동시키는 API다.

Request body 없음.

호출 예:

```bash
curl -i http://127.0.0.1:8010/api/v1/auth/kakao/login
```

Response:

```text
307 Temporary Redirect
```

---

## 4.2 카카오 로그인 콜백

```http
GET /api/v1/auth/kakao/callback
```

카카오 인증 완료 후 redirect되는 콜백 API다.

Query Parameters:

| 이름 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `code` | string | O | 카카오 인증 code |
| `state` | string | O | 요청 검증용 state |

Request 예:

```http
GET /api/v1/auth/kakao/callback?code={kakao_code}&state={state}
```

Response:

```text
307 Temporary Redirect
```

---

## 4.3 내 로그인 정보 조회

```http
GET /api/v1/auth/me
```

Headers:

| 이름 | 필수 | 설명 |
|---|---:|---|
| `Authorization` | O | `Bearer {access_token}` |

호출 예:

```bash
curl -X GET http://127.0.0.1:8010/api/v1/auth/me \
  -H "Authorization: Bearer {access_token}"
```

Success Response 예:

```json
{
  "success": true,
  "data": {
    "id": 1,
    "provider": "kakao",
    "provider_user_id": "123456789",
    "nickname": "사용자",
    "email": null,
    "daily_generation_count": 0,
    "daily_generation_limit": 3
  },
  "error": null
}
```

---

## 4.4 개발용 생성 횟수 초기화

```http
POST /api/v1/auth/dev/reset-quota
```

Headers:

| 이름 | 필수 | 설명 |
|---|---:|---|
| `Authorization` | O | `Bearer {access_token}` |

Request body 없음.

호출 예:

```bash
curl -X POST http://127.0.0.1:8010/api/v1/auth/dev/reset-quota \
  -H "Authorization: Bearer {access_token}"
```

---

# 5. 광고 생성 API

## 5.1 통합 광고 생성

```http
POST /api/v1/ad/generate
```

광고 문구와 광고 이미지를 한 번에 생성하는 API다.

Content-Type:

```http
multipart/form-data
```

Headers:

| 이름 | 필수 | 설명 |
|---|---:|---|
| `Authorization` | 조건부 | 로그인 기반 생성 제한을 사용할 경우 `Bearer {access_token}` |

Form Data Parameters:

| 이름 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `store_name` | string | O | 가게 이름 |
| `menu_name` | string | O | 메뉴 또는 상품 이름 |
| `purpose` | string | X | 광고 목적 |
| `request_note` | string | X | 추가 요청사항 |
| `moods` | string | X | 분위기 값. 쉼표로 구분 |
| `tone` | string | X | 광고 문구 말투 |
| `image` | file | X | 업로드 이미지 |

moods 전달 예:

```text
moods=cozy,fresh
```

이미지 포함 호출 예:

```bash
curl -X POST http://127.0.0.1:8010/api/v1/ad/generate \
  -H "Authorization: Bearer {access_token}" \
  -F "store_name=만월" \
  -F "menu_name=데몬헌터스 케이크" \
  -F "purpose=신메뉴 홍보" \
  -F "request_note=캐릭터 컨셉과 디저트 분위기를 살려줘" \
  -F "moods=cozy,fresh" \
  -F "tone=감성적인" \
  -F "image=@sample_food.png"
```

텍스트만 호출 예:

```bash
curl -X POST http://127.0.0.1:8010/api/v1/ad/generate \
  -H "Authorization: Bearer {access_token}" \
  -F "store_name=만월" \
  -F "menu_name=데몬헌터스 케이크" \
  -F "purpose=신메뉴 홍보" \
  -F "request_note=캐릭터 컨셉과 디저트 분위기를 살려줘" \
  -F "moods=cozy,fresh" \
  -F "tone=감성적인"
```

### 5.2 통합 광고 생성 성공 응답

이미지 생성까지 성공한 경우:

```json
{
  "success": true,
  "data": {
    "caption": "생성된 광고 문구",
    "images": [
      "base64_encoded_image_1",
      "base64_encoded_image_2",
      "base64_encoded_image_3"
    ],
    "partial_success": false,
    "warnings": [],
    "image_generation_success": true,
    "image_generation": {
      "request_id": "img-xxxxxxxxxx",
      "generation_mode": "direct_poster",
      "latency_ms": 98569,
      "stage_latencies_ms": {
        "food_generation_ms": 0,
        "poster_generation_ms": 98532,
        "total_ms": 98569
      },
      "num_images": 3,
      "poster_image_count": 3,
      "applied_moods": ["cozy", "fresh", "cozy"]
    }
  },
  "error": null
}
```

### 5.3 텍스트만 생성한 경우

```json
{
  "success": true,
  "data": {
    "caption": "생성된 광고 문구",
    "images": [],
    "partial_success": false,
    "warnings": [],
    "image_generation_success": null
  },
  "error": null
}
```

### 5.4 이미지 생성 실패 후 fallback

```json
{
  "success": true,
  "data": {
    "caption": "생성된 광고 문구",
    "images": [
      "fallback_base64_image",
      "fallback_base64_image",
      "fallback_base64_image"
    ],
    "partial_success": true,
    "warnings": [
      {
        "code": "IMAGE_POSTER_RETRY_FAILED",
        "message": "포스터 생성 실패로 fallback 이미지를 반환했습니다.",
        "detail": {
          "request_id": "gen-xxxxxxxx",
          "error_type": "AppException",
          "error": "포스터 이미지 생성 재시도에 실패했습니다."
        }
      }
    ],
    "image_generation_success": false,
    "image_generation_error": "포스터 생성 실패로 fallback 이미지를 반환했습니다."
  },
  "error": null
}
```

프론트 판단 기준:

```text
success=true
partial_success=true
image_generation_success=false
```

---

# 6. 단독 이미지 광고 생성 API

## 6.1 이미지 광고 생성

```http
POST /api/v1/ad/image
```

이미지 광고만 생성하는 API다.  
신규 구조에서는 이미지 path를 받지 않고 `input_image_base64`를 받는다.

Content-Type:

```http
application/json
```

Request Body:

| 이름 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `input_image_base64` | string | O | 입력 이미지 base64 |
| `store_name` | string | X | 가게명 |
| `menu_name` | string | X | 메뉴명 |
| `mood` | string | X | 이미지 무드 |
| `mood_list` | string[] | X | 여러 무드 목록 |
| `prompt` | string | X | 추가 프롬프트 |
| `num_images` | number | X | 생성 이미지 수 |
| `generation_mode` | string | X | `direct_poster` 또는 `two_stage` |
| `headline` | string | X | 포스터 상단 문구 |
| `price_text` | string | X | 가격 문구 |
| `layout_type` | string | X | `auto`, `classic`, `focus`, `left` |

Request 예:

```json
{
  "input_image_base64": "base64_encoded_source_image",
  "store_name": "만월",
  "menu_name": "데몬헌터스 케이크",
  "mood": "cozy",
  "num_images": 3,
  "generation_mode": "direct_poster"
}
```

Success Response 예:

```json
{
  "success": true,
  "data": {
    "request_id": "img-xxxxxxxxxx",
    "mood": "cozy",
    "prompt_used": "실제 이미지 생성에 사용된 prompt",
    "num_images": 3,
    "latency_ms": 98569,
    "generation_mode": "direct_poster",
    "stage_latencies_ms": {
      "food_generation_ms": 0,
      "poster_generation_ms": 98532,
      "total_ms": 98569
    },
    "images": [
      "base64_encoded_image_1",
      "base64_encoded_image_2",
      "base64_encoded_image_3"
    ],
    "poster_images": [
      "base64_encoded_image_1",
      "base64_encoded_image_2",
      "base64_encoded_image_3"
    ],
    "applied_moods": ["cozy", "fresh", "vintage"],
    "seed": null,
    "message": "ok"
  },
  "error": null
}
```

---

# 7. 이미지 저장 정책

현재 백엔드는 생성 이미지를 서버 디스크에 저장하지 않는다.

```text
업로드 이미지 bytes
→ 전처리 bytes
→ 이미지 생성 bytes
→ base64 응답
```

사용하지 않는 것:

```text
outputs/ 저장
source_rgba.png 저장
inpaint_mask.png 저장
poster_*.png 저장
/outputs 정적 파일 URL
download_url 기반 응답
```

프론트는 `data.images`의 base64 문자열을 decode해서 화면에 표시한다.

---

# 8. Health Check

```http
GET /health
```

Response:

```json
{
  "status": "ok"
}
```

---

# 9. Root

```http
GET /
```

Response:

```json
{
  "service": "biz-ad-ai-backend",
  "status": "running",
  "docs": "/docs"
}
```
