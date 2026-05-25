# ANPR (Automatic Number Plate Recognition) System

A production-ready license plate recognition system with multi-camera support, real-time detection, and comprehensive admin panel.

## Features

- 🚗 **Multi-Camera Support** - Monitor multiple RTSP camera streams simultaneously
- 🔍 **Real-Time Detection** - Live license plate recognition with high accuracy
- 📊 **Admin Dashboard** - Comprehensive web-based admin panel
- 🗄️ **MySQL Database** - Scalable data storage with full history
- 📸 **Image Storage** - Automatic saving of detection images
- 📄 **PDF Export** - Export detection records with images
- 🔐 **User Authentication** - Secure admin panel access
- 📡 **Real-Time Updates** - WebSocket-based live updates
- 🎯 **API Integration** - Camera API integration for access control

## Quick Start

### Production Setup (Recommended)

```bash
# Run automated setup script
sudo ./setup_production.sh
```

See [PRODUCTION_SETUP.md](PRODUCTION_SETUP.md) for detailed manual setup instructions.

### Development Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Setup database
python init_database.py
python create_admin_user.py

# Configure cameras in config.json

# Run ANPR service
python app_multi_camera.py

# Run admin panel (in another terminal)
cd admin_panel
python app.py
```

## Project Structure

```
ANPR-Production/
├── app_multi_camera.py          # Main ANPR processing service
├── plate_logger.py              # Detection logging module
├── db_connection.py             # Database connection handler
├── config.json                  # Main configuration file
├── database_schema.sql          # Database schema
├── init_database.py             # Database initialization script
├── create_admin_user.py         # Admin user creation script
├── setup_production.sh          # Production setup script
├── PRODUCTION_SETUP.md          # Production setup guide
├── admin_panel/                 # Admin panel web application
│   ├── app.py                   # Flask application
│   ├── templates/               # HTML templates
│   ├── static/                  # CSS, JS, images
│   └── ...
└── requirements.txt             # Python dependencies
```

## Configuration

### Database Configuration

Edit `config.json`:

```json
{
  "database": {
    "host": "localhost",
    "port": 3306,
    "user": "anpr_user",
    "password": "your_password",
    "database": "anpr_system",
    "pool_size": 5
  }
}
```

### Camera Configuration

Add cameras in `config.json`:

```json
{
  "cameras": [
    {
      "id": "cam_001",
      "name": "Main Entrance",
      "location": "Main Gate",
      "rtsp_source": "rtsp://user:pass@camera_ip:554/stream",
      "enabled": true,
      "confidence_threshold": 0.8,
      "dedup_window": 50
    }
  ]
}
```

## Services

### ANPR Service

Processes camera streams and detects license plates:

```bash
# Start service
sudo systemctl start anpr-multi-camera

# Check status
sudo systemctl status anpr-multi-camera

# View logs
sudo journalctl -u anpr-multi-camera -f
```

### Admin Panel

Web interface for managing the system (default port: 8084):

```bash
# Start service
sudo systemctl start anpr-admin-panel

# Check status
sudo systemctl status anpr-admin-panel

# View logs
sudo journalctl -u anpr-admin-panel -f
```

## Access

- **Admin Panel:** http://your-server-ip:8084
- **Default Login:**
  - Username: `admin`
  - Password: `admin123` (change immediately!)

## Documentation

- [PRODUCTION_SETUP.md](PRODUCTION_SETUP.md) - Production deployment guide
- [CONFIGURATION_GUIDE.md](CONFIGURATION_GUIDE.md) - Configuration details
- [MYSQL_MIGRATION_README.md](MYSQL_MIGRATION_README.md) - Database migration guide

## Requirements

- Python 3.8+
- MySQL 5.7+ or MariaDB 10.3+
- OpenCV
- PaddleOCR
- YOLO (Ultralytics)
- Flask
- ReportLab (for PDF export)

See `requirements.txt` for complete list.

## Maintenance

### Cleanup Unnecessary Files

```bash
./cleanup_unnecessary_files.sh
```

### Backup Database

```bash
mysqldump -u anpr_user -p anpr_system > backup_$(date +%Y%m%d).sql
```

### Update System

```bash
cd /opt/anpr-system
source venv/bin/activate
pip install -r requirements.txt --upgrade
sudo systemctl restart anpr-multi-camera
sudo systemctl restart anpr-admin-panel
```

## Troubleshooting

### Service Issues

```bash
# Check service status
sudo systemctl status anpr-multi-camera
sudo systemctl status anpr-admin-panel

# View recent logs
sudo journalctl -u anpr-multi-camera -n 50
sudo journalctl -u anpr-admin-panel -n 50
```

### Database Issues

```bash
# Test connection
mysql -u anpr_user -p anpr_system

# Check database exists
mysql -u root -p -e "SHOW DATABASES LIKE 'anpr_system';"
```

### Camera Issues

- Verify RTSP URLs are accessible
- Check camera credentials
- Test stream: `ffprobe rtsp://your-camera-url`

## License

[Your License Here]

## Support

For issues, check:
- Application logs
- System logs: `journalctl`
- Configuration: `config.json`
- Database: MySQL error logs

