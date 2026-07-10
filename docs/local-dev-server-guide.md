# Local Docker CPU 실행 가이드

Mac 로컬 환경에서 GPU/CUDA 없이 OpenAI 기준으로 서비스를 실행하는 방법입니다.  
HF Stable Diffusion 3.5 Medium 실제 이미지 생성은 GPU 서버에서 테스트하는 것을 권장합니다.


## 1. `.env` 설정

로컬 실행 전 `backend/.env`를 로컬 기준으로 설정합니다.

```env
FRONTEND_BASE_URL=http://localhost:8501
KAKAO_REDIRECT_URI=http://localhost:8010/api/v1/auth/kakao/callback
CORS_ALLOWED_ORIGINS=http://localhost:8501,http://127.0.0.1:8501

```

## 2. 로컬 Docker 실행

프로젝트 루트에서 실행합니다.

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.local.yml \
  -p biz-ad-ai-local \
  up -d --build
```

## 3. 실행 상태 확인

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.local.yml \
  -p biz-ad-ai-local \
  ps
```

## 4. 접속 주소

Backend Health:

```text
http://localhost:8010/api/v1/health
```

Swagger:

```text
http://localhost:8010/docs
```

Frontend:

```text
http://localhost:8501
```

Streamlit Health:

```text
http://localhost:8501/_stcore/health
```

## 5. 로그 확인

Backend 로그:

```bash
docker logs biz-ad-ai-backend-local --tail=200
```

Frontend 로그:

```bash
docker logs biz-ad-ai-frontend-local --tail=200
```

Backend 실시간 로그:

```bash
docker logs -f biz-ad-ai-backend-local
```

Frontend 실시간 로그:

```bash
docker logs -f biz-ad-ai-frontend-local
```

## 6. 종료

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.local.yml \
  -p biz-ad-ai-local \
  down
```

볼륨까지 삭제할 때만 사용합니다.

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.local.yml \
  -p biz-ad-ai-local \
  down -v
```

## 참고

로컬 CPU 실행은 `requirements.local.txt`를 사용합니다.

- `requirements.txt`: GPU 서버 / CUDA 기준
- `requirements.local.txt`: Mac 로컬 Docker / CPU 기준
- `requirements.local.in`: local requirements 관리용 입력 파일

Mac 로컬 Docker에서는 CUDA 기반 HF 이미지 생성까지 검증하지 않습니다.  
로컬에서는 OpenAI 기준 광고 생성, API 동작, 로그인 흐름, 테스트 통과를 확인합니다.
