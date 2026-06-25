#!/usr/bin/env bash
source "$(dirname "$0")/utils.sh"

USER_NAME="${SUDO_USER:-$(whoami)}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

info "Setting up sudoers for ANPR services..."

SUDOERS_FILE="/etc/sudoers.d/anpr-services"

cat > "$SUDOERS_FILE" << EOF
# Allow ${USER_NAME} to manage ANPR services without password
${USER_NAME} ALL=(ALL) NOPASSWD: /bin/systemctl start anpr-multi-camera.service
${USER_NAME} ALL=(ALL) NOPASSWD: /bin/systemctl stop anpr-multi-camera.service
${USER_NAME} ALL=(ALL) NOPASSWD: /bin/systemctl restart anpr-multi-camera.service
${USER_NAME} ALL=(ALL) NOPASSWD: /bin/systemctl status anpr-multi-camera.service
${USER_NAME} ALL=(ALL) NOPASSWD: /bin/systemctl restart anpr-multi-camera
${USER_NAME} ALL=(ALL) NOPASSWD: /bin/journalctl -u anpr-multi-camera*

${USER_NAME} ALL=(ALL) NOPASSWD: /bin/systemctl start anpr-admin-panel.service
${USER_NAME} ALL=(ALL) NOPASSWD: /bin/systemctl stop anpr-admin-panel.service
${USER_NAME} ALL=(ALL) NOPASSWD: /bin/systemctl restart anpr-admin-panel.service
${USER_NAME} ALL=(ALL) NOPASSWD: /bin/systemctl status anpr-admin-panel.service
${USER_NAME} ALL=(ALL) NOPASSWD: /bin/systemctl enable anpr-admin-panel.service
${USER_NAME} ALL=(ALL) NOPASSWD: /bin/systemctl disable anpr-admin-panel.service
${USER_NAME} ALL=(ALL) NOPASSWD: /bin/journalctl -u anpr-admin-panel*

${USER_NAME} ALL=(ALL) NOPASSWD: ${ROOT_DIR}/run.sh
EOF

chmod 0440 "$SUDOERS_FILE"

info "Validating sudoers file..."
if visudo -c -f "$SUDOERS_FILE"; then
    info "Sudoers file validated successfully"
else
    err "Sudoers validation failed! Removing file to prevent system issues."
    rm "$SUDOERS_FILE"
    exit 1
fi
