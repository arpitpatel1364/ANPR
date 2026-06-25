#!/usr/bin/env bash
source "$(dirname "$0")/utils.sh"

info "Rolling back..."

rm -rf "$ROOT_DIR/anpr_env" || true

systemctl stop anpr-multi-camera.service || true
systemctl stop anpr-admin-panel.service || true

rm -f /etc/systemd/system/anpr-*.service || true

systemctl daemon-reload
systemctl reset-failed

warn "Rollback complete"