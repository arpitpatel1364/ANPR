#!/bin/bash

# ANPR Admin Panel Service Management Script
# This script provides easy management of the admin panel service

SERVICE_NAME="anpr-admin-panel"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

# Function to check if service exists
check_service() {
    if ! sudo systemctl list-unit-files | grep -q "$SERVICE_NAME.service"; then
        print_error "Service $SERVICE_NAME not found. Please install it first:"
        echo "   sudo ./install_admin_service.sh"
        exit 1
    fi
}

# Function to show service status
show_status() {
    print_info "Service Status:"
    sudo systemctl status "$SERVICE_NAME" --no-pager
    echo ""
    print_info "Recent Logs:"
    sudo journalctl -u "$SERVICE_NAME" --no-pager -n 10
}

# Function to start service
start_service() {
    check_service
    print_info "Starting $SERVICE_NAME..."
    if sudo systemctl start "$SERVICE_NAME"; then
        print_status "Service started successfully"
        sleep 2
        show_status
    else
        print_error "Failed to start service"
        exit 1
    fi
}

# Function to stop service
stop_service() {
    check_service
    print_info "Stopping $SERVICE_NAME..."
    if sudo systemctl stop "$SERVICE_NAME"; then
        print_status "Service stopped successfully"
    else
        print_error "Failed to stop service"
        exit 1
    fi
}

# Function to restart service
restart_service() {
    check_service
    print_info "Restarting $SERVICE_NAME..."
    if sudo systemctl restart "$SERVICE_NAME"; then
        print_status "Service restarted successfully"
        sleep 2
        show_status
    else
        print_error "Failed to restart service"
        exit 1
    fi
}

# Function to show logs
show_logs() {
    check_service
    print_info "Showing live logs for $SERVICE_NAME (Press Ctrl+C to exit):"
    sudo journalctl -u "$SERVICE_NAME" -f
}

# Function to enable/disable service
enable_service() {
    check_service
    print_info "Enabling $SERVICE_NAME to start on boot..."
    if sudo systemctl enable "$SERVICE_NAME"; then
        print_status "Service enabled successfully"
    else
        print_error "Failed to enable service"
        exit 1
    fi
}

disable_service() {
    check_service
    print_info "Disabling $SERVICE_NAME from starting on boot..."
    if sudo systemctl disable "$SERVICE_NAME"; then
        print_status "Service disabled successfully"
    else
        print_error "Failed to disable service"
        exit 1
    fi
}

# Function to uninstall service
uninstall_service() {
    check_service
    print_warning "This will stop and remove the $SERVICE_NAME service"
    read -p "Are you sure? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_info "Stopping service..."
        sudo systemctl stop "$SERVICE_NAME" 2>/dev/null || true
        
        print_info "Disabling service..."
        sudo systemctl disable "$SERVICE_NAME" 2>/dev/null || true
        
        print_info "Removing service file..."
        sudo rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
        
        print_info "Reloading systemd..."
        sudo systemctl daemon-reload
        
        print_status "Service uninstalled successfully"
    else
        print_info "Uninstall cancelled"
    fi
}

# Function to show help
show_help() {
    echo "ANPR Admin Panel Service Management"
    echo ""
    echo "Usage: $0 [COMMAND]"
    echo ""
    echo "Commands:"
    echo "  start     Start the admin panel service"
    echo "  stop      Stop the admin panel service"
    echo "  restart   Restart the admin panel service"
    echo "  status    Show service status and recent logs"
    echo "  logs      Show live logs (Press Ctrl+C to exit)"
    echo "  enable    Enable service to start on boot"
    echo "  disable   Disable service from starting on boot"
    echo "  uninstall Remove the service completely"
    echo "  help      Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 start"
    echo "  $0 status"
    echo "  $0 logs"
}

# Main script logic
case "${1:-help}" in
    start)
        start_service
        ;;
    stop)
        stop_service
        ;;
    restart)
        restart_service
        ;;
    status)
        show_status
        ;;
    logs)
        show_logs
        ;;
    enable)
        enable_service
        ;;
    disable)
        disable_service
        ;;
    uninstall)
        uninstall_service
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        print_error "Unknown command: $1"
        echo ""
        show_help
        exit 1
        ;;
esac
