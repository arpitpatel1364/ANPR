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

source "$ROOT_DIR/anpr_env/bin/activate"

if [[ -f "$ROOT_DIR/scripts/init_database.py" ]]; then
    python "$ROOT_DIR/scripts/init_database.py"
fi