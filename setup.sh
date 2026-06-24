#!/usr/bin/env bash

# ANPR System Setup Script

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="$SCRIPT_DIR/anpr_env"
SERVICE_USER="${SUDO_USER:-$(whoami)}"
PYTHON_BIN="python3"

# Color helpers
info(){ echo -e "\033[1;32m[INFO]\033[0m $*"; }
warn(){ echo -e "\033[1;33m[WARN]\033[0m $*"; }
err(){ echo -e "\033[1;31m[ERROR]\033[0m $*"; }
die() { err "$*"; exit 1; }

function ensure_root() {
    if [[ $EUID -ne 0 ]]; then
        die "This step must be run as root (use sudo)";
    fi
}

function install_system_deps() {
    if command -v apt-get &>/dev/null; then
        info "Installing system packages..."
        apt-get update -y
        apt-get install -y python3-venv python3-pip ffmpeg libsm6 libxext6 libfontconfig1 libxrender1 libgl1-mesa-glx git curl wget default-mysql-client netcat-openbsd || warn "Some system packages failed to install"
    else
        warn "apt-get not found — skipping system package installation"
    fi
}

function check_dependencies() {
    info "Checking core dependencies..."
    
    # Check Python 3
    if ! command -v $PYTHON_BIN &> /dev/null; then
        die "Python 3 is not installed or not in PATH. Please install python3."
    fi
    info "Found Python: $($PYTHON_BIN --version)"
    
    # Check pip
    if ! $PYTHON_BIN -m pip --version &> /dev/null; then
        warn "pip is not installed. Attempting to install python3-pip..."
        if command -v apt-get &>/dev/null; then
            apt-get install -y python3-pip || die "Failed to install pip. Please install it manually."
        else
            die "Cannot automatically install pip. Please install python3-pip manually."
        fi
    fi
    info "Found pip: $($PYTHON_BIN -m pip --version | awk '{print $1" "$2}')"
    
    # Check venv
    if ! $PYTHON_BIN -m venv -h &> /dev/null; then
        warn "python3-venv is not installed. Attempting to install..."
        if command -v apt-get &>/dev/null; then
            apt-get install -y python3-venv || die "Failed to install venv. Please install python3-venv manually."
        else
            die "Cannot automatically install venv. Please install python3-venv manually."
        fi
    fi
    info "Found venv module"
    
    info "All core dependencies are satisfied!"
}

function create_python_env() {
    info "Setting up Python virtual environment"
    if [ ! -d "$VENV_DIR" ]; then
        $PYTHON_BIN -m venv "$VENV_DIR"
    fi
    source "$VENV_DIR/bin/activate"
    pip install --upgrade pip setuptools wheel
    
    if [ -f "requirements.txt" ]; then
        info "Installing backend requirements"
        pip install -r requirements.txt
    fi
    
    if [ -f "admin_panel/requirements.txt" ]; then
        info "Installing admin panel requirements"
        pip install -r admin_panel/requirements.txt
    fi
    
    # Optional: adjust permissions so the normal user owns the venv if setup was run via sudo
    if [[ $EUID -eq 0 && -n "${SUDO_USER:-}" ]]; then
        chown -R "$SUDO_USER":"$(id -gn "$SUDO_USER")" "$VENV_DIR" || true
    fi
}

