# HuggingFace 모델 캐시 관리 가이드

이 문서는 Biz Ad AI 프로젝트에서 HuggingFace 모델 파일을 어디에 저장하고, Docker 개발/배포 환경에서 어떻게 불러오며, 캐시를 어떻게 관리할지 정리한 문서입니다.

## 1. 기본 원칙

HuggingFace 모델 파일은 GitHub 저장소나 Docker 이미지에 포함하지 않습니다.

모델 파일은 VM host의 `/opt/hf-cache`에 저장하고, Docker backend 컨테이너는 이 경로를 mount해서 사용합니다.

```text
VM Host
└── /opt/hf-cache
    ├── hub
    └── xet

Docker Backend Container
└── /app/.cache/huggingface
    └── VM Host의 /opt/hf-cache와 연결됨
```

## 2. Docker cache mount 설정

backend 컨테이너는 아래 설정을 통해 HuggingFace 캐시 위치를 고정합니다.

```yaml
environment:
  - HF_HOME=/app/.cache/huggingface
  - HF_HUB_CACHE=/app/.cache/huggingface/hub

volumes:
  - /opt/hf-cache:/app/.cache/huggingface
```

의미는 다음과 같습니다.

```text
VM Host의 /opt/hf-cache
→ Docker 컨테이너 내부의 /app/.cache/huggingface 로 연결
```

따라서 컨테이너가 삭제되거나 재생성되어도 모델 파일은 VM의 `/opt/hf-cache`에 남습니다.

## 3. 모델 로드 흐름

### 3.1 모델 파일이 캐시에 없는 경우

```text
1. backend 컨테이너에서 모델 로드 요청
2. HuggingFace Hub에서 모델 파일 다운로드
3. /opt/hf-cache에 모델 파일 저장
4. 저장된 파일을 읽어 모델 로드
5. GPU 메모리에 모델 적재
6. 이미지 생성 실행
```

이 경우 첫 실행 시간이 길어집니다.

### 3.2 모델 파일이 캐시에 있는 경우

```text
1. backend 컨테이너에서 모델 로드 요청
2. HuggingFace Hub에서 다시 다운로드하지 않음
3. /opt/hf-cache에 있는 모델 파일을 읽음
4. GPU 메모리에 모델 적재
5. 이미지 생성 실행
```

컨테이너를 재시작하면 GPU 메모리에 올라간 모델은 사라지지만, `/opt/hf-cache`의 모델 파일은 유지됩니다.

### 3.3 같은 backend 프로세스에서 두 번째 요청부터

```text
1. 이미 GPU 메모리에 올라간 모델 객체 재사용
2. model_load 단계 생략
3. inference만 실행
```

즉, 캐시는 두 종류로 나누어 이해해야 합니다.

| 구분 | 위치 | 역할 | 재시작 시 유지 여부 |
|---|---|---|---|
| 디스크 캐시 | `/opt/hf-cache` | 모델 파일 저장 | 유지됨 |
| 메모리 캐시 | backend 프로세스 / GPU 메모리 | 로드된 모델 재사용 | 사라짐 |

## 4. 현재 캐시에 저장될 수 있는 주요 모델

현재 SDXL Lightning 테스트 기준으로 다음 모델 파일들이 `/opt/hf-cache`에 저장될 수 있습니다.

```text
stabilityai/stable-diffusion-xl-base-1.0
ByteDance/SDXL-Lightning
h94/IP-Adapter
```

HuggingFace 캐시 폴더에서는 보통 아래와 같은 이름으로 보입니다.

```text
/opt/hf-cache/hub/models--stabilityai--stable-diffusion-xl-base-1.0
/opt/hf-cache/hub/models--ByteDance--SDXL-Lightning
/opt/hf-cache/hub/models--h94--IP-Adapter
```

## 5. 캐시 상태 확인 명령어

### 전체 캐시 용량 확인

```bash
du -sh /opt/hf-cache
```

### 모델별 캐시 용량 확인

```bash
du -sh /opt/hf-cache/hub/models--*
```

### 캐시 목록 확인

```bash
ls -lh /opt/hf-cache/hub | grep models--
```

### 디스크 여유 공간 확인

```bash
df -h
```

### backend 컨테이너가 `/opt/hf-cache`를 mount했는지 확인

운영 컨테이너 기준:

```bash
docker inspect biz-ad-ai-backend \
  --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
```

개발 컨테이너 기준:

```bash
docker inspect biz-ad-ai-backend-dev-spai0913 \
  --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
```

정상 예시:

```text
/opt/hf-cache -> /app/.cache/huggingface
```

### 컨테이너 내부 HuggingFace 환경변수 확인

운영 컨테이너 기준:

