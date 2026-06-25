#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="$ROOT_DIR/setup.log"

info(){ echo -e "\033[1;32m[INFO]\033[0m $*" | tee -a "$LOG_FILE"; }
warn(){ echo -e "\033[1;33m[WARN]\033[0m $*" | tee -a "$LOG_FILE"; }
err(){ echo -e "\033[1;31m[ERROR]\033[0m $*" | tee -a "$LOG_FILE"; }

die(){ err "$*"; exit 1; }

retry(){
    local attempts=$1; shift
    local i=0
    until "$@"; do
        ((i++))
        [[ $i -ge $attempts ]] && die "Failed: $*"
        warn "Retry $i/$attempts..."
        sleep $((i*2))
    done
}