function validate_db_env() {
    info "Validating database environment variables..."
    # Set default values if not defined to ensure out-of-the-box operation
    export DB_HOST="${DB_HOST:-127.0.0.1}"
    export DB_PORT="${DB_PORT:-3306}"
    export DB_USER="${DB_USER:-root}"
    if [[ -z "${DB_PASSWORD+x}" ]]; then
        export DB_PASSWORD=""
    fi
    export DB_NAME="${DB_NAME:-anpr_system}"

    # Verify that they exist (are set) and that non-password variables are not empty.
    local missing_vars=()
    for var in DB_HOST DB_PORT DB_USER DB_NAME; do
        if [[ -z "${!var:-}" ]]; then
            missing_vars+=("$var")
        fi
    done
    if [[ -z "${DB_PASSWORD+x}" ]]; then
        missing_vars+=("DB_PASSWORD")
    fi
    
    if [[ ${#missing_vars[@]} -ne 0 ]]; then
        err "The following database environment variables are missing or empty: ${missing_vars[*]}"
        err "Please define them before running setup."
        die "Database configuration validation failed."
    fi
    
    info "Database configuration validated:"
    info "  DB_HOST=$DB_HOST"
    info "  DB_PORT=$DB_PORT"
    info "  DB_USER=$DB_USER"
    info "  DB_NAME=$DB_NAME"
}

function is_mysql_ready() {
    # First check if mysqladmin responds to ping
    if command -v mysqladmin &>/dev/null; then
        mysqladmin ping -h"${DB_HOST}" -P"${DB_PORT}" --silent
    elif command -v nc &>/dev/null; then
        nc -z "${DB_HOST}" "${DB_PORT}" &>/dev/null
    else
        timeout 1 bash -c "cat < /dev/null > /dev/tcp/${DB_HOST}/${DB_PORT}" &>/dev/null
    fi
}

function run_mysql_diagnostics() {
    err "=== MySQL Diagnostics ==="
    local SUDO=""
    if [[ $EUID -ne 0 ]]; then
        SUDO="sudo"
    fi
    
    err "Checking if port ${DB_PORT} is listening:"
    if command -v ss &>/dev/null; then
        $SUDO ss -tulpn | grep "${DB_PORT}" || true
    elif command -v netstat &>/dev/null; then
        $SUDO netstat -tulpn | grep "${DB_PORT}" || true
    fi
    
    err "Checking running MySQL processes:"
    ps aux | grep -E "mysqld|lampp|mariadb" | grep -v grep || true
    
    err "Checking service statuses:"
    if [[ -x /opt/lampp/lampp ]]; then
        $SUDO /opt/lampp/lampp status || true
    fi
    if systemctl list-units --all --type=service | grep -q "mysql.service"; then
        systemctl status mysql --no-pager || true
    fi
    if systemctl list-units --all --type=service | grep -q "mariadb.service"; then
        systemctl status mariadb --no-pager || true
    fi
    err "========================="
}

function wait_for_mysql() {
    local timeout_secs=${1:-60}
    info "Waiting up to $timeout_secs seconds for MySQL to become ready..."
    
    local elapsed=0
    while [[ $elapsed -lt $timeout_secs ]]; do
        if is_mysql_ready; then
            info "MySQL is ready and accepting connections!"
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
        echo -n "."
    done
    echo ""
    
    err "MySQL did not become ready on ${DB_HOST}:${DB_PORT} within $timeout_secs seconds."
    run_mysql_diagnostics
    die "Database connection failed. Cannot proceed."
}

function check_xampp() {
    info "Checking if MySQL/XAMPP is running..."
    
    validate_db_env
    
    if is_mysql_ready; then
        info "MySQL service is running and accepting connections."
        return 0
    fi
    
    warn "MySQL is not responding. Attempting to start database service..."
    
    local SUDO=""
    if [[ $EUID -ne 0 ]]; then
        SUDO="sudo"
    fi
    
    local started=0
    if [[ -x /opt/lampp/lampp ]]; then
        info "Found XAMPP. Fixing MySQL directory permissions..."
        if [[ -d "/opt/lampp/var/mysql" ]]; then
            $SUDO chown -R mysql:mysql /opt/lampp/var/mysql 2>/dev/null || $SUDO chown -R nobody:root /opt/lampp/var/mysql 2>/dev/null || true
            $SUDO chmod -R 777 /opt/lampp/var/mysql 2>/dev/null || true
        fi
        info "Starting XAMPP MySQL..."
        $SUDO /opt/lampp/lampp startmysql || warn "Failed to start XAMPP MySQL"
        started=1
    elif systemctl list-units --all --type=service | grep -q "mysql.service"; then
        info "Found mysql.service. Starting mysql service..."
        $SUDO systemctl start mysql || warn "Failed to start mysql.service"
        started=1
    elif systemctl list-units --all --type=service | grep -q "mariadb.service"; then
        info "Found mariadb.service. Starting mariadb service..."
        $SUDO systemctl start mariadb || warn "Failed to start mariadb.service"
        started=1
    fi
    
    if [[ $started -eq 0 ]]; then
        warn "Could not identify local database service (XAMPP, MySQL, or MariaDB)."
        info "Downloading and installing XAMPP..."
        wget https://sourceforge.net/projects/xampp/files/XAMPP%20Linux/8.2.12/xampp-linux-x64-8.2.12-0-installer.run -O "$SCRIPT_DIR/xampp-installer.run"
        chmod +x "$SCRIPT_DIR/xampp-installer.run"
        $SUDO "$SCRIPT_DIR/xampp-installer.run" --mode unattended
        rm -f "$SCRIPT_DIR/xampp-installer.run"
        info "XAMPP installation completed."
        
        if [[ -x /opt/lampp/lampp ]]; then
            info "Fixing XAMPP MySQL directory permissions..."
            if [[ -d "/opt/lampp/var/mysql" ]]; then
                $SUDO chown -R mysql:mysql /opt/lampp/var/mysql 2>/dev/null || $SUDO chown -R nobody:root /opt/lampp/var/mysql 2>/dev/null || true
                $SUDO chmod -R 777 /opt/lampp/var/mysql 2>/dev/null || true
            fi
            info "Starting XAMPP MySQL..."
            $SUDO /opt/lampp/lampp startmysql || warn "Failed to start XAMPP MySQL after installation"
        else
            die "XAMPP was not installed successfully."
        fi
    fi
    
    # Wait for MySQL to become ready
    wait_for_mysql 60
}

function verify_mysql_port() {
    info "Verifying that port ${DB_PORT} is listening on ${DB_HOST}..."
    local port_open=0
    
    if command -v nc &>/dev/null; then
        if nc -z "${DB_HOST}" "${DB_PORT}" &>/dev/null; then
            port_open=1
        fi
    elif command -v ss &>/dev/null; then
        if ss -lnt | grep -q "${DB_PORT}"; then
            port_open=1
        fi
    else
        # Fallback to bash TCP connection check
        if timeout 1 bash -c "cat < /dev/null > /dev/tcp/${DB_HOST}/${DB_PORT}" &>/dev/null; then
            port_open=1
        fi
    fi
    
    if [[ $port_open -eq 0 ]]; then
        err "Port ${DB_PORT} is not open on ${DB_HOST}!"
        run_mysql_diagnostics
        die "Port validation failed. MySQL database service must be listening on port ${DB_PORT}."
    fi
    info "Port verification successful: MySQL is listening on port ${DB_PORT}."
}

function init_database() {
    validate_db_env
    check_xampp
    verify_mysql_port
    
    info "Initializing database (creating database & tables)"
    if [[ -f "scripts/init_database.py" ]]; then
        source "$VENV_DIR/bin/activate"
        python scripts/init_database.py || die "Database initialization failed"
    else
        die "scripts/init_database.py not found"
    fi
}

function create_admin_user() {
    info "Creating admin user"
    if [ -f "scripts/create_admin_user.py" ]; then
        source "$VENV_DIR/bin/activate"
        python scripts/create_admin_user.py || warn "Admin user creation failed"
    else
        warn "scripts/create_admin_user.py not found"
    fi
}

function setup_sudoers() {
    info "Configuring sudoers for service control"
    tee /etc/sudoers.d/anpr-services > /dev/null << EOF
# Allow $SERVICE_USER to manage ANPR services without password
$SERVICE_USER ALL=(ALL) NOPASSWD: $SCRIPT_DIR/run.sh
$SERVICE_USER ALL=(ALL) NOPASSWD: /bin/systemctl start anpr-multi-camera.service
$SERVICE_USER ALL=(ALL) NOPASSWD: /bin/systemctl stop anpr-multi-camera.service
$SERVICE_USER ALL=(ALL) NOPASSWD: /bin/systemctl restart anpr-multi-camera.service
$SERVICE_USER ALL=(ALL) NOPASSWD: /bin/systemctl status anpr-multi-camera.service
$SERVICE_USER ALL=(ALL) NOPASSWD: /bin/journalctl -u anpr-multi-camera*
$SERVICE_USER ALL=(ALL) NOPASSWD: /bin/systemctl start anpr-admin-panel.service
$SERVICE_USER ALL=(ALL) NOPASSWD: /bin/systemctl stop anpr-admin-panel.service
$SERVICE_USER ALL=(ALL) NOPASSWD: /bin/systemctl restart anpr-admin-panel.service
$SERVICE_USER ALL=(ALL) NOPASSWD: /bin/systemctl status anpr-admin-panel.service
$SERVICE_USER ALL=(ALL) NOPASSWD: /bin/systemctl enable anpr-admin-panel.service
$SERVICE_USER ALL=(ALL) NOPASSWD: /bin/systemctl disable anpr-admin-panel.service
$SERVICE_USER ALL=(ALL) NOPASSWD: /bin/journalctl -u anpr-admin-panel*
EOF
    chmod 440 /etc/sudoers.d/anpr-services
    visudo -c -f /etc/sudoers.d/anpr-services || warn "sudoers validation failed"
}

function install_services() {
    info "Installing systemd services"
    SERVICE_GROUP=$(id -gn "$SERVICE_USER")
    USER_HOME=$(eval echo ~$SERVICE_USER)

    # XAMPP Service
    if [ -f "$SCRIPT_DIR/xampp.service" ]; then
        cp "$SCRIPT_DIR/xampp.service" /etc/systemd/system/
        systemctl enable xampp.service
        systemctl start xampp.service || warn "xampp.service failed to start"
    fi

    # Backend Service
    tee /etc/systemd/system/anpr-multi-camera.service > /dev/null <<EOF
[Unit]
Description=ANPR Multi-Camera Service
After=network.target xampp.service mysql.service mariadb.service
Wants=xampp.service mysql.service mariadb.service

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$SCRIPT_DIR
ExecStart=/bin/bash $SCRIPT_DIR/run.sh backend
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=anpr-multi-camera

Environment="PATH=$VENV_DIR/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="PYTHONPATH=$SCRIPT_DIR"
Environment=CUDA_VISIBLE_DEVICES=0
Environment=OPENCV_VIDEOIO_PRIORITY_MSMF=0
Environment="DISPLAY=:1"
Environment="XAUTHORITY=$USER_HOME/.Xauthority"

NoNewPrivileges=false
PrivateTmp=false
ProtectSystem=false
ProtectHome=false

[Install]
WantedBy=multi-user.target
EOF

    # Admin Panel Service
    tee /etc/systemd/system/anpr-admin-panel.service > /dev/null <<EOF
[Unit]
Description=ANPR Admin Panel Web Interface
After=network.target xampp.service mysql.service mariadb.service
Wants=xampp.service mysql.service mariadb.service

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$SCRIPT_DIR/admin_panel
ExecStart=/bin/bash $SCRIPT_DIR/run.sh admin
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=anpr-admin-panel

Environment="PATH=$VENV_DIR/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="PYTHONPATH=$SCRIPT_DIR"
Environment=FLASK_ENV=production
Environment=FLASK_DEBUG=0
Environment="DISPLAY=:1"
Environment="XAUTHORITY=$USER_HOME/.Xauthority"

NoNewPrivileges=false
PrivateTmp=false
ProtectSystem=false
ProtectHome=false

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable anpr-multi-camera.service
    systemctl enable anpr-admin-panel.service
    
    info "Starting services..."
    systemctl start anpr-multi-camera.service || warn "backend service failed to start"
    systemctl start anpr-admin-panel.service || warn "admin service failed to start"
}

function show_help() {
    cat <<'EOF'
ANPR System Setup

Usage: sudo ./setup.sh [COMMAND]

Commands:
  all       Perform all setup steps (deps, check, env, db, admin user, services)
  deps      Install system dependencies (apt-get)
  check     Check core python dependencies (python3, pip, venv)
  env       Create Python virtual environment and install requirements
  db        Initialize the database schema
  admin     Create an administrator user
  services  Install, enable & start systemd services
  help      Show this help message

Example:
  sudo ./setup.sh all
EOF
}

if [[ $# -eq 0 ]]; then
    show_help
    exit 0
fi

case "$1" in
    all)
        ensure_root
        install_system_deps
        check_dependencies
        create_python_env
        init_database
        create_admin_user
        setup_sudoers
        install_services
        info "Setup complete! You can now use ./run.sh to manage your services."
        ;;
    deps)
        ensure_root
        install_system_deps
        ;;
    check)
        ensure_root
        check_dependencies
        ;;
    env)
        check_dependencies
        create_python_env
        ;;
    db)
        init_database
        ;;
    admin)
        create_admin_user
        ;;
    services)
        ensure_root
        setup_sudoers
        install_services
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
