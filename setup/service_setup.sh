#!/usr/bin/env bash
source "$(dirname "$0")/utils.sh"

USER_NAME="${SUDO_USER:-$(whoami)}"
GROUP_NAME=$(id -gn "$USER_NAME")

info "Creating services..."

cat > /etc/systemd/system/anpr-multi-camera.service <<EOF
[Unit]
Description=ANPR Backend
After=network.target mysql.service
Wants=mysql.service

[Service]
User=$USER_NAME
Group=$GROUP_NAME
WorkingDirectory=$ROOT_DIR
ExecStart=/bin/bash $ROOT_DIR/run.sh backend
Restart=always

Environment="PATH=$ROOT_DIR/anpr_env/bin:/usr/bin"

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/anpr-admin-panel.service <<EOF
[Unit]
Description=ANPR Admin
After=network.target mysql.service
Wants=mysql.service

[Service]
User=$USER_NAME
Group=$GROUP_NAME
WorkingDirectory=$ROOT_DIR/admin_panel
ExecStart=/bin/bash $ROOT_DIR/run.sh admin
Restart=always

Environment="PATH=$ROOT_DIR/anpr_env/bin:/usr/bin"

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable anpr-multi-camera.service
systemctl enable anpr-admin-panel.service

systemctl restart anpr-multi-camera.service
systemctl restart anpr-admin-panel.service