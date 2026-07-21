# Model Weights

이 폴더는 로컬 또는 VM에서 사용하는 모델 weight/checkpoint 파일을 두기 위한 위치입니다.

주의:
- `.safetensors`, `.ckpt`, `.pt`, `.pth`, `.bin` 같은 대용량 모델 파일은 Git에 커밋하지 않습니다.
- Hugging Face 모델은 기본적으로 `HF_HOME` 또는 `HF_HUB_CACHE`에 캐시됩니다.
- 팀 공용 캐시는 필요 시 `/opt/hf-cache` 같은 외부 경로를 사용합니다.
