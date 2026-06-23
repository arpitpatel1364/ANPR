#!/bin/bash

# ANPR Service Runner & Manager

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_ACTIVATE="$SCRIPT_DIR/anpr_env/bin/activate"

show_help() {
    cat <<'EOF'
ANPR Service Manager

Usage: ./run.sh [COMMAND] [SERVICE]

Commands:
  backend                      Run the backend multi-camera script directly (used by systemd)
  admin                        Run the admin panel script directly (used by systemd)
  
  start <all|backend|admin>    Start the systemd service(s)
  stop <all|backend|admin>     Stop the systemd service(s)
  restart <all|backend|admin>  Restart the systemd service(s)
  status <all|backend|admin>   Show the status of systemd service(s)
  logs <all|backend|admin>     Show live logs for systemd service(s)

Examples:
  ./run.sh start all
  ./run.sh logs backend
  ./run.sh restart admin
EOF
}

run_backend() {
    cd "$SCRIPT_DIR"
    
    if [ ! -f "$VENV_ACTIVATE" ]; then
        echo "Error: Python virtual environment not found. Please run './setup.sh env' first."
        exit 1
    fi
    
    source "$VENV_ACTIVATE"
    
    LOG_FILE="$SCRIPT_DIR/anpr_service.log"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Current directory: $(pwd)" >> "$LOG_FILE"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Current user: $(whoami)" >> "$LOG_FILE"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting ANPR Multi-Camera Service..." | tee -a "$LOG_FILE"
    
    if [ ! -f "plate_logger.py" ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: plate_logger.py not found!" | tee -a "$LOG_FILE"
        exit 1
    fi
    
    export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"
    export CUDA_VISIBLE_DEVICES=0
    export OPENCV_VIDEOIO_PRIORITY_MSMF=0
    
    python app_multi_camera_lprnet.py 2>&1 | tee -a "$LOG_FILE"
}

run_admin() {
    cd "$SCRIPT_DIR/admin_panel"
    
    if [ ! -f "$VENV_ACTIVATE" ]; then
        echo "Error: Python virtual environment not found. Please run './setup.sh env' first."
        exit 1
    fi
    
    source "$VENV_ACTIVATE"
    
    mkdir -p static/images/verified_plates static/css static/js templates
    
    export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"
    
    echo "Starting admin panel on http://localhost:8084"
    python app.py
}

manage_service() {
    local action="$1"
    local target="$2"
    
    local svc_backend="anpr-multi-camera.service"
    local svc_admin="anpr-admin-panel.service"
    
    local services=()
    if [[ "$target" == "all" ]]; then
        services=("$svc_backend" "$svc_admin")
    elif [[ "$target" == "backend" ]]; then
        services=("$svc_backend")
    elif [[ "$target" == "admin" ]]; then
        services=("$svc_admin")
    else
        echo "Unknown service target: $target. Valid options are: all, backend, admin"
        exit 1
    fi
    
    for svc in "${services[@]}"; do
        echo "Running '$action' on $svc..."
        case "$action" in
            start|stop|restart|status)
                sudo systemctl $action "$svc"
                ;;
            logs)
                echo "Showing logs for $svc (Press Ctrl+C to exit)..."
                sudo journalctl -u "$svc" -f
                ;;
        esac
        echo ""
    done
}

if [[ $# -eq 0 ]]; then
    show_help
    exit 0
fi

case "$1" in
    backend)
        run_backend
        ;;
    admin)
        run_admin
        ;;
    start|stop|restart|status|logs)
        if [[ -z "${2:-}" ]]; then
            echo "Error: Missing service target. Please specify 'all', 'backend', or 'admin'."
            echo "Usage: ./run.sh $1 <all|backend|admin>"
            exit 1
        fi
        manage_service "$1" "$2"
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        echo "Unknown command: $1"
        show_help
        exit 1
        ;;
esac
