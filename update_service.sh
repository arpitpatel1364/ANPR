#!/bin/bash

echo "🔄 Updating ANPR Service for headless mode..."

# Stop the current service
echo "1. Stopping current service..."
sudo systemctl stop anpr-multi-camera 2>/dev/null || true

# Copy the updated service file
echo "2. Updating service file..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
sudo cp "$SCRIPT_DIR/anpr-multi-camera.service" /etc/systemd/system/

# Reload systemd
echo "3. Reloading systemd..."
sudo systemctl daemon-reload

# Start the service
echo "4. Starting service..."
sudo systemctl start anpr-multi-camera

# Wait a moment for startup
sleep 3

# Check status
echo "5. Checking status..."
sudo systemctl status anpr-multi-camera --no-pager

echo "✅ Service updated for headless mode!"
echo ""
echo "The service is now configured to run without a display (headless mode)."
echo "To view logs: journalctl -u anpr-multi-camera -f"
echo "To check status: sudo systemctl status anpr-multi-camera"
