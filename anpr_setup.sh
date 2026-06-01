#!/usr/bin/env bash
# ANPR_Setup.sh
# A wrapper script to automate the common installation/setup tasks for the
# ANPR multi-camera system.
#
# Usage: sudo ./ANPR_Setup.sh [options]
# Options will be added as we evolve the script; run without arguments for an
# interactive checklist.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

function die() {
    echo "ERROR: $*" >&2
    exit 1
}

function ensure_root() {
    if [[ $EUID -ne 0 ]]; then
        die "This setup script must be run as root (sudo)";
    fi
}

function create_python_env() {
    # create or activate a virtual environment (venv) named anpr_env
    echo "==> creating python virtual environment (venv)"
    python3 -m venv anpr_env || die "failed to create venv"
    echo "==> activating venv and installing requirements"
    # shellcheck disable=SC1091
    source anpr_env/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
    deactivate
}

function init_database() {
    echo "==> initializing MySQL database"
    # note: assumes mysql/mariadb is running and environment variables have correct credentials
    python3 scripts/init_database.py || die "database initialization failed"
}

function create_admin_user_interactive() {
    echo "==> creating admin user"
    python3 scripts/create_admin_user.py || die "admin user creation failed"
}

function install_systemd_services() {
    echo "==> installing systemd units"
    cp anpr-multi-camera.service /etc/systemd/system/
    cp anpr-admin-panel.service /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable anpr-multi-camera
    systemctl enable anpr-admin-panel
}

function show_help() {
    cat <<'EOF'
ANPR System Setup

Usage: sudo ./anpr_setup.sh [COMMAND]

Commands:
  all       Perform all setup steps (env, db, admin user, services)
  env       Create Python virtual environment and install dependencies
  db        Initialize the MySQL/MariaDB database schema
  admin     Prompt to create an administrator user
  services  Install & enable systemd service units
  help      Show this help message

Examples:
  sudo ./anpr_setup.sh all
  sudo ./anpr_setup.sh env
  sudo ./anpr_setup.sh db
  sudo ./anpr_setup.sh admin
  sudo ./anpr_setup.sh services
EOF
}

# main dispatcher
if [[ $# -eq 0 ]]; then
    show_help
    exit 0
fi

case "$1" in
    all)
        ensure_root
        create_python_env
        init_database
        create_admin_user_interactive
        install_systemd_services
        ;;
    env)
        create_python_env
        ;;
    db)
        init_database
        ;;
    admin)
        create_admin_user_interactive
        ;;
    services)
        ensure_root
        install_systemd_services
        ;;
    help)
        show_help
        ;;
    *)
        echo "Unknown command: $1" >&2
        show_help
        exit 1
        ;;
esac
