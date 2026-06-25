#!/usr/bin/env bash
set -Eeuo pipefail

# Detect ROOT (where this file is)
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP_DIR="$ROOT_DIR/setup"

source "$SETUP_DIR/utils.sh"

trap 'err "❌ FAILED → running rollback"; bash "$SETUP_DIR/rollback.sh"' ERR

info "🚀 Starting FULL system setup..."

bash "$SETUP_DIR/validate.sh"
bash "$SETUP_DIR/install.sh"
bash "$SETUP_DIR/python_env.sh"
bash "$SETUP_DIR/db_setup.sh"
bash "$SETUP_DIR/sudoers_setup.sh"
bash "$SETUP_DIR/service_setup.sh"

echo ""
read -p "Do you want to add a web icon and shortcut on the desktop? (y/n): " ADD_SHORTCUT
if [[ "$ADD_SHORTCUT" =~ ^[Yy](es)?$ ]]; then
    bash "$SETUP_DIR/shortcut_setup.sh"
else
    info "Skipping desktop shortcut creation."
fi

info "✅ SETUP COMPLETE SUCCESSFULLY"