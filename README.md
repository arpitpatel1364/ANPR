# ANPR (Automatic Number Plate Recognition) System


## 🚀 Quick Start (Production Setup)

**Prerequisites:** Ubuntu 20.04+, Python 3.8+, MySQL/MariaDB, 4GB+ RAM, and optionally a CUDA-capable GPU.

We highly recommend using the automated setup script for production:

```bash
# Clone the repository
git clone <your-repo-url> /opt/anpr-system
cd /opt/anpr-system

# Make scripts executable
chmod +x *.sh

# Run automated setup script
sudo ./setup_production.sh
```

### Manual Development Setup

If you prefer to run it manually without `systemd`:
```bash
# 1. Install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Setup database
python scripts/init_database.py
python scripts/create_admin_user.py

# 3. Configure cameras in config.json

# 4. Run ANPR service
python app_multi_camera_lprnet.py

# 5. Run admin panel (in another terminal)
cd admin_panel
python app.py
```

---

## 🏗️ Architecture & Project Structure

The project is split into two independent services that work seamlessly together:
1. **ANPR Service:** Processes camera feeds and saves detections to MySQL.
2. **Admin Panel Service:** Provides a web interface to view and manage detections.

```
ANPR-Production/
├── app_multi_camera_lprnet.py   # Main ANPR processing service
├── plate_logger.py              # Detection logging module (MySQL)
├── db_connection.py             # Database connection handler
├── config.json                  # Main configuration file (cameras, settings)
├── database_schema.sql          # Database schema
├── scripts/                     # Helper & migration scripts
│   ├── init_database.py
│   ├── create_admin_user.py
│   └── migrate_to_mysql.py
├── admin_panel/                 # Admin panel web application
│   ├── app.py                   # Flask application
│   ├── templates/               # HTML templates
│   └── static/                  # CSS, JS, images
└── requirements.txt             # Python dependencies
```

### Configuration Storage

| Data Type | Storage Location | Managed By |
|-----------|-----------------|------------|
| Detections | MySQL (`detections`) | `plate_logger.py` |
| Allowed Plates | MySQL (`allowed_plates`) | Admin Panel |
| Users | MySQL (`users`) | `scripts/create_admin_user.py` |
| Camera Config | `config.json` | Admin Panel / Manual Edit |
| System Settings | `config.json` | Manual Edit |
| Database Config | `config.json` | Manual Edit |

**Note on Camera Configuration:** Camera configurations (RTSP URLs, ROIs, thresholds) are intentionally kept in `config.json` to allow complex nested structures like ROI polygons. They can be edited via the Admin Panel UI.

---

## 🔧 Managing Systemd Services

The system is deployed using two background systemd services:
1. `anpr-multi-camera`
2. `anpr-admin-panel`

We provide handy management scripts (`manage_service.sh` and `manage_admin_service.sh`) so you do not need to memorize systemctl commands.

### ANPR Service Management
```bash
./manage_service.sh start      # Start the service
./manage_service.sh stop       # Stop the service
./manage_service.sh restart    # Restart the service
./manage_service.sh status     # Check status
./manage_service.sh logs       # View live logs
```

### Admin Panel Management
```bash
./manage_admin_service.sh start    # Start the admin panel
./manage_admin_service.sh status   # Check status
./manage_admin_service.sh logs     # View live logs
```

*(You can also use standard `sudo systemctl start anpr-multi-camera` and `journalctl -u anpr-multi-camera -f` if you prefer).*

---

## 💻 Admin Panel Interface

Once services are running, the Admin Panel is accessible at:
- **URL**: `http://localhost:8084` (or your server's IP address)
- **Default Login**: `admin` / `admin123` *(Please change immediately)*

**Key Capabilities:**
- **Dashboard:** Real-time statistics, live detection feed, and camera health.
- **Plates:** Add, delete, and bulk-import allowed license plates.
- **Cameras:** Visually configure RTSP streams, test connections, and toggle feeds.
- **History:** Search, filter, and export historical detections.

---

## 🗄️ MySQL Database Migration

If you are upgrading from an older version of this system that used CSV/JSON for storage, follow these steps to migrate to MySQL:

1. Setup your MySQL server and configure credentials in `config.json` under the `database` key.
2. Initialize the tables:
   ```bash
   python scripts/init_database.py
   ```
3. Run the migration script to safely transfer old data (skips duplicates automatically):
   ```bash
   python scripts/migrate_to_mysql.py
   ```
4. Start your services. The system is now running purely on MySQL!

---

## 🛠️ Troubleshooting & Maintenance

### Common Issues

**Service won't start:**
1. Check the logs: `sudo journalctl -u anpr-multi-camera -n 50`
2. Check permissions: Ensure the user running the service owns the project files.
3. Verify `config.json` is valid JSON and database credentials are correct.

**Port 8084 already in use (Admin Panel):**
1. Identify the process: `sudo lsof -i :8084`
2. Kill the process: `sudo kill -9 <PID>`
3. Alternatively, change the port in `admin_panel/config.py`.

**Camera Connection Issues:**
1. Test your RTSP stream manually via VLC or `ffprobe rtsp://your-camera-url`.
2. Ensure no firewall is blocking the internal RTSP stream.

### Maintenance Commands

**Update System (Git Workflow):**
```bash
cd /opt/anpr-system
source venv/bin/activate
git pull
pip install -r requirements.txt --upgrade
sudo systemctl restart anpr-multi-camera
sudo systemctl restart anpr-admin-panel
```

**Backup Database:**
```bash
mysqldump -u anpr_user -p anpr_system > backup_$(date +%Y%m%d).sql
```
