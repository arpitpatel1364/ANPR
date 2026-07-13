#!/usr/bin/env bash
source "$(dirname "$0")/utils.sh"

VENV="$ROOT_DIR/anpr_env"

info "Setting up Python environment..."

command -v /usr/bin/python3 || die "Python3 missing"

[[ ! -d "$VENV" ]] && /usr/bin/python3 -m venv "$VENV"

source "$VENV/bin/activate"

retry 3 pip install --upgrade pip

[[ -f "$ROOT_DIR/requirements.txt" ]] && retry 3 pip install -r "$ROOT_DIR/requirements.txt"
[[ -f "$ROOT_DIR/admin_panel/requirements.txt" ]] && retry 3 pip install -r "$ROOT_DIR/admin_panel/requirements.txt"

########################################
# PADDLE DEVICE SETUP (GPU or CPU)
########################################

PADDLE_DEVICE_FILE="$ROOT_DIR/newmodel/.paddle_device"
mkdir -p "$(dirname "$PADDLE_DEVICE_FILE")"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
info "🔍  Detecting GPU for Awiros ANPR-OCR (PaddlePaddle)..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

_USE_GPU="no"

if command -v nvidia-smi &>/dev/null && nvidia-smi --query-gpu=name --format=csv,noheader &>/dev/null 2>&1; then
    echo ""
    echo "  ✅  NVIDIA GPU detected:"
    nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader \
        | awk -F',' '{printf "      GPU %s : %s  (%s RAM)\n", $1, $2, $3}'
    echo ""
    echo "  The GPU version of PaddlePaddle gives significantly faster OCR."
    echo "  (You can change this later by re-running setup.sh)"
    echo ""
    printf "  ❓  Use GPU (CUDA) version of PaddlePaddle? [Y/n]: "
    read -r _ANSWER </dev/tty
    _ANSWER="${_ANSWER:-Y}"
    if [[ "$_ANSWER" =~ ^[Yy] ]]; then
        _USE_GPU="yes"
    fi
else
    echo ""
    echo "  ℹ️   No NVIDIA GPU detected — using CPU version of PaddlePaddle."
fi

echo ""

if [[ "$_USE_GPU" == "yes" ]]; then
    info "🧹  Uninstalling any existing PaddlePaddle packages..."
    pip uninstall -y paddlepaddle paddlepaddle-gpu

    # Detect CUDA version
    CUDA_VER=""
    if command -v nvcc &>/dev/null; then
        CUDA_VER=$(nvcc --version | grep -oP "release \K[0-9]+\.[0-9]+")
    elif command -v nvidia-smi &>/dev/null; then
        CUDA_VER=$(nvidia-smi 2>/dev/null | grep -oP "CUDA Version: \K[0-9]+\.[0-9]+")
    fi

    info "🔍  Detected CUDA version: ${CUDA_VER:-unknown}"

    PADDLE_PKG="paddlepaddle-gpu==2.6.2"
    INDEX_URL="https://pypi.org/simple"

    if [[ "$CUDA_VER" =~ ^12\. ]] || [[ "$CUDA_VER" =~ ^13\. ]]; then
        PADDLE_PKG="paddlepaddle-gpu==2.6.2.post120"
        INDEX_URL="https://www.paddlepaddle.org.cn/packages/stable/cu120/"
    elif [[ "$CUDA_VER" =~ ^11\. ]]; then
        PADDLE_PKG="paddlepaddle-gpu==2.6.2.post118"
        INDEX_URL="https://www.paddlepaddle.org.cn/packages/stable/cu118/"
    fi

    info "📦  Installing $PADDLE_PKG (CUDA) ..."
    retry 3 pip install "$PADDLE_PKG" -i "$INDEX_URL" "safetensors>=0.4.0" \
        "PyYAML>=6.0" "shapely>=2.0.0"
    echo "gpu" > "$PADDLE_DEVICE_FILE"
    info "✅  PaddlePaddle GPU installed — Awiros-OCR will use GPU."

    # Automatically symlink cuDNN 9 libraries inside virtualenv to ensure compatibility
    info "🔗  Configuring cuDNN compatibility links in virtualenv..."
    SITE_PACKAGES=$(python3 -c "import site; print(site.getsitepackages()[0])" 2>/dev/null)
    if [[ -z "$SITE_PACKAGES" ]]; then
        SITE_PACKAGES=$(find "$VENV/lib" -name "site-packages" -type d | head -n 1)
    fi
    CUDNN_LIB_DIR="$SITE_PACKAGES/nvidia/cudnn/lib"
    if [[ -d "$CUDNN_LIB_DIR" ]]; then
        info "      Found cuDNN library dir: $CUDNN_LIB_DIR"
        (
            cd "$CUDNN_LIB_DIR"
            for f in *.so.9; do
                if [[ -f "$f" ]]; then
                    base="${f%.9}"
                    ln -sf "$f" "$base"
                    ln -sf "$f" "$base.8"
                fi
            done
        )
        info "      cuDNN compatibility links created successfully."
    else
        info "      No virtualenv cuDNN libraries found to link (using system cuDNN)."
    fi
else
    info "🧹  Uninstalling any existing PaddlePaddle packages..."
    pip uninstall -y paddlepaddle paddlepaddle-gpu

    info "📦  Installing paddlepaddle==2.6.2 (CPU) ..."
    retry 3 pip install "paddlepaddle==2.6.2" "safetensors>=0.4.0" \
        "PyYAML>=6.0" "shapely>=2.0.0"
    echo "cpu" > "$PADDLE_DEVICE_FILE"
    info "✅  PaddlePaddle CPU installed — Awiros-OCR will use CPU."
fi

# Reclaim ownership of the virtual environment to the real user if run as root/sudo
REAL_USER="${SUDO_USER:-$(whoami)}"
if [[ "$REAL_USER" != "root" ]]; then
    info "👤  Reclaiming ownership of virtual environment for user $REAL_USER..."
    chown -R "$REAL_USER:$REAL_USER" "$VENV"
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""