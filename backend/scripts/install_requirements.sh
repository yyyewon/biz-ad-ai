#!/usr/bin/env bash
# GPU VM / Jupyter: backend 의존성 1회 설치
#
# 사용법 (프로젝트 루트):
#   bash backend/scripts/install_requirements.sh
#
# 주의: pip install -r requirements.txt 한 번만으로는 gptqmodel 빌드가 실패할 수 있음.
#       이 스크립트가 torch 선설치 + PYTHONPATH 정리를 처리함.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BACKEND="$(cd "$(dirname "$0")/.." && pwd)"

unset PYTHONPATH
export PYTHONNOUSERSITE=1

cd "$ROOT"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

# shellcheck source=/dev/null
source .venv/bin/activate

echo "[install] python: $(which python)"
echo "[install] pip:    $(which python -m pip)"

python -m pip install -U pip setuptools wheel

echo "[install] 1/5 torch..."
python -m pip install -r "$BACKEND/requirements-torch.txt"

echo "[install] 2/5 numpy (gptqmodel pin)..."
python -m pip install "numpy==2.2.6"

if [[ -d /usr/local/cuda/bin ]]; then
  export CUDA_HOME=/usr/local/cuda
  export PATH="$CUDA_HOME/bin:$PATH"
  echo "[install] CUDA_HOME=$CUDA_HOME"
fi

echo "[install] 3/5 backend..."
python -m pip install -r "$BACKEND/requirements.txt" --no-build-isolation

echo "[install] 4/5 frontend..."
python -m pip install -r "$ROOT/frontend/requirements.txt"

echo "[install] 5/5 numpy pin (frontend가 올린 버전 되돌림)..."
python -m pip install "numpy==2.2.6"

echo "[install] fonts..."
(cd "$BACKEND" && python scripts/setup_fonts.py)

cat <<EOF

[install] 완료.

매 터미널:
  cd $ROOT
  unset PYTHONPATH && export PYTHONNOUSERSITE=1
  source .venv/bin/activate

모델 미리 받기 (선택, 첫 포스터 요청 전):
  cd $BACKEND && python scripts/prefetch_models.py

EOF
