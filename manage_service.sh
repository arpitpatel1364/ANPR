#!/bin/bash

# ANPR Service Management Script
# Easy commands to manage the ANPR service

SERVICE_NAME="anpr-multi-camera"

show_help() {
    echo "ANPR Service Management"
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  start     - Start the ANPR service"
    echo "  stop      - Stop the ANPR service"
    echo "  restart   - Restart the ANPR service"
    echo "  status    - Show service status"
    echo "  logs      - Show service logs (live)"
    echo "  logs-tail - Show last 50 log lines"
    echo "  enable    - Enable service to start on boot"
    echo "  disable   - Disable service from starting on boot"
    echo "  install   - Install the service (run once)"
    echo "  uninstall - Remove the service"
    echo "  help      - Show this help message"
}

case "$1" in
    start)
        echo "🚀 Starting ANPR service..."
        systemctl start $SERVICE_NAME
        echo "✅ Service started"
        ;;
    stop)
        echo "🛑 Stopping ANPR service..."
        systemctl stop $SERVICE_NAME
        echo "✅ Service stopped"
        ;;
    restart)
        echo "🔄 Restarting ANPR service..."
        systemctl restart $SERVICE_NAME
        echo "✅ Service restarted"
        ;;
    status)
        echo "📊 ANPR Service Status:"
        systemctl status $SERVICE_NAME
        ;;
    logs)
        echo "📝 Showing live ANPR service logs (Ctrl+C to exit):"
        journalctl -u $SERVICE_NAME -f
        ;;
    logs-tail)
        echo "📝 Last 50 ANPR service log lines:"
        journalctl -u $SERVICE_NAME -n 50
        ;;
    enable)
        echo "🔧 Enabling ANPR service to start on boot..."
        systemctl enable $SERVICE_NAME
        echo "✅ Service enabled for auto-start"
        ;;
    disable)
        echo "🚫 Disabling ANPR service from starting on boot..."
        systemctl disable $SERVICE_NAME
        echo "✅ Service disabled from auto-start"
        ;;
    install)
        echo "📦 Installing ANPR service..."
        ./install_service.sh
        ;;
    uninstall)
        echo "🗑️  Uninstalling ANPR service..."
        sudo systemctl stop $SERVICE_NAME 2>/dev/null || true
        sudo systemctl disable $SERVICE_NAME 2>/dev/null || true
        sudo rm -f /etc/systemd/system/$SERVICE_NAME.service
        sudo systemctl daemon-reload
        echo "✅ Service uninstalled"
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        echo "❌ Unknown command: $1"
        echo ""
        show_help
        exit 1
        ;;
esac
