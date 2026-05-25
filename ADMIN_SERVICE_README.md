# ANPR Admin Panel Service

This document explains how to install, configure, and manage the ANPR Admin Panel as a systemd service.

## Overview

The ANPR Admin Panel service provides a web-based interface for managing license plate detections, camera settings, and system monitoring. It runs as a background service and automatically starts on system boot.

## Files

- `anpr-admin-panel.service` - Systemd service configuration
- `install_admin_service.sh` - Installation script
- `manage_admin_service.sh` - Service management script
- `admin_panel/start_admin.sh` - Admin panel startup script

## Prerequisites

1. **User Account**: The `anpr` user must exist on the system
2. **Python Environment**: Python 3.7+ with required packages
3. **Permissions**: Root access for service installation

## Installation

### 1. Create User (if not exists)
```bash
sudo useradd -m -s /bin/bash anpr
sudo usermod -aG sudo anpr
```

### 2. Install Service
```bash
sudo ./install_admin_service.sh
```

### 3. Start Service
```bash
sudo systemctl start anpr-admin-panel
```

## Service Management

Use the management script for easy service control:

```bash
# Start the service
./manage_admin_service.sh start

# Stop the service
./manage_admin_service.sh stop

# Restart the service
./manage_admin_service.sh restart

# Check status and logs
./manage_admin_service.sh status

# View live logs
./manage_admin_service.sh logs

# Enable auto-start on boot
./manage_admin_service.sh enable

# Disable auto-start on boot
./manage_admin_service.sh disable

# Uninstall service
./manage_admin_service.sh uninstall
```

## Manual Service Commands

You can also use systemctl directly:

```bash
# Start service
sudo systemctl start anpr-admin-panel

# Stop service
sudo systemctl stop anpr-admin-panel

# Restart service
sudo systemctl restart anpr-admin-panel

# Check status
sudo systemctl status anpr-admin-panel

# View logs
sudo journalctl -u anpr-admin-panel -f

# Enable on boot
sudo systemctl enable anpr-admin-panel

# Disable on boot
sudo systemctl disable anpr-admin-panel
```

## Access

Once the service is running, access the admin panel at:

- **URL**: http://localhost:8084
- **Default Credentials**: 
  - Username: `admin` / Password: `admin123`
  - Username: `anpr` / Password: `anpr2024`

## Configuration

### Service Configuration
The service configuration is in `/etc/systemd/system/anpr-admin-panel.service`:

```ini
[Unit]
Description=ANPR Admin Panel Web Interface
After=network.target
Wants=network.target

[Service]
Type=simple
User=anpr
Group=anpr
WorkingDirectory=/path/to/admin_panel
ExecStart=/bin/bash /path/to/admin_panel/start_admin.sh
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Admin Panel Configuration
The admin panel configuration is in `admin_panel/config.py`:

```python
# Server settings
HOST = '0.0.0.0'
PORT = 8084
DEBUG = False

# Database settings
CSV_FILE = 'plate_detections.csv'

# Security settings
SECRET_KEY = 'your-secret-key-here'
```

## Troubleshooting

### Service Won't Start
1. Check service status: `sudo systemctl status anpr-admin-panel`
2. View logs: `sudo journalctl -u anpr-admin-panel -f`
3. Check file permissions: `ls -la admin_panel/`
4. Verify Python environment: `sudo -u anpr python3 --version`

### Permission Issues
```bash
# Fix ownership
sudo chown -R anpr:anpr /path/to/admin_panel

# Fix permissions
sudo chmod +x /path/to/admin_panel/start_admin.sh
```

### Port Already in Use
If port 8084 is already in use:
1. Check what's using it: `sudo netstat -tlnp | grep 8084`
2. Kill the process: `sudo kill -9 <PID>`
3. Or change the port in `admin_panel/config.py`

### Database Issues
1. Check CSV file exists: `ls -la plate_detections.csv`
2. Check file permissions: `ls -la plate_detections.csv`
3. Verify data format: `head -5 plate_detections.csv`

## Logs

### Service Logs
```bash
# View all logs
sudo journalctl -u anpr-admin-panel

# View recent logs
sudo journalctl -u anpr-admin-panel -n 50

# Follow live logs
sudo journalctl -u anpr-admin-panel -f

# View logs from specific time
sudo journalctl -u anpr-admin-panel --since "2024-01-01 00:00:00"
```

### Application Logs
The admin panel also creates application logs in the `admin_panel/logs/` directory.

## Security Considerations

1. **Firewall**: Consider restricting access to port 8084
2. **SSL**: For production, configure HTTPS
3. **Authentication**: Change default passwords
4. **File Permissions**: Ensure proper ownership and permissions

## Performance

### Resource Usage
- **Memory**: ~50-100MB typical usage
- **CPU**: Low usage when idle
- **Disk**: Minimal, mainly for logs and CSV data

### Optimization
1. **Database**: Consider migrating from CSV to SQLite/PostgreSQL for large datasets
2. **Caching**: Enable Redis for session caching
3. **Static Files**: Use nginx for serving static files

## Updates

To update the admin panel service:

1. Stop the service: `sudo systemctl stop anpr-admin-panel`
2. Update the code
3. Restart the service: `sudo systemctl start anpr-admin-panel`

## Support

For issues or questions:
1. Check the logs first
2. Verify configuration
3. Check file permissions
4. Review this documentation

## Integration with ANPR Service

The admin panel service works alongside the main ANPR service:

1. **ANPR Service**: Processes camera feeds and saves detections to CSV
2. **Admin Panel Service**: Provides web interface to view and manage detections

Both services can run simultaneously and are independent of each other.
