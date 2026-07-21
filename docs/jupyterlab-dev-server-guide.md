# JupyterLab 개발 서버 실행 가이드

같은 VM에서 팀원별로 개발 서버를 실행하는 방법을 정리한다.  
배포 서버 포트는 건드리지 않고, 팀원별 개발 포트를 분리해서 사용한다.

---

## 1. 포트 기준

### 배포용

| 구분 | 포트 |
|---|---:|
| Backend | `8010` |
| Frontend | `8501` |

배포 주소:

```text
http://34.60.252.165:8501/
```

개발 시에는 배포 포트인 `8010`, `8501`을 사용하지 않는다.

### 팀원별 개발용

| 이름 | Jupyter 계정 | Backend | Frontend | Docker suffix |
|---|---|---:|---:|---|
| 황예원 | `spai0904` | `8011` | `8511` | `dev-spai0904` |
| 손영욱 | `spai0928` | `8012` | `8512` | `dev-spai0928` |
| 박도원 | `spai0908` | `8013` | `8513` | `dev-spai0908` |
| 채영환 | `spai0913` | `8014` | `8514` | `dev-spai0913` |
| 천지연 | `spai0925` | `8015` | `8515` | `dev-spai0925` |

---

## 2. Jupyter Server Proxy 방식

### 방식 설명

본 프로젝트의 VM 개발 환경에서는 **Jupyter Server Proxy** 방식을 사용한다.

각 팀원은 서버 내부에서 백엔드와 프론트엔드를 실행하고, 브라우저에서는 JupyterHub 주소의 `/user/{계정명}/proxy/{포트}/` 경로로 접속한다.

이 방식은 개발용 포트를 외부 방화벽에 직접 열지 않고, JupyterHub를 통해 우회 접속할 수 있다.

### 주소 형식

```text
Frontend:
http://34.60.252.165:8000/user/{JUPYTER_USER}/proxy/{FRONTEND_PORT}/

Backend Swagger:
http://34.60.252.165:8000/user/{JUPYTER_USER}/proxy/{BACKEND_PORT}/docs
```

예시: 채영환

```text
Frontend:
http://34.60.252.165:8000/user/spai0913/proxy/8514/

Backend Swagger:
http://34.60.252.165:8000/user/spai0913/proxy/8014/docs
```

---

## 3. Jupyter Server Proxy 설치

`jupyter-server-proxy`는 프로젝트 requirements에 넣지 않는다.  
JupyterLab을 실행하는 VM 공통 Python 환경에 설치한다.

현재 VM 기준 JupyterLab 실행 환경:

```text
/opt/jhub-venv
```

VM SSH 터미널에서 관리자 권한으로 설치한다.

```bash
sudo -i

/opt/jhub-venv/bin/python -m pip install jupyter-server-proxy

/opt/jhub-venv/bin/python -c "import jupyter_server_proxy; print('proxy installed')"
```

필요 시 extension을 확인하거나 활성화한다.

```bash
/opt/jhub-venv/bin/jupyter server extension list | grep -i proxy || true

/opt/jhub-venv/bin/jupyter server extension enable jupyter_server_proxy
```

설치 후 JupyterLab 서버 재시작이 필요할 수 있다.

```text
1. http://34.60.252.165:8000/hub/home 접속
2. Stop My Server 클릭
3. Start My Server 클릭
```

---

## 4. Kakao Redirect URI

카카오 개발자 콘솔에는 팀원별 redirect URI를 등록한다.

| 이름 | Kakao Redirect URI |
|---|---|
| 황예원 | `http://34.60.252.165:8000/user/spai0904/proxy/8011/api/v1/auth/kakao/callback` |
| 손영욱 | `http://34.60.252.165:8000/user/spai0928/proxy/8012/api/v1/auth/kakao/callback` |
| 박도원 | `http://34.60.252.165:8000/user/spai0908/proxy/8013/api/v1/auth/kakao/callback` |
| 채영환 | `http://34.60.252.165:8000/user/spai0913/proxy/8014/api/v1/auth/kakao/callback` |
| 천지연 | `http://34.60.252.165:8000/user/spai0925/proxy/8015/api/v1/auth/kakao/callback` |

카카오는 redirect URI가 정확히 일치해야 한다.  
계정명, 포트, path가 하나라도 다르면 로그인에 실패한다.

---

# 5. 가상환경으로 실행

가상환경 방식은 각자 `.venv`를 활성화한 뒤 백엔드와 프론트엔드를 따로 실행하는 방식이다.

## 5.1 Backend 실행

채영환 예시:

