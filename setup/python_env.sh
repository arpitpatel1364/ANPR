#!/usr/bin/env bash
source "$(dirname "$0")/utils.sh"

VENV="$ROOT_DIR/anpr_env"

info "Setting up Python environment..."

command -v python3 || die "Python3 missing"

[[ ! -d "$VENV" ]] && python3 -m venv "$VENV"

source "$VENV/bin/activate"

retry 3 pip install --upgrade pip

[[ -f "$ROOT_DIR/requirements.txt" ]] && retry 3 pip install -r "$ROOT_DIR/requirements.txt"
[[ -f "$ROOT_DIR/admin_panel/requirements.txt" ]] && retry 3 pip install -r "$ROOT_DIR/admin_panel/requirements.txt"