# Metrics · 팀 공용 JSONL 세팅

개인 dev(801x/851x)와 배포(8010/8501)에서 나온 성능·품질 로그를 **한 폴더**에 모아 **8555 대시보드**에서 같이 봅니다.

---

## 흐름

```text
dev backend (8013 등) ──┐
다른 팀원 backend      ──┼──→ /opt/biz-ad-ai-team-logs/*.jsonl
배포 backend (8010)    ──┘              │
                                       ↓
                         Metrics UI (8555, 팀당 1개)
```

- JSONL: `performance.jsonl`, `quality.jsonl`
- 대시보드: `http://34.60.252.165:8000/user/spai0908/proxy/8555/`
- dev / prod 구분: JSONL `extra`의 `source_user`, `deploy_env` (대시보드 필터)

---

## 1. VM 공통 (최초 1회)

```bash
sudo mkdir -p /opt/biz-ad-ai-team-logs
sudo chmod 1777 /opt/biz-ad-ai-team-logs
```

---

## 2. 개인 dev (각자)

### 2.1 compose 복사·수정

```bash
cp docker-compose.dev.proxy.example.yml docker-compose.dev.proxy.yml
mkdir -p backend/logs-dev   # sudo 없을 때 기본 로그 폴더
```

**로그 경로 (`.env` 또는 shell, 선택):**

```env
# sudo 없음 → 생략 (기본 ./backend/logs-dev, 본인만)
# 팀 공용 → sudo 있는 팀원이 /opt 폴더 만든 뒤:
METRICS_LOG_HOST_PATH=/opt/biz-ad-ai-team-logs
```

`docker-compose.dev.proxy.yml`에서 **본인 계정·포트**로 바꿉니다 (`spai0908` / `8013` / `8513` 예시):

| 항목 | 값 |
|---|---|
| `container_name` | `biz-ad-ai-backend-dev-spai0908` 등 |
| backend ports | `"8013:8010"` |
| frontend ports | `"8513:8501"` |
| `--root-path` | `/user/spai0908/proxy/8013` |
| `API_BROWSER_BASE_URL` | `http://34.60.252.165:8000/user/spai0908/proxy/8013` |
| `METRICS_SOURCE_USER` | `spai0908` |
| `METRICS_BACKEND_PORT` | `8013` |
| `METRICS_FRONTEND_PORT` | `8513` |
| logs | 기본 `logs-dev` (팀 공용은 `.env`에 `METRICS_LOG_HOST_PATH=/opt/biz-ad-ai-team-logs`) |

> `./backend/logs-dev` 는 **본인 dev만** 대시board에 보임. 팀 합산은 `/opt/...` 필요.

### 2.2 `frontend/.env`

```env
API_BASE_URL=http://backend:8010
```

### 2.3 실행

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev.proxy.yml \
  -p biz-ad-ai-dev-spai0908 \
  up -d --build
```

- `backend`, `frontend` → **본인마다** up
- `metrics` → **팀에서 1명만** up (8555, 이미 떠 있으면 생략)

---

## 3. 배포 prod

VM `/opt/biz-ad-ai/.env`에 추가:

```env
METRICS_LOG_HOST_PATH=/opt/biz-ad-ai-team-logs
METRICS_SOURCE_USER=prod
METRICS_BACKEND_PORT=8010
METRICS_FRONTEND_PORT=8501
METRICS_DEPLOY_ENV=prod
```

```bash
cd /opt/biz-ad-ai
docker compose up -d --build
```

배포 stack에는 metrics를 따로 안 띄워도 됩니다. dev 쪽 8555가 같은 JSONL을 읽습니다.

---

## 4. 확인

```bash
# JSONL 쌓였는지
tail -n 3 /opt/biz-ad-ai-team-logs/performance.jsonl

# metrics 컨테이너
docker ps --filter name=biz-ad-ai-metrics-dev-shared
```

광고 1회 생성 → 8555 UI **새로고침** → `source_user` / `deploy_env` 필터로 dev·prod 확인.

---

## 자주 하는 실수

| 증상 | 해결 |
|---|---|
| 대시보드 비어 있음 | backend volume을 `/opt/biz-ad-ai-team-logs:/app/logs`로 |
| 배포 로그만 없음 | `/opt/biz-ad-ai/.env`에 `METRICS_LOG_HOST_PATH` 추가 |
| 8555 접속 불가 | metrics 컨테이너 1개 up |
| 프론트 API 실패 | `frontend/.env` → `API_BASE_URL=http://backend:8010` |

---

## 관련 파일

| 파일 | Git | 비고 |
|---|---|---|
| `docker-compose.dev.proxy.example.yml` | O | 템플릿 |
| `docker-compose.dev.proxy.yml` | X | 본인 dev 설정 |
| `frontend/.env` | X | Docker dev용 API URL |
| `/opt/biz-ad-ai/.env` | X | 배포 METRICS 설정 |

더 자세한 dev 실행: [jupyterlab-dev-server-guide.md](./jupyterlab-dev-server-guide.md)