```bash
cd ~/biz-ad-ai/backend

source ../.venv/bin/activate

python -m uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 8014 \
  --reload \
  --env-file .env \
  --root-path /user/spai0913/proxy/8014
```

팀원별로 바꿀 값:

```text
--port {BACKEND_PORT}
--root-path /user/{JUPYTER_USER}/proxy/{BACKEND_PORT}
```

## 5.2 Frontend 실행

채영환 예시:

```bash
cd ~/biz-ad-ai/frontend

source ../.venv/bin/activate

export API_BASE_URL=http://127.0.0.1:8014
export API_BROWSER_BASE_URL=http://34.60.252.165:8000/user/spai0913/proxy/8014

streamlit run app.py \
  --server.address 127.0.0.1 \
  --server.port 8514 \
  --server.headless true \
  --server.enableCORS false \
  --server.enableXsrfProtection false
```

팀원별로 바꿀 값:

```text
API_BASE_URL=http://127.0.0.1:{BACKEND_PORT}
API_BROWSER_BASE_URL=http://34.60.252.165:8000/user/{JUPYTER_USER}/proxy/{BACKEND_PORT}
--server.port {FRONTEND_PORT}
```

## 5.3 `API_BASE_URL`과 `API_BROWSER_BASE_URL` 차이

| 값 | 사용 위치 | 설명 |
|---|---|---|
| `API_BASE_URL` | Streamlit 서버 내부 | 프론트 서버가 백엔드 API를 호출할 때 사용 |
| `API_BROWSER_BASE_URL` | 사용자 브라우저 | 카카오 로그인처럼 브라우저가 직접 백엔드로 이동할 때 사용 |

가상환경 실행에서는 프론트와 백엔드가 같은 VM에서 실행되므로 `API_BASE_URL`은 `127.0.0.1:{BACKEND_PORT}`를 사용한다.  
카카오 로그인 버튼은 사용자의 브라우저가 직접 접근하므로 `API_BROWSER_BASE_URL`은 Jupyter proxy 주소를 사용한다.

---

# 6. Docker로 실행

Docker 방식은 프로젝트 `.venv`를 직접 활성화하지 않고 컨테이너에서 실행하는 방식이다.

기존 `docker-compose.yml`을 그대로 실행하면 배포용 컨테이너와 충돌할 수 있으므로, 개발용 override 파일을 함께 사용한다.

---

## 6.1 개발용 Docker 이미지 정책

본 프로젝트는 배포용 이미지와 개발용 이미지를 분리한다.

```text
배포용 image:
- biz-ad-ai-backend:latest
- biz-ad-ai-frontend:latest

개발용 공용 image:
- biz-ad-ai-backend-dev:latest
- biz-ad-ai-frontend-dev:latest
```

개발용 image는 계정별로 나누지 않는다.

```text
사용하지 않는 방식:
- biz-ad-ai-backend-dev-spai0913:latest
- biz-ad-ai-backend-dev-spai0928:latest
- biz-ad-ai-backend-dev-spai0908:latest
```

계정별 image를 만들면 backend 이미지와 Docker build cache가 중복되어 VM 디스크를 크게 사용할 수 있다.  
팀원 구분은 image가 아니라 아래 값으로 처리한다.

```text
1. container_name
2. ports
3. Docker Compose project name(-p)
4. --root-path
5. API_BROWSER_BASE_URL
```

단, `requirements.txt`나 `Dockerfile`을 수정하는 작업은 공용 dev image에 영향을 줄 수 있으므로 팀에 공유한 뒤 진행한다.

---

## 6.2 `docker-compose.dev.proxy.yml` 역할

`docker-compose.dev.proxy.yml`은 기존 `docker-compose.yml`을 대체하는 파일이 아니다.  
기본 compose 설정을 읽은 뒤, 개발용 설정만 override한다.

팀원별로 주로 바꿔야 하는 값:

```text
1. container_name
2. ports
3. API_BROWSER_BASE_URL
4. --root-path
5. Jupyter 계정명
```

개발용 image 이름은 팀원별로 바꾸지 않는다.

```text
backend image:
biz-ad-ai-backend-dev:latest

frontend image:
biz-ad-ai-frontend-dev:latest
```

---

## 6.3 개발용 compose 예시

채영환 예시:

