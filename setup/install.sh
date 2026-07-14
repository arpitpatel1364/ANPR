#!/usr/bin/env bash
source "$(dirname "$0")/utils.sh"

info "Installing system dependencies..."

export DEBIAN_FRONTEND=noninteractive

# 1. Clean up/resolve any pre-existing broken package states
info "Checking for broken package manager states..."
if ! dpkg --configure -a --force-confold; then
    warn "dpkg configuration failed. Attempting to auto-fix dependencies..."
    apt-get install -f -y || true
fi

# If mysql-server is half-configured and still broken, force-purge it using dpkg to avoid apt deadlock
if dpkg -l | grep -q "mysql-server" && ! dpkg --configure -a; then
    warn "mysql-server package is half-configured and failing. Force-purging server packages..."
    systemctl stop mysql || true
    dpkg --purge --force-all mysql-server mysql-server-8.0 mysql-server-core-8.0 || true
    apt-get autoremove -y || true
    apt-get clean
fi

retry 3 apt-get update -y

# 2. Check if a database is already running on port 3306 or 3307
DB_RUNNING=false
if nc -z 127.0.0.1 3306 >/dev/null 2>&1 || nc -z 127.0.0.1 3307 >/dev/null 2>&1; then
    info "MySQL/MariaDB is already running on port 3306/3307. Skipping database package installation."
    DB_RUNNING=true
fi

# 3. Install core dependencies (excluding database server if already running)
if [[ "$DB_RUNNING" == "true" ]]; then
    retry 3 apt-get install -y \
        python3 python3-venv python3-pip \
        ffmpeg libsm6 libxext6 libgl1 \
        git curl wget netcat-openbsd
else
    # Try to install mariadb-server first (lightweight/reliable), fallback to mysql-server
    info "No database detected. Installing MariaDB Server..."
    if ! retry 3 apt-get install -y mariadb-server \
        python3 python3-venv python3-pip \
        ffmpeg libsm6 libxext6 libgl1 \
        git curl wget netcat-openbsd; then
        
        warn "MariaDB installation failed. Trying mysql-server..."
        retry 3 apt-get install -y mysql-server \
            python3 python3-venv python3-pip \
            ffmpeg libsm6 libxext6 libgl1 \
            git curl wget netcat-openbsd
    fi
fi