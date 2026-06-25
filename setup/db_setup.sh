#!/usr/bin/env bash
source "$(dirname "$0")/utils.sh"

info "Setting up MySQL..."

systemctl start mysql || true
systemctl enable mysql || true

sleep 3

if ! systemctl is-active --quiet mysql; then
    warn "MySQL failed, reinstalling..."
    retry 3 apt-get install --reinstall -y mysql-server
    systemctl restart mysql
fi

info "Waiting for DB..."
for i in {1..30}; do
    nc -z 127.0.0.1 3306 && break
    sleep 2
done

info "Configuring MySQL root user..."
sudo mysql -e "ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY '';" || true
sudo mysql -e "CREATE USER IF NOT EXISTS 'root'@'127.0.0.1' IDENTIFIED WITH mysql_native_password BY '';" || true
sudo mysql -e "GRANT ALL PRIVILEGES ON *.* TO 'root'@'127.0.0.1' WITH GRANT OPTION;" || true
sudo mysql -e "CREATE DATABASE IF NOT EXISTS anpr_system CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" || true
sudo mysql -e "FLUSH PRIVILEGES;" || true

source "$ROOT_DIR/anpr_env/bin/activate"

if [[ -f "$ROOT_DIR/scripts/init_database.py" ]]; then
    python "$ROOT_DIR/scripts/init_database.py"
fi

if [[ -f "$ROOT_DIR/scripts/create_admin_user.py" ]]; then
    info "Injecting default users..."
    python "$ROOT_DIR/scripts/create_admin_user.py"
fi