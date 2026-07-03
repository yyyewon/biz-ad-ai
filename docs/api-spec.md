# API Specification

<!-- IMAGE_PREPROCESS_API_SPEC_START -->
## Image Preprocess API

### 개요

사용자가 업로드한 이미지를 백엔드에서 전처리하는 API입니다.

이 API는 multipart/form-data 형식으로 이미지를 전달받은 뒤,
backend/app/image_processor.py의 remove_background_and_resize(image_bytes) 함수를 실행합니다.

현재 처리 내용은 다음과 같습니다.

- 이미지 파일 bytes 읽기
- rembg 기반 배경 제거
- 512x512 크기 리사이징
- PNG bytes로 변환
- base64 문자열로 응답 반환

현재 이 API는 이미지 생성 모델을 직접 실행하지 않습니다.
이미지 생성 전에 사용할 수 있는 전처리 단계 API입니다.

---

### Endpoint

POST /api/v1/image/preprocess

---

### Request

Content-Type:

multipart/form-data

Form Data:

| 필드명 | 타입 | 필수 여부 | 설명 |
|---|---|---:|---|
| file | File | 필수 | 전처리할 이미지 파일 |

지원 파일:

서버에서는 content_type이 image/로 시작하는 파일만 허용합니다.

예시:

- image/png
- image/jpeg
- image/webp

---

### curl 예시

로컬 개발 서버 기준:

curl -X POST \
  http://127.0.0.1:8013/api/v1/image/preprocess \
  -F "file=@tmp_samples/sample.png"

응답이 길기 때문에 파일로 저장해서 확인하는 방식도 사용할 수 있습니다.

curl -X POST \
  http://127.0.0.1:8013/api/v1/image/preprocess \
  -F "file=@tmp_samples/sample.png" \
  -o tmp_samples/preprocess_response.json

head -c 500 tmp_samples/preprocess_response.json
echo

---

### Success Response

HTTP Status:

200 OK

Body:

{
  "success": true,
  "data": {
    "image_base64": "iVBORw0KGgoAAAANSUhEUgAA...",
    "mime_type": "image/png",
    "filename": "sample.png"
  },
  "error": null
}

Response Fields:

| 필드 | 타입 | 설명 |
|---|---|---|
| success | boolean | 요청 성공 여부 |
| data.image_base64 | string | 전처리 결과 PNG 이미지를 base64로 인코딩한 문자열 |
| data.mime_type | string | 결과 이미지 MIME type. 현재는 image/png |
| data.filename | string | 업로드한 원본 파일명 |
| error | null | 성공 시 null |

---

### Frontend 사용 예시

응답으로 받은 image_base64는 아래와 같이 이미지로 표시할 수 있습니다.

HTML / 일반 프론트:

const imageSrc = `data:image/png;base64,${imageBase64}`;

Streamlit:

import base64
from io import BytesIO
from PIL import Image
import streamlit as st

image_bytes = base64.b64decode(image_base64)
image = Image.open(BytesIO(image_bytes))

st.image(image)

---

### Error Response

공통 에러 응답 형식은 다음과 같습니다.

{
  "success": false,
  "data": null,
  "error": {
    "code": "ERROR_CODE",
    "message": "에러 메시지",
    "detail": "상세 정보"
  }
}

---

### Error Codes

#### 1. 이미지가 아닌 파일 업로드

HTTP Status:

400 Bad Request

Response:

{
  "success": false,
  "data": null,
  "error": {
    "code": "INVALID_IMAGE_FILE",
    "message": "이미지 파일만 업로드할 수 있습니다.",
    "detail": {
      "content_type": "text/plain"
    }
  }
}

---

#### 2. 빈 파일 업로드

HTTP Status:

400 Bad Request

Response:

{
  "success": false,
  "data": null,
  "error": {
    "code": "EMPTY_IMAGE_FILE",
    "message": "업로드된 이미지 파일이 비어 있습니다.",
    "detail": null
  }
}

---

#### 3. 이미지 전처리 의존성 오류

rembg, onnxruntime, platformdirs 등 이미지 전처리 실행에 필요한 패키지가 누락된 경우 발생합니다.

HTTP Status:

500 Internal Server Error

Response:

{
  "success": false,
  "data": null,
  "error": {
    "code": "IMAGE_PREPROCESS_DEPENDENCY_ERROR",
    "message": "이미지 전처리 의존성이 설치되지 않았습니다.",
    "detail": "No module named '...'"
  }
}

---

#### 4. 이미지 전처리 실패

이미지 파일이 손상되었거나, 내부 처리 중 예상하지 못한 오류가 발생한 경우입니다.

HTTP Status:

500 Internal Server Error

Response:

{
  "success": false,
  "data": null,
  "error": {
    "code": "IMAGE_PREPROCESS_FAILED",
    "message": "이미지 전처리 중 오류가 발생했습니다.",
    "detail": "상세 오류 메시지"
  }
}

---

#### 5. 전처리 결과가 비어 있는 경우

HTTP Status:

500 Internal Server Error

Response:

{
  "success": false,
  "data": null,
  "error": {
    "code": "IMAGE_PREPROCESS_EMPTY_RESULT",
    "message": "이미지 전처리 결과가 비어 있습니다.",
    "detail": null
  }
}

---

### Backend 처리 흐름

POST /api/v1/image/preprocess
↓
UploadFile 수신
↓
content_type 검증
↓
file.read()로 image_bytes 추출
↓
remove_background_and_resize(image_bytes) 실행
↓
결과 PNG bytes 생성
↓
base64.b64encode()
↓
success_response(data={...}) 반환

---

### 관련 파일

- backend/app/image_processor.py
- backend/app/api/v1/endpoints/image_preprocess.py
- backend/app/api/v1/router.py
- backend/tests/test_image_preprocess.py
- backend/requirements.in
- backend/requirements.txt

---

### Runtime Dependencies

이미지 전처리 API 실행을 위해 백엔드 requirements에 아래 의존성이 포함되어 있습니다.

- rembg[cpu]
- onnxruntime
- numpy<2.5

rembg[cpu]는 배경 제거 모델 실행을 위해 onnxruntime CPU backend를 사용합니다.

---

### Test

pytest:

cd backend
python -m pytest -q

정상 기준:

11 passed

실제 이미지 curl 테스트:

cd ~/biz-ad-ai

PYTHONPATH=backend ./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8013 --reload

다른 터미널에서:

curl -X POST \
  http://127.0.0.1:8013/api/v1/image/preprocess \
  -F "file=@tmp_samples/sample.png" \
  -o tmp_samples/preprocess_response.json

정상 기준:

{
  "success": true,
  "data": {
    "image_base64": "...",
    "mime_type": "image/png",
    "filename": "sample.png"
  },
  "error": null
}

<!-- IMAGE_PREPROCESS_API_SPEC_END -->
