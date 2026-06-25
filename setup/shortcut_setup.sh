#!/usr/bin/env bash
source "$(dirname "$0")/utils.sh"

USER_NAME="${SUDO_USER:-$(whoami)}"
USER_HOME=$(eval echo "~$USER_NAME")
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# === CONFIG ===
APP_NAME="ANPR Admin Panel"
URL="http://localhost:8084"
ICON_PATH="$ROOT_DIR/admin_panel/static/images/favicon.png"

# Use the user's Desktop directory explicitly
DESKTOP_DIR="$USER_HOME/Desktop"
DESKTOP_FILE="$DESKTOP_DIR/anpr-admin.desktop"

# Also create it in applications menu
APPS_DIR="$USER_HOME/.local/share/applications"
APP_MENU_FILE="$APPS_DIR/anpr-admin.desktop"

info "Creating desktop shortcuts..."

# Create Desktop entry content
cat > "/tmp/anpr-admin.desktop" <<EOF
[Desktop Entry]
Name=$APP_NAME
Comment=Open $APP_NAME
Exec=xdg-open $URL
Icon=$ICON_PATH
Terminal=false
Type=Application
Categories=Network;WebBrowser;
EOF

# Copy to Desktop if it exists
if [ -d "$DESKTOP_DIR" ]; then
    cp "/tmp/anpr-admin.desktop" "$DESKTOP_FILE"
    chmod +x "$DESKTOP_FILE"
    chown "$USER_NAME:$USER_NAME" "$DESKTOP_FILE"
    
    # Trust the desktop file on modern GNOME/Ubuntu (gio set)
    if command -v gio >/dev/null 2>&1; then
        sudo -u "$USER_NAME" gio set "$DESKTOP_FILE" metadata::trusted true 2>/dev/null || true
    fi
    info "Desktop entry created at $DESKTOP_FILE"
fi

# Copy to Application Menu
mkdir -p "$APPS_DIR"
chown "$USER_NAME:$USER_NAME" "$APPS_DIR"
cp "/tmp/anpr-admin.desktop" "$APP_MENU_FILE"
chmod +x "$APP_MENU_FILE"
chown "$USER_NAME:$USER_NAME" "$APP_MENU_FILE"

rm "/tmp/anpr-admin.desktop"

info "✅ Application menu and desktop entries created successfully"