```yaml
services:
  backend:
    image: biz-ad-ai-backend-dev:latest
    container_name: biz-ad-ai-backend-dev-spai0913
    ports: !override
      - "8014:8010"

    env_file:
      - ./backend/.env

    environment:
      - HF_HOME=/app/.cache/huggingface
      - HF_HUB_CACHE=/app/.cache/huggingface/hub

    # 개발 환경에서는 production entrypoint를 사용하지 않는다.
    # Jupyter proxy root-path와 reload를 적용하기 위해 uvicorn을 직접 실행한다.
    entrypoint: !override
      - uvicorn
      - app.main:app
      - --host
      - 0.0.0.0
      - --port
      - "8010"
      - --reload
      - --root-path
      - /user/spai0913/proxy/8014

    volumes: !override
      - ./backend:/app
      - ./backend/logs-dev:/app/logs
      - /opt/hf-cache:/app/.cache/huggingface

    restart: "no"

  frontend:
    image: biz-ad-ai-frontend-dev:latest
    container_name: biz-ad-ai-frontend-dev-spai0913
    ports: !override
      - "8514:8501"

    env_file:
      - ./frontend/.env

    environment:
      - API_BASE_URL=http://backend:8010
      - API_BROWSER_BASE_URL=http://34.60.252.165:8000/user/spai0913/proxy/8014

    volumes: !override
      - ./frontend:/app

    depends_on:
      - backend

    restart: "no"
```

### 포트 의미

```yaml
ports:
  - "8014:8010"
```

의미:

```text
VM의 8014 포트
→ backend 컨테이너 내부 8010 포트
```

백엔드는 컨테이너 내부에서 `8010`으로 실행하고, 브라우저/Jupyter proxy에서는 `8014`로 접근한다.

---

## 6.4 HuggingFace 모델 캐시 설정

HF 모델 캐시는 VM의 공용 경로에서 관리한다.

```text
VM 경로:
/opt/hf-cache

컨테이너 내부 경로:
/app/.cache/huggingface
```

backend 컨테이너는 아래 환경변수와 volume mount를 사용한다.

```yaml
environment:
  - HF_HOME=/app/.cache/huggingface
  - HF_HUB_CACHE=/app/.cache/huggingface/hub

volumes:
  - /opt/hf-cache:/app/.cache/huggingface
```

`docker-compose.dev.proxy.yml`에서 `volumes: !override`를 사용하면 기본 `docker-compose.yml`의 volumes가 통째로 대체된다.  
따라서 개발용 override 파일에는 `/opt/hf-cache:/app/.cache/huggingface`를 반드시 직접 포함해야 한다.

이 설정이 없으면 팀원별 dev 컨테이너가 같은 모델을 중복 다운로드하거나, 컨테이너 내부 임시 경로에 모델을 저장할 수 있다.

---

## 6.5 Docker에서 `API_BASE_URL=http://backend:8010`을 쓰는 이유

Docker Compose 안에서는 `backend`라는 서비스명이 내부 DNS 이름으로 잡힌다.

따라서 프론트 컨테이너에서 백엔드 컨테이너로 요청할 때는 아래 주소를 사용한다.

```text
http://backend:8010
```

구조:

```text
브라우저
→ JupyterHub Proxy
→ frontend 컨테이너 8514
→ API_BASE_URL=http://backend:8010
→ backend 컨테이너 8010
```

반면 카카오 로그인처럼 브라우저가 직접 백엔드로 이동해야 하는 경우는 Docker 내부 주소를 사용할 수 없다.  
그래서 `API_BROWSER_BASE_URL`은 Jupyter proxy 주소를 사용한다.

---

## 6.6 Docker 설정 확인

실행 전에 최종 compose 설정을 확인한다.

```bash
cd ~/biz-ad-ai

docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev.proxy.yml \
  -p biz-ad-ai-dev-spai0913 \
  config
```

주요 값만 확인하려면:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev.proxy.yml \
  -p biz-ad-ai-dev-spai0913 \
  config | grep -E "image:|container_name:|published:|HF_HOME|HF_HUB_CACHE|/opt/hf-cache|root-path"
```

정상 예시:

```text
image: biz-ad-ai-backend-dev:latest
container_name: biz-ad-ai-backend-dev-spai0913
HF_HOME=/app/.cache/huggingface
HF_HUB_CACHE=/app/.cache/huggingface/hub
source: /opt/hf-cache
target: /app/.cache/huggingface
published: "8014"
--root-path
/user/spai0913/proxy/8014

image: biz-ad-ai-frontend-dev:latest
container_name: biz-ad-ai-frontend-dev-spai0913
published: "8514"
```

---

## 6.7 Docker 실행

```bash
cd ~/biz-ad-ai

docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev.proxy.yml \
  -p biz-ad-ai-dev-spai0913 \
  up --build
```

백그라운드로 실행하려면:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev.proxy.yml \
  -p biz-ad-ai-dev-spai0913 \
  up --build -d
```