```bash
docker exec biz-ad-ai-backend sh -lc 'echo $HF_HOME && echo $HF_HUB_CACHE'
```

정상 예시:

```text
/app/.cache/huggingface
/app/.cache/huggingface/hub
```

## 6. 캐시 삭제 방법

캐시를 삭제하면 모델 파일이 사라집니다. 다음 실행 때 필요한 모델을 다시 다운로드합니다.

삭제 전에는 반드시 디스크 상태와 실행 중인 컨테이너를 확인합니다.

```bash
df -h
du -sh /opt/hf-cache
docker ps
```

### 6.1 특정 모델만 삭제

사용하지 않는 모델만 골라서 삭제하는 방식입니다. 전체 삭제보다 안전합니다.

예시:

```bash
sudo rm -rf /opt/hf-cache/hub/models--ByteDance--SDXL-Lightning
sudo rm -rf /opt/hf-cache/hub/models--h94--IP-Adapter
sudo rm -rf /opt/hf-cache/hub/models--stabilityai--stable-diffusion-xl-base-1.0
```

삭제 후 권한을 다시 확인합니다.

```bash
sudo chown -R spai0913:spai0913 /opt/hf-cache
chmod -R u+rwX,go+rX /opt/hf-cache
```

### 6.2 전체 캐시 삭제

전체 캐시 삭제는 최후 수단으로만 사용합니다.

운영/개발 컨테이너가 모델을 사용 중이지 않은지 확인한 뒤 진행합니다.

```bash
sudo rm -rf /opt/hf-cache

sudo mkdir -p /opt/hf-cache
sudo chown -R spai0913:spai0913 /opt/hf-cache
chmod -R u+rwX,go+rX /opt/hf-cache
```

삭제 후 첫 모델 실행은 다시 다운로드가 필요하므로 오래 걸릴 수 있습니다.

## 7. 새 모델을 추가할 때 캐시 동작

새 HuggingFace 모델을 추가하더라도 모델 파일을 Git에 올리지 않습니다.

모델 설정을 추가한 뒤 처음 실행하면 HuggingFace가 필요한 파일을 자동으로 `/opt/hf-cache`에 다운로드합니다.

```text
새 모델 최초 실행
→ /opt/hf-cache에 해당 모델 파일 없음
→ HuggingFace Hub에서 다운로드
→ /opt/hf-cache에 저장
→ 이후 실행부터 캐시 재사용
```

### 새 모델 추가 전 확인

큰 모델을 추가하기 전에는 반드시 디스크 여유 공간을 확인합니다.

```bash
df -h
du -sh /opt/hf-cache
du -sh /opt/hf-cache/hub/models--*
```

### 새 모델을 미리 캐시에 받아두는 방법

가장 단순한 방법은 실제 이미지 생성 요청을 한 번 실행해서 자동 다운로드되게 두는 것입니다.

모델 파일 하나만 명시적으로 받을 때는 아래처럼 받을 수 있습니다.

```bash
docker exec biz-ad-ai-backend sh -lc 'python - <<PY
from huggingface_hub import hf_hub_download

hf_hub_download(
    repo_id="ByteDance/SDXL-Lightning",
    filename="sdxl_lightning_4step_unet.safetensors",
)
PY'
```

단, `from_pretrained()`로 로드하는 모델은 필요한 파일이 여러 개일 수 있으므로 일반적으로는 실제 기능을 한 번 실행해서 캐시를 채우는 방식이 더 안전합니다.

## 8. Git에 올리면 안 되는 것

아래 항목은 GitHub에 올리지 않습니다.

```text
/opt/hf-cache
hf-cache/
models/weights/*.safetensors
models/weights/*.bin
models/weights/*.ckpt
models/weights/*.pt
models/weights/*.pth
backend/.env
frontend/.env
backend/logs/
backend/logs-dev/
experiments/
```

모델 파일은 코드 저장소가 아니라 VM의 `/opt/hf-cache`에서 관리합니다.

## 9. 팀 공통 운영 규칙

- `/opt/hf-cache`는 팀 공용 HuggingFace 모델 캐시로 사용합니다.
- 모델 파일은 GitHub에 올리지 않습니다.
- 새 모델을 테스트하기 전에는 `df -h`로 디스크 여유 공간을 확인합니다.
- 캐시를 삭제하기 전에는 팀원에게 공유합니다.
- 전체 캐시 삭제보다 특정 모델 폴더 삭제를 우선합니다.
- 컨테이너를 재시작하면 GPU 메모리 캐시는 사라지지만 `/opt/hf-cache`의 모델 파일은 유지됩니다.
- 배포 Docker와 개발 Docker는 같은 `/opt/hf-cache`를 mount해서 모델 파일을 재사용합니다.
