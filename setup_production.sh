#!/usr/bin/env bash

# Unified ANPR Production Setup Script
# - idempotent installer for the current project layout
# - creates/uses `anpr_env` virtualenv, installs requirements
# - configures systemd services and sudoers entries

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/anpr_env"
SERVICE_USER="${SUDO_USER:-$(whoami)}"
PYTHON_BIN="python3"

# color helpers
info(){ echo -e "\033[1;32m[INFO]\033[0m $*"; }
warn(){ echo -e "\033[1;33m[WARN]\033[0m $*"; }
err(){ echo -e "\033[1;31m[ERROR]\033[0m $*"; }

echo "=========================================="
echo "ANPR Production Setup"
echo "=========================================="
echo ""
echo "Detected Configuration:"
echo "  Project Directory: $PROJECT_DIR"
echo "  Service User: $SERVICE_USER"
echo "  Virtual Env: $VENV_DIR"
echo ""

# Ask for MySQL port (optional)
read -p "Enter MySQL port (default: 3306): " MYSQL_PORT
MYSQL_PORT="${MYSQL_PORT:-3306}"
info "Using MySQL port: $MYSQL_PORT"
export MYSQL_PORT

echo ""

# 1) Ensure system deps (best-effort, requires sudo)
if command -v apt-get &>/dev/null; then
    info "Installing system packages (requires sudo)..."
    sudo apt-get update -y
    sudo apt-get install -y python3-venv python3-pip ffmpeg libsm6 libxext6 libfontconfig1 libxrender1 libgl1-mesa-glx git curl wget || warn "Some system packages failed to install"
else
    warn "apt-get not found — skipping system package installation"
fi

# 2) Create or reuse virtual environment
if [ ! -d "$VENV_DIR" ]; then
    info "Creating virtualenv at $VENV_DIR"
    $PYTHON_BIN -m venv "$VENV_DIR"
fi

info "Activating virtualenv"
source "$VENV_DIR/bin/activate"
pip install --upgrade pip setuptools wheel
if [ -f "$PROJECT_DIR/requirements.txt" ]; then
    info "Installing Python requirements"
    pip install -r "$PROJECT_DIR/requirements.txt" || warn "pip install reported errors"
else
    warn "requirements.txt not found — skipping pip install"
fi

# 3) Initialize database if init script exists
if [ -f "$PROJECT_DIR/init_database.py" ]; then
    if command -v mysql &>/dev/null; then
        info "Initializing database (init_database.py)"
        "$VENV_DIR/bin/python" "$PROJECT_DIR/init_database.py" || warn "Database init returned non-zero"
    else
        warn "MySQL client not found — skipping DB initialization"
    fi
else
    warn "init_database.py not found — skipping DB initialization"
fi

# 3a) Create admin user if creation script exists
if [ -f "$PROJECT_DIR/create_admin_user.py" ]; then
    if command -v mysql &>/dev/null; then
        info "Creating admin user (create_admin_user.py)"
        "$VENV_DIR/bin/python" "$PROJECT_DIR/create_admin_user.py" || warn "Admin user creation returned non-zero"
    else
        warn "MySQL client not found — skipping admin user creation"
    fi
else
    warn "create_admin_user.py not found — skipping admin user creation"
fi

# 4) Ensure project service files are installed and configured
info "Installing systemd service files"

# Prepare service file for multi-camera
SC_MULTI_SRC="$PROJECT_DIR/anpr-multi-camera.service"
SC_MULTI_DST="/etc/systemd/system/anpr-multi-camera.service"

if [ -f "$SC_MULTI_SRC" ]; then
    sudo cp "$SC_MULTI_SRC" "$SC_MULTI_DST"
else
    warn "$SC_MULTI_SRC not found — generating service file"
    sudo tee "$SC_MULTI_DST" > /dev/null <<EOF
[Unit]
Description=ANPR Multi-Camera Service
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=/bin/bash $PROJECT_DIR/start_anpr_service.sh
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment="PATH=$VENV_DIR/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

[Install]
WantedBy=multi-user.target
EOF
fi

# Prepare service file for admin panel
SC_ADMIN_SRC="$PROJECT_DIR/anpr-admin-panel.service"
SC_ADMIN_DST="/etc/systemd/system/anpr-admin-panel.service"

if [ -f "$SC_ADMIN_SRC" ]; then
    sudo cp "$SC_ADMIN_SRC" "$SC_ADMIN_DST"
else
    warn "$SC_ADMIN_SRC not found — generating admin service file"
    sudo tee "$SC_ADMIN_DST" > /dev/null <<EOF
[Unit]
Description=ANPR Admin Panel Web Interface
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$PROJECT_DIR/admin_panel
ExecStart=/bin/bash $PROJECT_DIR/admin_panel/start_admin.sh
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment="PATH=$VENV_DIR/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

[Install]
WantedBy=multi-user.target
EOF
fi

info "Reloading systemd and enabling services"
sudo systemctl daemon-reload
sudo systemctl enable anpr-multi-camera.service || warn "Failed to enable multi-camera service"
sudo systemctl enable anpr-admin-panel.service || warn "Failed to enable admin-panel service"

# 5) Setup sudoers entries (optional)
if [ -f "$PROJECT_DIR/setup_sudoers.sh" ]; then
    info "Configuring sudoers for service control"
    sudo bash "$PROJECT_DIR/setup_sudoers.sh" || warn "setup_sudoers.sh reported errors"
else
    warn "setup_sudoers.sh not found — you may need to create sudoers entries manually"
fi

# 6) Start services
info "Starting services"
sudo systemctl start anpr-multi-camera.service || warn "anpr-multi-camera failed to start"
sudo systemctl start anpr-admin-panel.service || warn "anpr-admin-panel failed to start"

info "Setup finished — service statuses:"
sudo systemctl status anpr-multi-camera.service --no-pager -l || true
sudo systemctl status anpr-admin-panel.service --no-pager -l || true

echo "=========================================="
echo "One-step setup complete"
echo "Project directory: $PROJECT_DIR"
echo "Virtualenv: $VENV_DIR"
echo "Services: anpr-multi-camera, anpr-admin-panel"
echo "If detection is slow, consider configuring GPU drivers or running on stronger hardware."
echo "=========================================="