이미지를 다시 빌드하지 않고 기존 dev image로만 실행하려면 `--build`를 빼면 된다.

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev.proxy.yml \
  -p biz-ad-ai-dev-spai0913 \
  up -d
```

---

## 6.8 Docker 중지

실행할 때와 같은 `-f`, `-p` 옵션을 사용한다.

```bash
cd ~/biz-ad-ai

docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev.proxy.yml \
  -p biz-ad-ai-dev-spai0913 \
  down
```

이렇게 해야 개발용 컨테이너만 내려가고 배포용 컨테이너는 건드리지 않는다.

---

## 6.9 Docker 접속 주소

채영환 기준:

```text
Frontend:
http://34.60.252.165:8000/user/spai0913/proxy/8514/

Backend Swagger:
http://34.60.252.165:8000/user/spai0913/proxy/8014/docs
```

---

## 6.10 바로 반영되는 변경

개발용 compose에서 아래 volume을 사용한다.

```yaml
backend volumes:
  - ./backend:/app
  - ./backend/logs-dev:/app/logs
  - /opt/hf-cache:/app/.cache/huggingface

frontend volumes:
  - ./frontend:/app
```

따라서 아래 변경은 비교적 바로 반영된다.

```text
1. Python 코드 수정
2. Streamlit 화면 코드 수정
3. FastAPI endpoint 수정
4. 문서 파일 수정
5. 프론트 UI 코드 수정
```

백엔드는 `--reload`로 실행하므로 코드 변경 시 자동 재시작된다.  
Streamlit도 일반적으로 코드 변경 후 브라우저 새로고침으로 반영된다.

---

## 6.11 재시작 또는 rebuild가 필요한 변경

아래 변경은 컨테이너 재시작 또는 rebuild가 필요할 수 있다.

```text
1. requirements.txt 변경
2. Dockerfile 변경
3. docker-compose.yml 변경
4. docker-compose.dev.proxy.yml 변경
5. .env 변경
6. 새 패키지 설치
```

`.env`만 바꾼 경우 보통 컨테이너 재시작이 필요하다.

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev.proxy.yml \
  -p biz-ad-ai-dev-spai0913 \
  down

docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev.proxy.yml \
  -p biz-ad-ai-dev-spai0913 \
  up
```

`requirements.txt`, `Dockerfile`을 바꾼 경우는 `--build`를 붙인다.

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev.proxy.yml \
  -p biz-ad-ai-dev-spai0913 \
  up --build
```

공용 dev image를 쓰는 구조에서는 한 사람이 의존성을 변경해 빌드하면 이후 다른 팀원의 dev 컨테이너 재생성에도 영향을 줄 수 있다.  
따라서 `requirements.txt`, `Dockerfile` 변경은 PR 또는 팀 공유 후 진행한다.

---

# 7. `.env` 설정

## 7.1 `backend/.env`

Jupyter proxy 개발 환경에서는 아래 값을 팀원별로 맞춘다.

채영환 예시:

```env
CORS_ALLOWED_ORIGINS=http://localhost:8501,http://127.0.0.1:8501,http://34.60.252.165:8501,http://34.60.252.165:8000

KAKAO_REDIRECT_URI=http://34.60.252.165:8000/user/spai0913/proxy/8014/api/v1/auth/kakao/callback
FRONTEND_BASE_URL=http://34.60.252.165:8000/user/spai0913/proxy/8514
```

팀원별로 바꿔야 하는 값:

```text
KAKAO_REDIRECT_URI=http://34.60.252.165:8000/user/{JUPYTER_USER}/proxy/{BACKEND_PORT}/api/v1/auth/kakao/callback

