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
    │
    ├── config/                                            # 프로젝트 전체 설정 폴더
    │   └── model.yaml                                     # OpenAI / HF / Hybrid provider 조합 및 이미지 생성 설정 관리
    │
    ├── backend/
    │   ├── .gitkeep
    │   │
    │   ├── logs/                                          # FastAPI 서버 로그 저장 폴더. 실제 로그 파일은 Git 제외
    │   │   └── .gitkeep
    │   │
    │   ├── app/                                           # FastAPI 애플리케이션 코드 루트
    │   │   ├── __init__.py
    │   │   ├── main.py                                    # FastAPI 앱 시작점. CORS, router 연결, Swagger 설정
    │   │   │
    │   │   ├── api/                                       # API 라우터 계층
    │   │   │   ├── __init__.py
    │   │   │   └── v1/                                    # API 버전 v1 관리
    │   │   │       ├── __init__.py
    │   │   │       ├── router.py                          # v1 endpoint들을 하나로 묶는 라우터
    │   │   │       └── endpoints/                         # 실제 API endpoint 파일 모음
    │   │   │           ├── __init__.py
    │   │   │           ├── health.py                      # GET /api/v1/health. 서버 상태 확인 API
    │   │   │           ├── text_ad.py                     # POST /api/v1/ad/text. 광고 문구 생성 단독 테스트 API
    │   │   │           ├── image_ad.py                    # POST /api/v1/ad/image. 광고 이미지 생성 단독 테스트 API
    │   │   │           └── generate_ad.py                 # POST /api/v1/ad/generate. 프론트에서 사용할 통합 생성 API
    │   │   │
    │   │   ├── core/                                      # 앱 전역 설정과 공통 처리 영역
    │   │   │   ├── __init__.py
    │   │   │   ├── config.py                              # .env와 config/model.yaml 로딩. active_profile, provider, 이미지 설정 관리
    │   │   │   └── exceptions.py                          # 공통 예외 처리. 에러를 success/data/error 형식으로 변환
    │   │   │
    │   │   ├── schemas/                                   # API 요청/응답 데이터 구조 정의
    │   │   │   ├── __init__.py
    │   │   │   ├── common.py                              # 공통 응답 스키마. success, data, error 구조 정의
    │   │   │   ├── text_ad.py                             # 광고 문구 생성 API 요청/응답 스키마
    │   │   │   ├── image_ad.py                            # 광고 이미지 생성 API 요청/응답 스키마. base64 이미지 응답 포함
    │   │   │   └── generate_ad.py                         # 통합 생성 API 요청/응답 스키마
    │   │   │
    │   │   ├── services/                                  # 실제 처리 로직 계층
    │   │   │   ├── __init__.py
    │   │   │   │
    │   │   │   ├── pipelines/                             # API 요청이 들어온 뒤 전체 처리 흐름 관리
    │   │   │   │   ├── __init__.py
    │   │   │   │   ├── text_pipeline.py                   # 광고 문구 생성 흐름. 팀원 A 기능 단독 연결 지점
    │   │   │   │   ├── image_pipeline.py                  # 이미지 생성 흐름. 팀원 C 기능 단독 연결 지점
    │   │   │   │   └── generate_pipeline.py               # 통합 생성 흐름. 문구 생성 + 이미지 생성 + base64 응답 조립
    │   │   │   │
    │   │   │   └── providers/                             # OpenAI/HF/Hybrid 교체를 위한 AI Provider 계층
    │   │   │       ├── __init__.py
    │   │   │       ├── base.py                            # OpenAI/HF가 공통으로 따라야 하는 인터페이스 정의
    │   │   │       ├── factory.py                         # config/model.yaml 기준으로 기능별 provider 선택
    │   │   │       ├── openai_provider.py                 # OpenAI 기반 이미지 분석, 문구 생성, 이미지 생성 구현
    │   │   │       └── hf_provider.py                     # HuggingFace 기반 이미지 분석, 문구 생성, 이미지 생성 구현
    │   │   │
    │   │   └── utils/                                     # 공통 유틸리티 영역
    │   │       ├── __init__.py
    │   │       ├── image_utils.py                         # bytes ↔ PIL Image ↔ base64 변환, 최종 이미지 크기 후처리
    │   │       └── logger.py                              # loguru 기반 로그 설정. 요청/에러/추론 시간 기록
    │   │
    │   └── tests/                                         # 백엔드 단위 테스트 폴더
    │       ├── __init__.py
    │       ├── test_health.py                             # health API 테스트
    │       ├── test_text_ad.py                            # 광고 문구 생성 API 테스트
    │       ├── test_image_ad.py                           # 광고 이미지 생성 API 테스트
    │       └── test_generate_ad.py                        # 통합 생성 API 테스트
    │
    └── docs/                                              # 팀 공유 문서 폴더
        └── api-spec.md                                    # 프론트/백엔드 공유용 API 명세서. 요청/응답, 에러 코드, base64 응답 방식 정리

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
