# Backend Common Guide

백엔드 API 개발 시 공통으로 사용하는 **Logger, Exception, Response, Router 사용 방법**을 정리한 문서입니다.

새 API를 만들 때 응답 형식과 에러 처리 방식이 달라지지 않도록 아래 기준을 따라주세요.

---

## 1. 공통 Logger 사용 방법

공통 logger 설정 파일은 아래에 있습니다.

```text
backend/app/utils/logger.py
```

서버 시작 시 `backend/app/main.py`에서 한 번 설정됩니다.

```python
from app.utils.logger import setup_logger

setup_logger()
```

로그는 두 곳에 남습니다.

```text
1. 터미널 출력
2. backend/logs/app.log
```

로그 시간은 한국 시간 기준입니다.

```text
Asia/Seoul
```

---

## 2. API 코드에서 Logger 사용하기

API 파일이나 service 파일에서는 아래처럼 import해서 사용합니다.

```python
from loguru import logger
```

예시:

```python
logger.info("text_generation_started | business_type={} | tone={}", business_type, tone)
logger.warning("text_generation_retry | reason={}", reason)
logger.error("text_generation_failed | error={}", str(exc))
```

---

## 3. Logger 사용 예시

### 요청 처리 시작 로그

```python
logger.info(
    "image_preprocess_started | filename={} | content_type={} | file_size={}",
    file.filename,
    file.content_type,
    len(image_bytes),
)
```

### 요청 처리 완료 로그

```python
logger.info(
    "image_preprocess_completed | filename={} | output_size={} | base64_length={} | elapsed_ms={}",
    file.filename,
    len(processed_bytes),
    len(image_base64),
    elapsed_ms,
)
```

### 오류 로그

```python
logger.error(
    "image_generation_failed | error_type={} | error={}",
    type(exc).__name__,
    str(exc),
)
```

---

## 4. 자동 요청 로그

`backend/app/main.py`에는 요청 로그 middleware가 적용되어 있습니다.

따라서 각 API에서 별도로 설정하지 않아도 모든 요청마다 아래 정보가 자동으로 기록됩니다.

```text
request_id
HTTP method
path
status_code
elapsed_ms
```

예시 로그:

```text
request_completed | request_id=... | method=POST | path=/api/v1/image/preprocess | status_code=200 | elapsed_ms=1234.56
```

응답 헤더에도 request ID가 포함됩니다.

```text
X-Request-ID: ...
```

프론트와 백엔드가 같은 요청을 추적할 때 사용할 수 있습니다.

---

## 5. Logger 사용 시 주의사항

아래 정보는 로그에 남기지 않습니다.

```text
- 원본 이미지 bytes
- base64 전체 문자열
- OpenAI API Key
- Hugging Face Token
- 개인정보
- 너무 긴 프롬프트 전체 원문
```

잘못된 예시:

```python
logger.info("image_base64={}", image_base64)
```

권장 예시:

```python
logger.info(
    "image_input_received | filename={} | file_size={}",
    file.filename,
    len(image_bytes),
)
```

이미지나 base64는 값 전체가 매우 길기 때문에 로그 파일이 커지고, 민감 정보가 남을 수 있습니다. 크기, 파일명, 처리 시간 정도만 기록합니다.

---

## 6. 공통 예외 처리 사용 방법

공통 예외 처리 파일은 아래에 있습니다.

```text
backend/app/core/exceptions.py
```

API에서 에러가 발생했을 때 직접 `JSONResponse`를 만들지 말고, `AppException`을 사용합니다.

```python
from app.core.exceptions import AppException
```

예시:

```python
raise AppException(
    code="INVALID_IMAGE_FILE",
    message="이미지 파일만 업로드할 수 있습니다.",
    status_code=400,
    detail={"content_type": file.content_type},
)
```

---

## 7. 에러 응답 형식

`AppException`을 사용하면 아래 형식으로 에러 응답이 통일됩니다.

```json
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
```

---

## 8. 성공 응답 사용 방법

성공 응답은 `success_response`를 사용합니다.

```python
from app.schemas.common import success_response
```

예시:

```python
return success_response(
    data={
        "image_base64": image_base64,
        "mime_type": "image/png",
        "filename": file.filename,
    }
)
```

성공 응답 형식은 아래와 같습니다.

```json
{
  "success": true,
  "data": {
    "image_base64": "...",
    "mime_type": "image/png",
    "filename": "sample.png"
  },
  "error": null
}
```

---

## 9. API 작성 기본 패턴

새 API를 만들 때는 아래 구조를 기준으로 작성합니다.

```python
from fastapi import APIRouter
from loguru import logger

from app.core.exceptions import AppException
from app.schemas.common import success_response


router = APIRouter()


@router.post("/example")
async def example_api():
    logger.info("example_api_started")

    try:
        result = "some result"

    except AppException:
        raise

    except Exception as exc:
        logger.error(
            "example_api_failed | error_type={} | error={}",
            type(exc).__name__,
            str(exc),
        )

        raise AppException(
            code="EXAMPLE_API_FAILED",
            message="API 처리 중 오류가 발생했습니다.",
            status_code=500,
            detail=str(exc),
        ) from exc

    logger.info("example_api_completed")

    return success_response(
        data={
            "result": result
        }
    )
```