FRONTEND_BASE_URL=http://34.60.252.165:8000/user/{JUPYTER_USER}/proxy/{FRONTEND_PORT}
```

## 7.2 `frontend/.env`

Docker 방식에서는 `docker-compose.dev.proxy.yml`의 `environment` 값이 우선 적용된다.  
따라서 Docker 실행 기준으로는 `frontend/.env`를 반드시 수정하지 않아도 된다.

가상환경으로 직접 실행할 때는 `export API_BASE_URL`, `export API_BROWSER_BASE_URL`을 실행하거나 `.env`를 shell 환경변수로 로드해야 한다.

---

# 8. Docker Compose 실행 중 단축키

Docker Compose를 foreground로 실행하면 아래 안내가 보일 수 있다.

```text
w Enable Watch
d Detach
```

| 단축키 | 의미 |
|---|---|
| `w Enable Watch` | Docker Compose Watch 모드 활성화. 파일 변경 감지 후 sync/rebuild하는 기능 |
| `d Detach` | 로그 화면에서 빠져나오되 컨테이너는 계속 실행 |
| `Ctrl + C` | 컨테이너 실행 중지 |

현재 개발 환경은 `volumes`와 `--reload`를 사용하므로 `w`는 굳이 사용하지 않아도 된다.

---

# 9. 자주 쓰는 확인 명령어

### 포트 사용 여부 확인

```bash
ss -ltnp | grep -E ':8011|:8012|:8013|:8014|:8015|:8511|:8512|:8513|:8514|:8515' || true
```

### Docker 컨테이너 확인

```bash
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Status}}"
```

### Docker image 확인

```bash
docker images | grep -E "biz-ad-ai-backend|biz-ad-ai-frontend"
```

정상 기준:

```text
biz-ad-ai-backend:latest          # 배포용 backend image
biz-ad-ai-frontend:latest         # 배포용 frontend image
biz-ad-ai-backend-dev:latest      # 개발용 공용 backend image
biz-ad-ai-frontend-dev:latest     # 개발용 공용 frontend image
```

### Docker 로그 확인

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev.proxy.yml \
  -p biz-ad-ai-dev-spai0913 \
  logs -f
```

### 환경변수 확인

```bash
docker exec biz-ad-ai-backend-dev-spai0913 sh -lc 'env | grep -E "KAKAO|FRONTEND|CORS|HF_HOME|HF_HUB_CACHE"'

docker exec biz-ad-ai-frontend-dev-spai0913 sh -lc 'env | grep -E "API_BASE_URL|API_BROWSER_BASE_URL"'
```

### HF cache 확인

```bash
docker exec biz-ad-ai-backend-dev-spai0913 sh -lc 'du -sh /app/.cache/huggingface 2>/dev/null || true'

du -sh /opt/hf-cache 2>/dev/null || true
```

### 개발 로그 폴더 확인

```bash
ls -al ~/biz-ad-ai/backend/logs-dev
```

### Docker 디스크 사용량 확인

```bash
docker system df
```

### VM 디스크 사용량 확인

```bash
df -h /
```

---

# 10. 디스크와 캐시 관리

개발용 Docker build를 반복하면 Docker build cache가 쌓일 수 있다.  
디스크 여유 공간이 줄어든 경우 아래 명령으로 오래된 build cache를 정리한다.

```bash
docker builder prune -af --filter "until=24h"
```

더 강하게 정리해야 할 때만 전체 build cache를 삭제한다.

```bash
docker builder prune -af
```

실행 중인 컨테이너와 현재 image에는 영향이 없지만, 다음 build 시간이 길어질 수 있다.

사용하지 않는 dangling image만 정리하려면:

```bash
docker image prune -f
```

아래 명령은 운영 image까지 삭제할 수 있으므로 신중하게 사용한다.

```bash
docker system prune -a

docker image prune -a
```

---

# 11. 주의사항

```text
1. 배포 포트 8010, 8501은 개발용으로 사용하지 않는다.
2. 팀원별 backend/frontend 포트를 반드시 분리한다.
3. Jupyter proxy 주소에는 반드시 /user/{계정명}/proxy/{포트}/ 형식이 들어간다.
4. FastAPI Swagger를 proxy로 볼 때는 --root-path를 지정해야 한다.
5. 카카오 로그인은 브라우저 redirect가 필요하므로 proxy 주소를 사용해야 한다.
6. Docker 실행 시 -f, -p 옵션을 빠뜨리지 않는다.
7. Docker 중지 시에도 실행할 때와 같은 -f, -p 옵션을 사용한다.
8. 개발용 image는 배포용 image와 분리한다.
   - 배포용: biz-ad-ai-backend:latest, biz-ad-ai-frontend:latest
   - 개발용: biz-ad-ai-backend-dev:latest, biz-ad-ai-frontend-dev:latest
9. 개발용 image는 계정별로 나누지 않는다.
   팀원 구분은 container_name, ports, Docker Compose project name(-p)으로 처리한다.
10. docker-compose.dev.proxy.yml에서 volumes: !override를 사용하는 경우,
    /opt/hf-cache:/app/.cache/huggingface 마운트를 반드시 포함한다.
11. Docker 개발 실행 시 frontend의 API_BASE_URL은 http://backend:8010을 사용한다.
12. API_BROWSER_BASE_URL은 브라우저가 접근 가능한 Jupyter proxy backend 주소를 사용한다.
13. requirements.txt 또는 Dockerfile을 수정하는 작업은 팀에 공유한 뒤 진행한다.
14. production docker-entrypoint.sh는 개발용 Docker 실행에서 사용하지 않는다.
    개발용은 uvicorn --reload --root-path 방식으로 실행한다.
```
