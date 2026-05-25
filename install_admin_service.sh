#!/bin/bash

# ANPR Admin Panel Service Installation Script - Dynamic Version
# This script generates and installs the admin panel service with actual paths for this device

set -e

echo "🚀 Installing ANPR Admin Panel Service..."

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "❌ Please run as root (use sudo)"
    exit 1
fi

# Get the actual user who called sudo
ACTUAL_USER="${SUDO_USER:-root}"
ACTUAL_GROUP=$(id -gn "$ACTUAL_USER")

# Get the script directory
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

# Get home directory of actual user
ACTUAL_HOME=$(eval echo ~$ACTUAL_USER)

echo "📁 Working directory: $SCRIPT_DIR"
echo "👤 Service will run as: $ACTUAL_USER (group: $ACTUAL_GROUP)"
echo "🏠 Home directory: $ACTUAL_HOME"

# Generate dynamic service file with actual paths
echo "📝 Generating dynamic service file..."

# Create temporary service file
TEMP_SERVICE_FILE="/tmp/anpr-admin-panel.service.$$"

cat > "$TEMP_SERVICE_FILE" << 'SERVICEFILE'
[Unit]
Description=ANPR Admin Panel Web Interface
Documentation=https://github.com/ultralytics/ultralytics
After=network.target
Wants=network.target
StartLimitInterval=0

[Service]
Type=simple
User=__USER__
Group=__GROUP__
WorkingDirectory=__SCRIPT_DIR__/admin_panel
ExecStart=/bin/bash __SCRIPT_DIR__/admin_panel/start_admin.sh
ExecReload=/bin/kill -HUP $MAINPID
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=anpr-admin-panel

# Environment variables
Environment="PATH=__SCRIPT_DIR__/anpr_env/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="PYTHONPATH=__SCRIPT_DIR__"
Environment=FLASK_ENV=production
Environment=FLASK_DEBUG=0
Environment=DISPLAY=:1
Environment="XAUTHORITY=__HOME__/.Xauthority"

# Security settings (relaxed for home directory access)
NoNewPrivileges=false
PrivateTmp=false
ProtectSystem=false
ProtectHome=false

[Install]
WantedBy=multi-user.target
SERVICEFILE

# Replace placeholders with actual values
sed -i "s|__USER__|$ACTUAL_USER|g" "$TEMP_SERVICE_FILE"
sed -i "s|__GROUP__|$ACTUAL_GROUP|g" "$TEMP_SERVICE_FILE"
sed -i "s|__SCRIPT_DIR__|$SCRIPT_DIR|g" "$TEMP_SERVICE_FILE"
sed -i "s|__HOME__|$ACTUAL_HOME|g" "$TEMP_SERVICE_FILE"

# Copy to systemd directory
echo "📋 Installing service file to /etc/systemd/system/..."
cp "$TEMP_SERVICE_FILE" /etc/systemd/system/anpr-admin-panel.service
chown root:root /etc/systemd/system/anpr-admin-panel.service
chmod 644 /etc/systemd/system/anpr-admin-panel.service

# Set proper ownership of admin panel directory
echo "🔐 Setting ownership of admin_panel directory..."
chown -R "$ACTUAL_USER:$ACTUAL_GROUP" "$SCRIPT_DIR/admin_panel"
chmod +x "$SCRIPT_DIR/admin_panel/start_admin.sh"

# Cleanup
rm -f "$TEMP_SERVICE_FILE"

# Reload systemd
echo "🔄 Reloading systemd..."
systemctl daemon-reload

# Enable the service
echo "🔧 Enabling service..."
systemctl enable anpr-admin-panel.service

echo ""
echo "✅ ANPR Admin Panel Service installed successfully!"
echo ""
echo "📋 Service Management Commands:"
echo "  Start service:    sudo systemctl start anpr-admin-panel"
echo "  Stop service:     sudo systemctl stop anpr-admin-panel"
echo "  Restart service:  sudo systemctl restart anpr-admin-panel"
echo "  Check status:     sudo systemctl status anpr-admin-panel"
echo "  View logs:        journalctl -u anpr-admin-panel -f"
echo "  Disable service:  sudo systemctl disable anpr-admin-panel"
echo ""
echo "🎉 Admin panel will start automatically on system boot!"
echo ""
echo "📋 Service Management Commands:"
echo "   Start:   sudo systemctl start $SERVICE_NAME"
echo "   Stop:    sudo systemctl stop $SERVICE_NAME"
echo "   Status:  sudo systemctl status $SERVICE_NAME"
echo "   Logs:    sudo journalctl -u $SERVICE_NAME -f"
echo "   Restart: sudo systemctl restart $SERVICE_NAME"
echo ""
echo "🌐 The admin panel will be available at: http://localhost:8084"
echo "📝 Default credentials: admin/admin123 or anpr/anpr2024"
echo "👤 Running as user: $ACTUAL_USER"
echo ""
echo "🚀 To start the service now, run:"
echo "   sudo systemctl start $SERVICE_NAME"
