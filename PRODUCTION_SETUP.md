# ANPR System - Production Setup Guide

This guide will help you set up the ANPR (Automatic Number Plate Recognition) system on a production server.

## Prerequisites

- Ubuntu 20.04+ or Debian 10+ (recommended)
- Python 3.8 or higher
- MySQL 5.7+ or MariaDB 10.3+
- XAMPP (for MySQL) or standalone MySQL server
- Root/sudo access
- At least 4GB RAM (8GB+ recommended for GPU support)
- CUDA-capable GPU (optional, for better performance)

## Quick Setup (Automated)

Run the automated setup script:

```bash
chmod +x setup_production.sh
sudo ./setup_production.sh
```

The script will:
1. Install system dependencies
2. Set up Python virtual environment
3. Install Python packages
4. Configure MySQL database
5. Create systemd services
6. Set up admin panel

## Manual Setup Steps

### Step 1: System Dependencies

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install required packages
sudo apt install -y python3 python3-pip python3-venv mysql-server mysql-client \
    ffmpeg libsm6 libxext6 libfontconfig1 libxrender1 libgl1-mesa-glx \
    git curl wget

# For GPU support (NVIDIA)
sudo apt install -y nvidia-cuda-toolkit
```

### Step 2: Clone/Upload Project

```bash
# If using git
git clone <your-repo-url> /opt/anpr-system
cd /opt/anpr-system

# Or upload files via SCP/SFTP to /opt/anpr-system
```

### Step 3: Python Environment Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Python packages
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 4: MySQL Database Setup

```bash
# Start MySQL service
sudo systemctl start mysql
sudo systemctl enable mysql

# Secure MySQL installation (optional but recommended)
sudo mysql_secure_installation

# Create database and user
sudo mysql -u root -p << EOF
CREATE DATABASE IF NOT EXISTS anpr_system CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'anpr_user'@'localhost' IDENTIFIED BY 'your_secure_password';
GRANT ALL PRIVILEGES ON anpr_system.* TO 'anpr_user'@'localhost';
FLUSH PRIVILEGES;
EOF
```

### Step 5: Configure Database Connection

Edit `config.json`:

```json
{
  "database": {
    "host": "localhost",
    "port": 3306,
    "user": "anpr_user",
    "password": "your_secure_password",
    "database": "anpr_system",
    "pool_size": 5
  }
}
```

### Step 6: Initialize Database

```bash
# Activate virtual environment
source venv/bin/activate

# Initialize database schema
python init_database.py

# Create admin user
python create_admin_user.py
```

### Step 7: Configure Cameras

Edit `config.json` and update the `cameras` section with your RTSP URLs:

```json
{
  "cameras": [
    {
      "id": "cam_001",
      "name": "Main Entrance",
      "location": "Main Gate",
      "rtsp_source": "rtsp://username:password@camera_ip:554/stream",
      "enabled": true,
      ...
    }
  ]
}
```

### Step 8: Create Systemd Services

#### ANPR Service

Create `/etc/systemd/system/anpr-multi-camera.service`:

```ini
[Unit]
Description=ANPR Multi-Camera Service
After=network.target mysql.service

[Service]
Type=simple
User=anpr
WorkingDirectory=/opt/anpr-system
Environment="PATH=/opt/anpr-system/venv/bin"
ExecStart=/opt/anpr-system/venv/bin/python /opt/anpr-system/app_multi_camera_lprnet.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

#### Admin Panel Service

Create `/etc/systemd/system/anpr-admin-panel.service`:

```ini
[Unit]
Description=ANPR Admin Panel
After=network.target mysql.service

[Service]
Type=simple
User=anpr
WorkingDirectory=/opt/anpr-system/admin_panel
Environment="PATH=/opt/anpr-system/venv/bin"
ExecStart=/opt/anpr-system/venv/bin/python /opt/anpr-system/admin_panel/app.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### Step 9: Create System User

```bash
sudo useradd -r -s /bin/bash -d /opt/anpr-system anpr
sudo chown -R anpr:anpr /opt/anpr-system
```

### Step 10: Start Services

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable services
sudo systemctl enable anpr-multi-camera.service
sudo systemctl enable anpr-admin-panel.service

# Start services
sudo systemctl start anpr-multi-camera.service
sudo systemctl start anpr-admin-panel.service

# Check status
sudo systemctl status anpr-multi-camera.service
sudo systemctl status anpr-admin-panel.service
```

### Step 11: Firewall Configuration

```bash
# Allow admin panel port (default: 8084)
sudo ufw allow 8084/tcp

# Allow MySQL (if remote access needed)
sudo ufw allow 3306/tcp
```

## Verification

1. **Check ANPR Service:**
   ```bash
   sudo systemctl status anpr-multi-camera
   sudo journalctl -u anpr-multi-camera -f
   ```

2. **Check Admin Panel:**
   - Open browser: `http://your-server-ip:8084`
   - Login with admin credentials

3. **Check Database:**
   ```bash
   mysql -u anpr_user -p anpr_system -e "SELECT COUNT(*) FROM detections;"
   ```

## Default Credentials

- **Admin Panel:** 
  - Username: `admin`
  - Password: `admin123` (change immediately after first login)

## Post-Installation

1. **Change default admin password** (via admin panel)
2. **Configure cameras** in admin panel
3. **Add allowed license plates**
4. **Monitor logs** for any issues

## Troubleshooting

### Service won't start
```bash
# Check logs
sudo journalctl -u anpr-multi-camera -n 50
sudo journalctl -u anpr-admin-panel -n 50

# Check permissions
ls -la /opt/anpr-system
```

### Database connection errors
```bash
# Test MySQL connection
mysql -u anpr_user -p anpr_system

# Check config.json database settings
cat config.json | grep -A 5 database
```

### Camera connection issues
- Verify RTSP URLs are accessible
- Check camera credentials
- Test RTSP stream: `ffprobe rtsp://your-camera-url`

### Port already in use
```bash
# Check what's using port 8084
sudo lsof -i :8084

# Change port in admin_panel/app.py
```

## Maintenance

### Update System
```bash
cd /opt/anpr-system
source venv/bin/activate
git pull  # if using git
pip install -r requirements.txt --upgrade
sudo systemctl restart anpr-multi-camera
sudo systemctl restart anpr-admin-panel
```

### Backup Database
```bash
mysqldump -u anpr_user -p anpr_system > backup_$(date +%Y%m%d).sql
```

### View Logs
```bash
# ANPR Service logs
sudo journalctl -u anpr-multi-camera -f

# Admin Panel logs
sudo journalctl -u anpr-admin-panel -f

# Application logs
tail -f /opt/anpr-system/anpr_service.log
```

## Security Recommendations

1. **Change default passwords** immediately
2. **Use strong MySQL passwords**
3. **Enable firewall** (UFW)
4. **Use HTTPS** (setup reverse proxy with nginx)
5. **Regular backups** of database
6. **Keep system updated**
7. **Restrict admin panel access** (VPN/firewall rules)

## Performance Tuning

- **GPU Support:** Install CUDA drivers for faster processing
- **Database:** Optimize MySQL settings for your workload
- **Memory:** Ensure sufficient RAM for multiple cameras
- **Network:** Use wired connections for cameras

## Support

For issues or questions, check:
- Logs: `/var/log/` and application logs
- Configuration: `config.json`
- Database: MySQL error logs

