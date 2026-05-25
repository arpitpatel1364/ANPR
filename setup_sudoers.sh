#!/bin/bash

# Setup sudoers for ANPR services
# This script allows passwordless sudo for service management

echo "🔧 Setting up sudoers for ANPR services..."

# Create sudoers entry for anpr-multi-camera
echo "📝 Creating anpr-multi-camera sudoers..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
sudo tee /etc/sudoers.d/anpr-multi-camera > /dev/null << EOF
# Allow cactus to manage anpr-multi-camera service without password
cactus ALL=(ALL) NOPASSWD: $SCRIPT_DIR/manage_service.sh
cactus ALL=(ALL) NOPASSWD: /bin/systemctl start anpr-multi-camera.service
cactus ALL=(ALL) NOPASSWD: /bin/systemctl stop anpr-multi-camera.service
cactus ALL=(ALL) NOPASSWD: /bin/systemctl restart anpr-multi-camera.service
cactus ALL=(ALL) NOPASSWD: /bin/systemctl status anpr-multi-camera.service
cactus ALL=(ALL) NOPASSWD: /bin/journalctl -u anpr-multi-camera*
EOF

# Create sudoers entry for anpr-admin-panel
echo "📝 Creating anpr-admin-panel sudoers..."
sudo tee /etc/sudoers.d/anpr-admin-panel > /dev/null << 'EOF'
# Allow cactus to manage anpr-admin-panel service without password
cactus ALL=(ALL) NOPASSWD: /bin/systemctl start anpr-admin-panel.service
cactus ALL=(ALL) NOPASSWD: /bin/systemctl stop anpr-admin-panel.service
cactus ALL=(ALL) NOPASSWD: /bin/systemctl restart anpr-admin-panel.service
cactus ALL=(ALL) NOPASSWD: /bin/systemctl status anpr-admin-panel.service
cactus ALL=(ALL) NOPASSWD: /bin/systemctl enable anpr-admin-panel.service
cactus ALL=(ALL) NOPASSWD: /bin/systemctl disable anpr-admin-panel.service
cactus ALL=(ALL) NOPASSWD: /bin/journalctl -u anpr-admin-panel*
EOF

# Set proper permissions
echo "🔐 Setting permissions..."
sudo chmod 440 /etc/sudoers.d/anpr-multi-camera
sudo chmod 440 /etc/sudoers.d/anpr-admin-panel

# Validate both files
echo "✓ Validating sudoers files..."
sudo visudo -c -f /etc/sudoers.d/anpr-multi-camera && echo "✓ anpr-multi-camera validated"
sudo visudo -c -f /etc/sudoers.d/anpr-admin-panel && echo "✓ anpr-admin-panel validated"

echo ""
echo "✅ Sudoers setup completed successfully!"
echo "You can now run service commands without a password:"
echo "  sudo systemctl start anpr-multi-camera.service"
echo "  sudo systemctl start anpr-admin-panel.service"
