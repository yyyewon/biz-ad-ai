# biz-ad-ai

<!-- BACKEND_STRUCTURE_START -->
## Backend Service Structure

본 프로젝트의 백엔드는 FastAPI 기반으로 구성합니다.  
프론트엔드에서 전달한 가게 정보, 대표 메뉴, 홍보 목적, 업로드 이미지, 무드, 문구 톤을 받아 광고 문구와 광고 이미지를 생성합니다.

현재 서비스는 업로드 이미지와 생성 이미지를 서버에 저장하지 않습니다.  
요청 처리 중 메모리에서만 이미지를 사용하고, 최종 생성 이미지는 base64 형태로 프론트엔드에 응답합니다.

### Core Policy

- 로그에는 request_id, 파일명, content_type, 파일 크기, image_hash, 에러 메시지 등 메타데이터만 기록

### API Overview

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/health` | 서버 상태 확인 |
| POST | `/api/v1/ad/text` | 광고 문구 생성 단독 테스트 |
| POST | `/api/v1/ad/image` | 광고 이미지 생성 단독 테스트 |
| POST | `/api/v1/ad/generate` | 광고 문구 + 이미지 통합 생성 |

최종 프론트엔드 서비스에서는 `/api/v1/ad/generate`를 주로 사용합니다.  
`/api/v1/ad/text`와 `/api/v1/ad/image`는 팀원별 기능 단독 개발 및 테스트를 위해 유지합니다.

### Directory Structure

    project-root/
    ├── config/
    │   └── model.yaml
    │
    ├── backend/
    │   ├── logs/
    │   │   └── .gitkeep
    │   │
    │   ├── app/
    │   │   ├── main.py
    │   │   ├── api/
    │   │   │   └── v1/
    │   │   │       ├── router.py
    │   │   │       └── endpoints/
    │   │   │           ├── health.py
    │   │   │           ├── text_ad.py
    │   │   │           ├── image_ad.py
    │   │   │           └── generate_ad.py
    │   │   │
    │   │   ├── core/
    │   │   │   ├── config.py
    │   │   │   └── exceptions.py
    │   │   │
    │   │   ├── schemas/
    │   │   │   ├── common.py
    │   │   │   ├── text_ad.py
    │   │   │   ├── image_ad.py
    │   │   │   └── generate_ad.py
    │   │   │
    │   │   ├── services/
    │   │   │   ├── pipelines/
    │   │   │   │   ├── text_pipeline.py
    │   │   │   │   ├── image_pipeline.py
    │   │   │   │   └── generate_pipeline.py
    │   │   │   │
    │   │   │   └── providers/
    │   │   │       ├── base.py
    │   │   │       ├── factory.py
    │   │   │       ├── openai_provider.py
    │   │   │       └── hf_provider.py
    │   │   │
    │   │   └── utils/
    │   │       ├── image_utils.py
    │   │       └── logger.py
    │   │
    │   └── tests/
    │       ├── test_health.py
    │       ├── test_text_ad.py
    │       ├── test_image_ad.py
    │       └── test_generate_ad.py
    │
    └── docs/
        └── api-spec.md

### Layer Description

| Layer | Directory | Role |
|---|---|---|
| API Layer | `backend/app/api/v1/endpoints/` | FastAPI endpoint 정의 |
| Schema Layer | `backend/app/schemas/` | 요청/응답 데이터 구조 정의 |
| Service Layer | `backend/app/services/pipelines/` | 광고 문구, 이미지, 통합 생성 흐름 관리 |
| Provider Layer | `backend/app/services/providers/` | OpenAI, HuggingFace, ONNX 등 모델 실행 방식 분리 |
| Core Layer | `backend/app/core/` | 설정 로딩, 예외 처리 |
| Utils Layer | `backend/app/utils/` | 이미지 변환, 해시 계산, 로깅 유틸 |
| Tests | `backend/tests/` | API 및 pipeline 단위 테스트 |

### Model Configuration

`config/model.yaml`에서 OpenAI, HuggingFace, Hybrid 실행 조합을 관리합니다.

| Key | Description |
|---|---|
| `active_profile` | 현재 사용할 provider 조합 |
| `profiles` | 기능별 provider 선택 |
| `output_image` | 최종 프론트에 전달할 이미지 크기 및 개수 설정 |
| `runtime` | 실행 환경 설정 |
| `openai` | OpenAI 모델 설정 |
| `hf` | HuggingFace 모델 설정 |
| `onnx` | ONNX 실행 설정 |


### Backend Design Notes

- endpoint는 요청을 받고 pipeline을 호출합니다.
- pipeline은 광고 문구 생성, 이미지 생성, 통합 생성 흐름을 관리합니다.
- provider는 OpenAI, HuggingFace, ONNX 등 모델 실행 방식을 분리합니다.
- schema는 API request/response 형식을 고정합니다.
- image_utils는 이미지 변환, base64 변환, image_hash 계산을 담당합니다.
- logger는 요청, 에러, 추론 시간, 이미지 메타데이터를 기록합니다.

<!-- BACKEND_STRUCTURE_END -->
