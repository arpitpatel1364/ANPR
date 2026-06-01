#!/bin/bash

# ANPR Service Installation Script - Dynamic Version
# This script generates and installs systemd service files with actual paths for this device

set -e

echo "🚀 Installing ANPR Multi-Camera Service..."

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo "❌ Please run this script as a regular user, not as root"
    echo "   The service will run under your user account"
    exit 1
fi

# Get current user, group and home directory
CURRENT_USER=$(whoami)
CURRENT_GROUP=$(id -gn)
USER_HOME=$(eval echo ~$CURRENT_USER)
SERVICE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "👤 User: $CURRENT_USER"
echo "👥 Group: $CURRENT_GROUP"
echo "📁 Service Directory: $SERVICE_DIR"

# Check if service directory exists
if [ ! -d "$SERVICE_DIR" ]; then
    echo "❌ Service directory not found: $SERVICE_DIR"
    exit 1
fi

# Check if required files exist
REQUIRED_FILES=("app_multi_camera_lprnet.py" "plate_logger.py" "db_connection.py" "ANPR_ver15.pt" "start_anpr_service.sh")
for file in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$SERVICE_DIR/$file" ]; then
        echo "❌ Required file not found: $file"
        exit 1
    fi
done

echo "✅ All required files found"

# Make startup script executable
chmod +x "$SERVICE_DIR/start_anpr_service.sh"
echo "✅ Startup script made executable"

# Generate dynamic service file with actual paths
echo "📝 Generating dynamic service file..."

# Create temporary service file with actual paths
TEMP_SERVICE_FILE="/tmp/anpr-multi-camera.service.$$"

cat > "$TEMP_SERVICE_FILE" << 'SERVICEFILE'
[Unit]
Description=ANPR Multi-Camera System
Documentation=https://github.com/ultralytics/ultralytics
After=network.target
Wants=network.target
StartLimitInterval=0

[Service]
Type=simple
User=__USER__
Group=__GROUP__

WorkingDirectory=__SERVICE_DIR__
ExecStart=/bin/bash __SERVICE_DIR__/start_anpr_service.sh
ExecReload=/bin/kill -HUP $MAINPID
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=anpr-multi-camera

# Environment variables
Environment="PATH=__SERVICE_DIR__/anpr_env/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="PYTHONPATH=__SERVICE_DIR__"
Environment=CUDA_VISIBLE_DEVICES=0
Environment=OPENCV_VIDEOIO_PRIORITY_MSMF=0

# Allow GUI windows on the host X session
Environment="DISPLAY=:1"
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
sed -i "s|__USER__|$CURRENT_USER|g" "$TEMP_SERVICE_FILE"
sed -i "s|__GROUP__|$CURRENT_GROUP|g" "$TEMP_SERVICE_FILE"
sed -i "s|__SERVICE_DIR__|$SERVICE_DIR|g" "$TEMP_SERVICE_FILE"
sed -i "s|__HOME__|$USER_HOME|g" "$TEMP_SERVICE_FILE"

# Copy to systemd directory
echo "📋 Installing systemd service file..."
sudo cp "$TEMP_SERVICE_FILE" /etc/systemd/system/anpr-multi-camera.service
sudo chown root:root /etc/systemd/system/anpr-multi-camera.service
sudo chmod 644 /etc/systemd/system/anpr-multi-camera.service

# Cleanup
rm -f "$TEMP_SERVICE_FILE"

echo "✅ Service file installed and configured for this device"

# Reload systemd daemon
echo "🔄 Reloading systemd daemon..."
sudo systemctl daemon-reload

# Enable the service
echo "🔧 Enabling service to start on boot..."
sudo systemctl enable anpr-multi-camera.service

echo "✅ Service installed and enabled successfully!"
echo ""
echo "📋 Service Management Commands:"
echo "  Start service:    sudo systemctl start anpr-multi-camera"
echo "  Stop service:     sudo systemctl stop anpr-multi-camera"
echo "  Restart service:  sudo systemctl restart anpr-multi-camera"
echo "  Check status:     sudo systemctl status anpr-multi-camera"
echo "  View logs:        journalctl -u anpr-multi-camera -f"
echo "  Disable service:  sudo systemctl disable anpr-multi-camera"
echo ""
echo "🎯 The service will now start automatically on system boot!"
echo "📝 Logs will be written to: $SERVICE_DIR/anpr_service.log"
echo "📊 Service logs also available via: journalctl -u anpr-multi-camera"
