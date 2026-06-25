#!/usr/bin/env bash
export PYTHONPATH="${PYTHONPATH:-}"
# 🔥 ANPR Service Runner & Manager (Production Ready)

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$SCRIPT_DIR"
VENV_ACTIVATE="$ROOT_DIR/anpr_env/bin/activate"
LOG_FILE="$ROOT_DIR/anpr_service.log"

########################################
# BASIC UTILS
########################################

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

die() {
    log "ERROR: $*"
    exit 1
}

########################################
# HELP MENU
########################################

show_help() {
    cat <<EOF
ANPR Service Manager

Usage: ./run.sh [COMMAND] [SERVICE]

Commands:
  backend                      Run backend (systemd use)
  admin                        Run admin panel (systemd use)

  start <all|backend|admin>
  stop <all|backend|admin>
  restart <all|backend|admin>
  status <all|backend|admin>
  logs <all|backend|admin>
EOF
}

########################################
# MYSQL CHECK
########################################

is_mysql_ready() {
    systemctl is-active --quiet mysql
}

wait_for_mysql() {
    local timeout_secs=${1:-60}
    log "Waiting for MySQL service to be active..."

    for ((i=0; i<timeout_secs; i+=2)); do
        if is_mysql_ready; then
            log "MySQL is ready"
            return 0
        fi
        sleep 2
    done

    die "MySQL not ready after ${timeout_secs}s"
}

ensure_mysql_running() {
    export DB_HOST="${DB_HOST:-127.0.0.1}"
    export DB_PORT="${DB_PORT:-3306}"

    if is_mysql_ready; then
        log "MySQL already running"
        return 0
    fi

    log "Verifying MySQL is running..."
    
    if ! systemctl is-active --quiet mysql; then
        die "MySQL service is not running. Start it first or rely on systemd dependencies."
    fi

    wait_for_mysql 60
}

########################################
# BACKEND
########################################

run_backend() {
    ensure_mysql_running

    cd "$ROOT_DIR"

    [[ -f "$VENV_ACTIVATE" ]] || die "Virtualenv missing. Run setup.sh first"
    source "$VENV_ACTIVATE"

    [[ -f "app_multi_camera_lprnet.py" ]] || die "Backend file missing"

    export PYTHONPATH="$ROOT_DIR:$PYTHONPATH"
    
    # Force execution on CPU by hiding all CUDA devices
    export CUDA_VISIBLE_DEVICES="-1"

    log "Starting backend service..."

    exec python -u app_multi_camera_lprnet.py 2>&1 | tee -a "$LOG_FILE"
}

########################################
# ADMIN PANEL
########################################

run_admin() {
    ensure_mysql_running

    cd "$ROOT_DIR/admin_panel"

    [[ -f "$VENV_ACTIVATE" ]] || die "Virtualenv missing"
    source "$VENV_ACTIVATE"

    mkdir -p static/images/verified_plates static/css static/js templates

    export PYTHONPATH="$ROOT_DIR:$PYTHONPATH"

    log "Starting admin panel at http://localhost:8084"

    exec python app.py
}

########################################
# SYSTEMD MANAGEMENT
########################################

manage_service() {
    local action="$1"
    local target="$2"

    local svc_backend="anpr-multi-camera.service"
    local svc_admin="anpr-admin-panel.service"

    local services=()

    case "$target" in
        all) services=("$svc_backend" "$svc_admin") ;;
        backend) services=("$svc_backend") ;;
        admin) services=("$svc_admin") ;;
        *) die "Invalid target: $target" ;;
    esac

    for svc in "${services[@]}"; do
        log "$action → $svc"

        case "$action" in
            start|stop|restart|status)
                sudo systemctl "$action" "$svc"
                ;;
            logs)
                sudo journalctl -u "$svc" -f
                ;;
            *)
                die "Invalid action: $action"
                ;;
        esac
    done
}

########################################
# ENTRYPOINT
########################################

[[ $# -eq 0 ]] && { show_help; exit 0; }

case "$1" in
    backend) run_backend ;;
    admin) run_admin ;;
    start|stop|restart|status|logs)
        [[ -z "${2:-}" ]] && die "Missing target"
        manage_service "$1" "$2"
        ;;
    help|-h|--help) show_help ;;
    *) die "Unknown command: $1" ;;
esac
