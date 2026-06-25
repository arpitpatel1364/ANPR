#!/usr/bin/env bash
source "$(dirname "$0")/utils.sh"

info "Rolling back..."

rm -rf "$ROOT_DIR/anpr_env" || true

systemctl stop anpr-multi-camera.service 2>/dev/null || true
systemctl stop anpr-admin-panel.service 2>/dev/null || true

rm -f /etc/systemd/system/anpr-*.service || true

systemctl daemon-reload
systemctl reset-failed

warn "Rollback complete"