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

  start  <all|backend|admin>
  stop   <all|backend|admin>
  restart <all|backend|admin>
  status  <all|backend|admin>
  logs    <all|backend|admin>

Note: To change GPU/CPU for OCR, re-run setup.sh
EOF
}

########################################
# PADDLE DEVICE CONFIG
########################################

PADDLE_DEVICE_FILE="$ROOT_DIR/newmodel/.paddle_device"

# Read previously saved device choice (cpu or gpu)
read_paddle_device() {
    if [[ -f "$PADDLE_DEVICE_FILE" ]]; then
        cat "$PADDLE_DEVICE_FILE"
    else
        echo "cpu"
    fi
}

########################################
# DATABASE CHECK & AUTO-DETECTION
########################################

is_db_service_active() {
    systemctl is-active --quiet mysql || systemctl is-active --quiet mariadb || systemctl is-active --quiet xampp
}

wait_for_db() {
    local timeout_secs=${1:-60}
    log "Waiting for database service to accept connections..."

    for ((i=0; i<timeout_secs; i+=2)); do
        if nc -z 127.0.0.1 3306 || nc -z 127.0.0.1 3307; then
            log "Database is ready"
            return 0
        fi
        sleep 2
    done

    die "Database not ready/listening after ${timeout_secs}s"
}

ensure_mysql_running() {
    export DB_HOST="${DB_HOST:-127.0.0.1}"

    # Auto-detect already running database port (3306 or 3307)
    if nc -z 127.0.0.1 3306 >/dev/null 2>&1; then
        export DB_PORT=3306
        log "Database detected on active port: $DB_PORT"
        return 0
    elif nc -z 127.0.0.1 3307 >/dev/null 2>&1; then
        export DB_PORT=3307
        log "Database detected on active port: $DB_PORT"
        return 0
    fi

    log "No active database port detected. Checking database services..."

    # If services are not active, try starting them (in case run.sh is executed manually outside systemd)
    if ! is_db_service_active; then
        log "Starting database service..."
        if systemctl list-unit-files | grep -q "^mariadb.service"; then
            sudo systemctl start mariadb || true
        elif systemctl list-unit-files | grep -q "^mysql.service"; then
            sudo systemctl start mysql || true
        elif systemctl list-unit-files | grep -q "^xampp.service"; then
            sudo systemctl start xampp || true
        fi
    fi

    # Wait for database to start accepting connections on either port
    wait_for_db 60

    # Re-detect active port
    if nc -z 127.0.0.1 3306 >/dev/null 2>&1; then
        export DB_PORT=3306
    elif nc -z 127.0.0.1 3307 >/dev/null 2>&1; then
        export DB_PORT=3307
    else
        die "Could not find active database on port 3306 or 3307 after service startup."
    fi

    log "Database configured to port: $DB_PORT"
}

########################################
# BACKEND
########################################

run_backend() {
    ensure_mysql_running

    cd "$ROOT_DIR"

    [[ -f "$VENV_ACTIVATE" ]] || die "Virtualenv missing. Run setup.sh first"
    source "$VENV_ACTIVATE"

    [[ -f "app_multi_camera.py" ]] || die "Backend file missing"

    export PYTHONPATH="$ROOT_DIR:$PYTHONPATH"

    # Add virtual environment CUDA / cuDNN paths to LD_LIBRARY_PATH so PaddlePaddle can find it
    export LD_LIBRARY_PATH="$ROOT_DIR/anpr_env/lib/python3.12/site-packages/nvidia/cudnn/lib:$ROOT_DIR/anpr_env/lib/python3.12/site-packages/nvidia/cublas/lib:$ROOT_DIR/anpr_env/lib/python3.12/site-packages/nvidia/cuda_runtime/lib:${LD_LIBRARY_PATH:-}"

    # Export the saved PaddlePaddle device choice so AwirosOCR reads it
    export ANPR_PADDLE_DEVICE="$(read_paddle_device)"
    log "Paddle device: ${ANPR_PADDLE_DEVICE^^}  (to change: re-run setup.sh)"

    # Force execution on CPU by hiding all CUDA devices
    # export CUDA_VISIBLE_DEVICES="-1"

    log "Starting backend service..."

    exec python -u app_multi_camera.py 2>&1 | tee -a "$LOG_FILE"
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
