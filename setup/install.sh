#!/usr/bin/env bash
source "$(dirname "$0")/utils.sh"

info "Installing system dependencies..."

export DEBIAN_FRONTEND=noninteractive

retry 3 apt-get update -y
retry 3 apt-get install -y \
    python3 python3-venv python3-pip \
    ffmpeg libsm6 libxext6 libgl1 \
    git curl wget netcat-openbsd \
    mysql-server