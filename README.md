# 📸 [2팀] 소상공인 두레

생성형 AI로 소상공인이 인스타그램에 올릴 광고 이미지와 문구를 손쉽게 만들 수 있는 서비스입니다.  
디자인 역량이나 전문 툴 없이, 사진 한 장과 몇 가지 정보만 입력하면 배경이 교체된 광고 이미지와 광고 문구를 자동으로 생성합니다. 요식업 소상공인을 주 타겟으로 하며, 비영리 목적(취약계층 지원)으로 기획된 프로젝트입니다.

## 기능

- 제품(음식) 사진의 배경을 보존한 채 인스타 감성 배경으로 교체
- 가게 정보, 음식 유형, 톤을 반영한 광고 문구·이미지 자동 생성
- 생성된 이미지·문구를 프론트엔드에서 바로 수정 및 다운로드

## Tech Stack

| 영역 | 기술 |
|---|---|
| Frontend | Streamlit |
| Backend | FastAPI |
| AI (텍스트) | OpenAI `gpt-5.4-mini` / HuggingFace `Qwen/Qwen3-4B-Instruct-2507` |
| AI (이미지) | OpenAI `gpt-image-1-mini` / HuggingFace `stable-diffusion-3.5-medium` |
| Infra | Docker, Docker Compose, GCP, GitHub Actions |

Provider는 `config/model.yaml`의 `active_profile`로 OpenAI / HuggingFace / Hybrid 조합을 선택합니다.

## 모델 라이선스 고지

**Powered by Stability AI**

이 프로젝트는 이미지 생성 기능 중 일부에 Stability AI의
`stable-diffusion-3.5-medium` 모델을 사용합니다.
해당 모델은 [Stability AI Community License](https://stability.ai/community-license-agreement)
를 따르며, 자세한 고지 사항은 [`NOTICE`](./NOTICE) 파일을 참고하세요.

## 프로젝트 구조

```
.
├── config/model.yaml      # AI provider / 모델 설정
├── frontend/              # Streamlit 앱 (광고 UI + metrics_app.py)
│   ├── app.py             # 메인: Step 1/2/3 광고 생성 플로우
│   ├── metrics_app.py     # Metrics 전용 entry (별도 포트)
│   ├── core/
│   │   ├── metrics/       # JSONL 로더, 집계 (대시보드 전용)
│   │   ├── api_client.py
│   │   └── config.py
│   └── components/        # Step UI 컴포넌트
├── backend/               # FastAPI 서버
│   └── app/
│       ├── api/           # 라우터 & 엔드포인트
│       ├── core/          # 설정, 예외 처리
│       ├── schemas/       # 요청/응답 스키마, performance_metrics registry
│       ├── services/      # pipeline, provider, eval
│       └── utils/         # 이미지 처리, performance_logger
├── docs/api-spec.md       # API 명세
└── docker-compose.yml
```

### Metrics 대시보드

팀 **공용 JSONL** + **8555** 포트에서 dev·prod 생성분을 한 화면에서 확인합니다.

**초기 세팅·수정 위치:** [`docs/metrics-setup-guide.md`](./docs/metrics-setup-guide.md)

| 항목 | 설명 |
|---|---|
| 접속 (VM) | `http://34.60.252.165:8000/user/{계정}/proxy/8555/` |
| JSONL | `/opt/biz-ad-ai-team-logs/performance.jsonl`, `quality.jsonl` |
| 출처 필드 | `extra.source_user`, `backend_port`, `frontend_port`, `deploy_env` |

## 시작하기

### 요구 사항

- Docker, Docker Compose

### 환경 변수

`frontend/.env.example`, `backend/.env.example`을 각각 복사해서 `.env`로 만든 뒤 값을 채워주세요.

| 파일 | 변수 | 설명 |
|---|---|---|
| `frontend/.env` | `API_BASE_URL` | 백엔드 주소 |
| `frontend/.env` | `RG_MOCK_MODE` | `true`면 백엔드 없이 목업 데이터로 프론트만 실행 |
| (선택) | `METRICS_LOG_DIR` | Metrics 컨테이너가 읽을 JSONL 디렉터리 (Docker dev: `/logs`) |
| `backend/.env` | `CORS_ALLOWED_ORIGINS` | 허용할 프론트엔드 origin (콤마 구분) |
| `backend/.env` | `MODEL_WARMUP_ENABLED` | 서버 시작 시 모델 자동 로딩 여부(기본 `false`) |
| `backend/.env` | `MODEL_LOAD_MIN_AVAILABLE_RAM_GB` | 모델 로딩 전 최소 available RAM(GB), `0`이면 검사 해제 |
| `backend/.env` | `HF_IMAGE_CPU_OFFLOAD_ENABLED` | Diffusers CPU offload 사용 여부(기본 `false`) |
| 루트 `.env` | `BACKEND_MEMORY_LIMIT` | 백엔드 컨테이너 RAM 제한(기본 `12g`) |
| 루트 `.env` | `BACKEND_MEMORY_SWAP_LIMIT` | RAM+swap 제한(기본 `16g`) |


### 실행

```bash
docker compose up --build
```

## 테스트

```bash
cd backend && pytest
cd frontend && pytest tests/test_metrics_jsonl_loader.py -q
```

##  산출물
- **최종 보고서** : [다운로드]
- **협업 일지**
  - [황예원]
  - [박도원]
  - [손영욱]
  - [채영환]
  - [천지연]
