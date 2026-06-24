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

is_mysql_ready() {
    # First check if mysqladmin responds to ping
    if command -v mysqladmin &>/dev/null; then
        mysqladmin ping -h"${DB_HOST:-127.0.0.1}" -P"${DB_PORT:-3306}" --silent
    elif command -v nc &>/dev/null; then
        nc -z "${DB_HOST:-127.0.0.1}" "${DB_PORT:-3306}" &>/dev/null
    else
        timeout 1 bash -c "cat < /dev/null > /dev/tcp/${DB_HOST:-127.0.0.1}/${DB_PORT:-3306}" &>/dev/null
    fi
}

wait_for_mysql() {
    local timeout_secs=${1:-60}
    echo "Waiting up to $timeout_secs seconds for MySQL to become ready..."
    local elapsed=0
    while [[ $elapsed -lt $timeout_secs ]]; do
        if is_mysql_ready; then
            echo "MySQL is ready and accepting connections!"
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
        echo -n "."
    done
    echo ""
    echo "Error: MySQL did not become ready on ${DB_HOST:-127.0.0.1}:${DB_PORT:-3306} within $timeout_secs seconds."
    return 1
}

ensure_mysql_running() {
    # Set default values if not defined to ensure out-of-the-box operation
    export DB_HOST="${DB_HOST:-127.0.0.1}"
    export DB_PORT="${DB_PORT:-3306}"
    export DB_USER="${DB_USER:-root}"
    if [[ -z "${DB_PASSWORD+x}" ]]; then
        export DB_PASSWORD=""
    fi
    export DB_NAME="${DB_NAME:-anpr_system}"

    if is_mysql_ready; then
        echo "MySQL is running and accepting connections."
        return 0
    fi

    echo "MySQL is not responding. Attempting to start database service..."

    local SUDO=""
    if [ "$EUID" -ne 0 ]; then
        SUDO="sudo"
    fi

    local started=0
    # Try starting XAMPP/MySQL/MariaDB if installed
    if [ -x "/opt/lampp/lampp" ]; then
        echo "Starting XAMPP MySQL..."
        $SUDO /opt/lampp/lampp startmysql || echo "Warning: Failed to start XAMPP MySQL"
        started=1
    elif systemctl list-units --all --type=service | grep -q "mysql.service"; then
        echo "Starting mysql.service..."
        $SUDO systemctl start mysql || echo "Warning: Failed to start mysql.service"
        started=1
    elif systemctl list-units --all --type=service | grep -q "mariadb.service"; then
        echo "Starting mariadb.service..."
        $SUDO systemctl start mariadb || echo "Warning: Failed to start mariadb.service"
        started=1
    fi

    # Fallback to installing XAMPP if no service is found and /opt/lampp is missing
    if [ ! -d "/opt/lampp" ] && [ $started -eq 0 ]; then
        echo "No database service found. Downloading and installing XAMPP..."
        wget https://sourceforge.net/projects/xampp/files/XAMPP%20Linux/8.2.12/xampp-linux-x64-8.2.12-0-installer.run -O /tmp/xampp-installer.run
        chmod +x /tmp/xampp-installer.run
        $SUDO /tmp/xampp-installer.run --mode unattended
        rm -f /tmp/xampp-installer.run
        $SUDO /opt/lampp/lampp start
        echo "XAMPP installed and started."
    fi

    wait_for_mysql 60
}

run_backend() {
    ensure_mysql_running
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
    
    if [ ! -f "app_multi_camera_lprnet.py" ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: app_multi_camera_lprnet.py not found!" | tee -a "$LOG_FILE"
        exit 1
    fi
    
    export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"
    export CUDA_VISIBLE_DEVICES=0
    export OPENCV_VIDEOIO_PRIORITY_MSMF=0
    
    python -B -u app_multi_camera_lprnet.py 2>&1 | tee -a "$LOG_FILE"
}

run_admin() {
    ensure_mysql_running
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