중요한 부분은 아래입니다.

```python
except AppException:
    raise
```

이미 의도적으로 발생시킨 `AppException`은 그대로 다시 raise해야 합니다. 그렇지 않으면 모든 에러가 일반 서버 에러로 처리될 수 있습니다.

---

## 10. Router 연결 방법

endpoint 파일을 새로 만들면 `backend/app/api/v1/router.py`에 연결해야 합니다.

예시:

```python
from app.api.v1.endpoints import image_preprocess


api_router.include_router(
    image_preprocess.router,
    prefix="/image",
    tags=["Image Preprocess"],
)
```

최종 API 경로는 아래 조합으로 만들어집니다.

```text
main.py        -> /api/v1
router.py      -> /image
endpoint file  -> /preprocess
```

최종 경로:

```text
POST /api/v1/image/preprocess
```

---

## 11. 현재 적용된 참고 파일

아래 파일을 보면 실제 적용 예시를 확인할 수 있습니다.

```text
backend/app/api/v1/endpoints/image_preprocess.py
```

이 파일에는 다음 내용이 적용되어 있습니다.

```text
- UploadFile 처리
- content_type 검증
- 빈 파일 검증
- logger.info 사용
- AppException 사용
- try / except AppException / except Exception 구조
- success_response 반환
```

예시 코드:

```python
if not file.content_type or not file.content_type.startswith("image/"):
    raise AppException(
        code="INVALID_IMAGE_FILE",
        message="이미지 파일만 업로드할 수 있습니다.",
        status_code=400,
        detail={"content_type": file.content_type},
    )
```

성공 응답 예시:

```python
return success_response(
    data={
        "image_base64": image_base64,
        "mime_type": "image/png",
        "filename": file.filename,
    }
)
```

---

## 12. 텍스트 광고 생성 API 예시

텍스트 광고 생성 API에서는 아래처럼 사용할 수 있습니다.

```python
from loguru import logger

from app.core.exceptions import AppException
from app.schemas.common import success_response


logger.info(
    "text_generation_started | business_type={} | tone={}",
    business_type,
    tone,
)

try:
    # 광고 문구 생성 로직
    pass

except Exception as exc:
    logger.error(
        "text_generation_failed | error_type={} | error={}",
        type(exc).__name__,
        str(exc),
    )

    raise AppException(
        code="TEXT_GENERATION_FAILED",
        message="광고 문구 생성 중 오류가 발생했습니다.",
        status_code=500,
        detail=str(exc),
    ) from exc

return success_response(
    data={
        "headline": headline,
        "body": body,
        "hashtags": hashtags,
    }
)
```

---

## 13. 이미지 생성 API 예시

이미지 생성 API에서는 아래처럼 사용할 수 있습니다.

```python
from loguru import logger

from app.core.exceptions import AppException
from app.schemas.common import success_response


logger.info(
    "image_generation_started | prompt_length={} | model={}",
    len(prompt),
    model_name,
)

try:
    # 이미지 생성 로직
    pass

except Exception as exc:
    logger.error(
        "image_generation_failed | error_type={} | error={}",
        type(exc).__name__,
        str(exc),
    )

    raise AppException(
        code="IMAGE_GENERATION_FAILED",
        message="이미지 생성 중 오류가 발생했습니다.",
        status_code=500,
        detail=str(exc),
    ) from exc

return success_response(
    data={
        "image_base64": image_base64,
        "mime_type": "image/png",
        "prompt": prompt,
    }
)
```

주의할 점:

```text
prompt 전체를 로그에 남기기보다는 prompt_length, model_name, 옵션 정보 정도만 남기는 것을 권장합니다.
```

---

## 14. 테스트 방법

백엔드 테스트는 아래 명령어로 실행합니다.

```bash
cd backend
python -m pytest -q
```

현재 정상 기준:

```text
11 passed
```

관련 테스트 파일:

```text
backend/tests/test_exception_handlers.py
backend/tests/test_common_response.py
backend/tests/test_health.py
backend/tests/test_image_preprocess.py
```

---

## 15. 적용 기준 요약

새 API를 만들 때는 아래 기준을 지켜주세요.

```text
1. print 대신 logger 사용
2. 성공 응답은 success_response(data={...}) 사용
3. 에러 응답은 AppException 사용
4. 직접 JSONResponse 만들지 않기
5. endpoint 파일 생성 후 router.py에 include_router 연결
6. 이미지 bytes, base64, API Key 등 민감하거나 큰 값은 로그에 남기지 않기
```

---

## 16. 빠른 참고

### Import

```python
from loguru import logger
from app.core.exceptions import AppException
from app.schemas.common import success_response
```

### Success

```python
return success_response(data={...})
```

### Error

```python
raise AppException(
    code="ERROR_CODE",
    message="에러 메시지",
    status_code=400,
    detail={...},
)
```

### Router

```python
api_router.include_router(
    some_router.router,
    prefix="/some-prefix",
    tags=["Some Tag"],
)
```
