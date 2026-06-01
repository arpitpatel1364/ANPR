# ANPR (Automatic Number Plate Recognition) System

A high-performance, multi-camera ANPR processing pipeline optimized for low-end to production environments. The system reads RTSP streams, performs YOLOv8 detection and LPRNet plate recognition via a multiprocessing pipeline, checks allowed formats, verifies plates in a MySQL database, and alerts an administrative dashboard in real-time.

---

## Quick Start (Production Setup)

**Prerequisites:** Ubuntu 20.04+, Python 3.8+, MySQL/MariaDB, 4GB+ RAM.

We recommend using the automated setup script to configure dependencies, database structures, and systemd services automatically:

```bash
# Make scripts executable
chmod +x *.sh

# Run automated setup script
sudo ./setup_production.sh
```

---

## Commands Quick Reference

The system runs as two background systemd services:
1. **ANPR Multi-Camera Core Service:** anpr-multi-camera
2. **ANPR Admin Panel Dashboard Service:** anpr-admin-panel

### 1. Management Script Commands
We provide helper scripts (manage_service.sh and manage_admin_service.sh) to simplify execution without typing long commands:

| Action | ANPR Core Service Command | Admin Panel Service Command |
| :--- | :--- | :--- |
| **Start** | ./manage_service.sh start | ./manage_admin_service.sh start |
| **Stop** | ./manage_service.sh stop | ./manage_admin_service.sh stop |
| **Restart** | ./manage_service.sh restart | ./manage_admin_service.sh restart |
| **Status** | ./manage_service.sh status | ./manage_admin_service.sh status |
| **Live Logs** | ./manage_service.sh logs | ./manage_admin_service.sh logs |
| **Recent Logs** | ./manage_service.sh logs-tail | (Displays inside status) |
| **Enable on Boot** | ./manage_service.sh enable | ./manage_admin_service.sh enable |
| **Disable on Boot**| ./manage_service.sh disable | ./manage_admin_service.sh disable |
| **Uninstall Service**| ./manage_service.sh uninstall | ./manage_admin_service.sh uninstall |

### 2. Standard systemctl Commands
Alternatively, you can manage the services directly using native Ubuntu systemctl utility commands:

```bash
# --- Start Services ---
sudo systemctl start anpr-multi-camera
sudo systemctl start anpr-admin-panel

# --- Stop Services ---
sudo systemctl stop anpr-multi-camera
sudo systemctl stop anpr-admin-panel

# --- Restart Services ---
sudo systemctl restart anpr-multi-camera
sudo systemctl restart anpr-admin-panel

# --- Service Status ---
sudo systemctl status anpr-multi-camera
sudo systemctl status anpr-admin-panel

# --- Show Live Logs ---
sudo journalctl -u anpr-multi-camera -f
sudo journalctl -u anpr-admin-panel -f

# --- Enable/Disable Autostart on Boot ---
sudo systemctl enable anpr-multi-camera anpr-admin-panel
sudo systemctl disable anpr-multi-camera anpr-admin-panel
```

---

## Local Developer / Local Setup

If you prefer to run the system in the foreground (e.g., for local testing or debugging) instead of using system services:

### 1. Virtual Environment & Dependencies
```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install requirements
pip install -r requirements.txt
```

### 2. Configure Database & Initial Data
Ensure MySQL is running and set your credentials inside the "database" block of config.json. Then run:
```bash
# Initialize MySQL tables and schema
python scripts/init_database.py

# Create default administrator credentials
python scripts/create_admin_user.py
```

### 3. Run in Active Terminal (Development Mode)
Run the two services in separate shell windows:

* **Terminal 1: ANPR Core Processing Pipeline**
  ```bash
  source venv/bin/activate
  python app_multi_camera_lprnet.py
  ```

* **Terminal 2: Admin Dashboard Panel Web Server**
  ```bash
  source venv/bin/activate
  cd admin_panel
  python app.py
  ```

Once running, navigate to http://localhost:8084 to access the dashboard.
* **Default Credentials:** admin / admin123

---

## Architecture & Project Structure

The project is split into two independent services that work seamlessly together:
- **ANPR Service:** Processes camera feeds and logs detections to MySQL.
- **Admin Panel Service:** Provides a web interface to view and manage detections.

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
│   ├── app.py                   # Flask web server
│   ├── templates/               # HTML templates
│   └── static/                  # CSS, JS, images
└── requirements.txt             # Python dependencies
```

---

## MySQL Database Migration

If you are upgrading from an older version of this system that used CSV or JSON files for plate storage:

1. Configure your MySQL credentials in config.json.
2. Initialize database schema:
   ```bash
   python scripts/init_database.py
   ```
3. Run the automated migration script to securely transfer historical logs without duplicates:
   ```bash
   python scripts/migrate_to_mysql.py
   ```
4. Start your services.

---

## Troubleshooting & Maintenance

### Common Issues

* **Service won't start:**
  Check error details in the system journal:
  ```bash
  sudo journalctl -u anpr-multi-camera -n 50
  ```
  Ensure the database user is permitted and credentials match config.json.

* **Port 8084 already in use (Admin Panel):**
  Identify and terminate the occupying process:
  ```bash
  sudo lsof -i :8084
  sudo kill -9 <PID>
  ```

* **Camera Connection Fails:**
  Verify the RTSP feed URL manually via VLC or ffprobe:
  ```bash
  ffprobe rtsp://your-camera-url
  ```
