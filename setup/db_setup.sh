#!/usr/bin/env bash
source "$(dirname "$0")/utils.sh"

info "Setting up Database..."

# Try to start/enable mariadb or mysql service if installed via apt
if systemctl list-unit-files | grep -q "^mariadb.service"; then
    systemctl start mariadb || true
    systemctl enable mariadb || true
elif systemctl list-unit-files | grep -q "^mysql.service"; then
    systemctl start mysql || true
    systemctl enable mysql || true
fi

# Detect running database port (3306 or 3307) dynamically
DB_PORT=""
info "Waiting for database to accept connections..."
for i in {1..30}; do
    if nc -z 127.0.0.1 3306 >/dev/null 2>&1; then
        DB_PORT=3306
        break
    elif nc -z 127.0.0.1 3307 >/dev/null 2>&1; then
        DB_PORT=3307
        break
    fi
    sleep 2
done

if [[ -z "$DB_PORT" ]]; then
    die "❌ Database not detected on port 3306 or 3307 after 60 seconds."
fi

info "✅ Database detected on port $DB_PORT"
export DB_PORT

# Helper to run SQL statement robustly trying different authentication/connection methods
run_sql() {
    local sql="$1"
    # Try using UNIX socket first (standard for root access on local apt installs)
    if sudo mysql -e "$sql" >/dev/null 2>&1; then
        return 0
    fi
    # Try via TCP without password (standard for XAMPP root, or standard TCP root with empty pass)
    if mysql -u root -h 127.0.0.1 -P "$DB_PORT" -e "$sql" >/dev/null 2>&1; then
        return 0
    fi
    # Try with sudo via TCP
    if sudo mysql -u root -h 127.0.0.1 -P "$DB_PORT" -e "$sql" >/dev/null 2>&1; then
        return 0
    fi
    warn "Failed to execute SQL: $sql (will proceed and check if DB is initialized anyway)"
    return 1
}

info "Configuring MySQL/MariaDB database and users..."
run_sql "ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY '';" || true
run_sql "CREATE USER IF NOT EXISTS 'root'@'127.0.0.1' IDENTIFIED WITH mysql_native_password BY '';" || true
run_sql "GRANT ALL PRIVILEGES ON *.* TO 'root'@'127.0.0.1' WITH GRANT OPTION;" || true
run_sql "CREATE DATABASE IF NOT EXISTS anpr_system CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" || true
run_sql "FLUSH PRIVILEGES;" || true

# Activate Python environment and run migrations/seeders
source "$ROOT_DIR/anpr_env/bin/activate"

if [[ -f "$ROOT_DIR/scripts/init_database.py" ]]; then
    python "$ROOT_DIR/scripts/init_database.py"
fi

if [[ -f "$ROOT_DIR/scripts/create_admin_user.py" ]]; then
    info "Injecting default users..."
    python "$ROOT_DIR/scripts/create_admin_user.py"
fi