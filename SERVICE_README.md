# ANPR Multi-Camera Service

This directory contains the ANPR (Automatic Number Plate Recognition) multi-camera system configured to run as a systemd service.

## Files Overview

- `app_multi_camera.py` - Main ANPR application
- `plate_logger.py` - Plate logging module
- `config.json` - Configuration file
- `allowed_plates.json` - Allowed plates database
- `ANPR_ver15.pt` - YOLO model file
- `start_anpr_service.sh` - Service startup script
- `anpr-multi-camera.service` - Systemd service file
- `install_service.sh` - Service installation script
- `manage_service.sh` - Service management script

## Quick Start

### 1. Install the Service
```bash
./install_service.sh
```

### 2. Start the Service
```bash
./manage_service.sh start
```

### 3. Check Status
```bash
./manage_service.sh status
```

## Service Management

Use the `manage_service.sh` script for easy service control:

```bash
# Start the service
./manage_service.sh start

# Stop the service
./manage_service.sh stop

# Restart the service
./manage_service.sh restart

# Check service status
./manage_service.sh status

# View live logs
./manage_service.sh logs

# View recent logs
./manage_service.sh logs-tail

# Enable auto-start on boot
./manage_service.sh enable

# Disable auto-start on boot
./manage_service.sh disable

# Uninstall the service
./manage_service.sh uninstall
```

## Manual Service Commands

You can also use systemctl directly:

```bash
# Start service
sudo systemctl start anpr-multi-camera

# Stop service
sudo systemctl stop anpr-multi-camera

# Restart service
sudo systemctl restart anpr-multi-camera

# Check status
sudo systemctl status anpr-multi-camera

# View logs
journalctl -u anpr-multi-camera -f

# Enable on boot
sudo systemctl enable anpr-multi-camera

# Disable on boot
sudo systemctl disable anpr-multi-camera
```

## Logs

- **Service logs**: `journalctl -u anpr-multi-camera -f`
- **Application logs**: `~/Desktop/ANPR-Space/anpr_service.log`

## Configuration

Edit `config.json` to configure:
- Camera settings
- API endpoints
- Detection parameters
- Headless mode settings

## Troubleshooting

### Service won't start
1. Check service status: `sudo systemctl status anpr-multi-camera`
2. Check logs: `journalctl -u anpr-multi-camera -n 50`
3. Verify all files exist in the service directory
4. Check file permissions

### Service stops unexpectedly
1. Check logs for errors: `journalctl -u anpr-multi-camera -f`
2. Verify camera connections
3. Check system resources (memory, CPU)

### Camera connection issues
1. Verify RTSP URLs in config.json
2. Check network connectivity
3. Test camera access manually

## Auto-Start on Boot

The service is configured to start automatically when the system boots. This is enabled during installation.

To disable auto-start:
```bash
./manage_service.sh disable
```

To re-enable auto-start:
```bash
./manage_service.sh enable
```

## Security

The service runs under your user account with appropriate security restrictions:
- No new privileges
- Private temporary directory
- Protected system files
- Limited file system access

## Resource Limits

- Maximum memory usage: 4GB
- Maximum open files: 65536
- Automatic restart on failure (10-second delay)
