# ANPR (Automatic Number Plate Recognition) System

A high-performance, multi-camera ANPR processing pipeline optimized for production environments. The system reads RTSP streams, performs YOLOv8 vehicle detection and LPRNet plate recognition via an asynchronous multiprocessing pipeline, verifies plates against an allowed list, logs detections to a MySQL database, and powers a modern administrative web dashboard for real-time monitoring and configuration.

---

## Quick Start (Production Setup)

**Prerequisites:** Ubuntu 20.04+, Python 3.8+, XAMPP/MySQL/MariaDB, 4GB+ RAM, NVIDIA GPU (optional but highly recommended for CUDA acceleration).

The system includes a fully automated, turnkey setup script. It installs system dependencies, checks the Python environment, auto-creates the `anpr_system` database, builds the required tables, creates the default admin user, and configures systemd services.

```bash
# Make scripts executable
chmod +x *.sh

# Run the fully automated, turnkey setup
sudo ./setup.sh all
```

Once the setup completes, the backend inference engine and the admin dashboard will automatically start in the background.

Navigate to **http://localhost:8084** to access the dashboard.
* **Default Login:** `admin` / `admin123` *(Please change this upon first login!)*

---

## System Management Quick Reference

The system runs as two background systemd services:
1. **Backend AI Pipeline:** `anpr-multi-camera`
2. **Admin Web Dashboard:** `anpr-admin-panel`

We provide a unified management script (`run.sh`) to easily control these services. 

### Common Commands

```bash
# Start all services
sudo ./run.sh start all

# Stop all services
sudo ./run.sh stop all

# Restart the backend AI pipeline
sudo ./run.sh restart backend

# View live logs for the admin panel
sudo ./run.sh logs admin

# Check the status of both services
sudo ./run.sh status all
```

### Manual systemctl Commands (Optional)
If you prefer native systemd commands:
```bash
sudo systemctl restart anpr-multi-camera
sudo journalctl -u anpr-admin-panel -f
```

---

## System Features

* **Centralized Dashboard:** Manage your cameras, regions of interest (ROI), allowed license plates, and system settings completely from the modern web UI. No more editing JSON configuration files.
* **Asynchronous AI Pipeline:** The core engine (`app_multi_camera_lprnet.py`) runs an advanced multi-process loop that handles frame grabbing, inference, and database writing completely asynchronously to eliminate bottlenecking.
* **Database Integration:** Seamlessly integrated with MySQL. The system uses a centralized database for zero-downtime camera updates and robust historical data logging.
* **Live ROI Editor:** Define custom polygon regions of interest for each camera directly in the web browser using a live snapshot from the camera stream.

---

## Architecture & Project Structure

```
ANPR/
├── app_multi_camera_lprnet.py   # Core asynchronous AI inference engine
├── run.sh                       # Unified service management controller
├── setup.sh                     # Turnkey installation and migration script
├── db_connection.py             # Global MySQL connection pool manager
├── database_schema.sql          # Base database structure definition
├── admin_panel/                 # Web Dashboard
│   ├── app.py                   # Flask web server
│   ├── camera_manager.py        # Camera API routing and stream logic
│   ├── templates/               # Modern HTML frontend
│   └── static/                  # CSS/JS assets and live frame cache
├── scripts/                     # Helper & migration scripts
│   ├── init_database.py         # Automated database builder
│   └── migrate_to_mysql.py      # Legacy flat-file to MySQL migration
└── requirements.txt             # Core Python dependencies
```

---

## Migrating from Legacy Versions

If you are upgrading from an older version of this system that relied on `config.json` and flat-file `detections.csv` storage:

1. Run the automated setup: `sudo ./setup.sh all` (this provisions the MySQL tables).
2. Stop the services: `sudo ./run.sh stop all`
3. Run the automated migration script to securely transfer your historical logs and camera configs without duplicates:
   ```bash
   source anpr_env/bin/activate
   python scripts/migrate_to_mysql.py
   python scripts/config_db.py
   ```
4. Restart the system: `sudo ./run.sh start all`

---

## Troubleshooting

* **Service won't start or AI is crashing:**
  Check the live logs for the core pipeline to identify model or stream errors:
  ```bash
  sudo ./run.sh logs backend
  ```

* **Dashboard not loading / Port 8084 in use:**
  If the admin panel fails to bind to port 8084, another service may be using it.
  ```bash
  sudo lsof -i :8084
  sudo kill -9 <PID>
  sudo ./run.sh restart admin
  ```

* **Cameras repeatedly disconnecting:**
  Ensure your RTSP links are stable. You can test them manually using VLC or:
  ```bash
  ffprobe rtsp://your-camera-url
  ```
