# ANPR System Configuration Guide

This document explains where different configuration data is stored in the ANPR system.

## Current Storage Architecture

### ✅ MySQL Database (Primary Storage)
The following data is stored in MySQL database (`anpr_system`):

1. **Detections** (`detections` table)
   - All license plate detections
   - Image paths
   - Verification status
   - Camera information
   - Timestamps

2. **Allowed Plates** (`allowed_plates` table)
   - Authorized license plates
   - Managed via admin panel

3. **Users** (`users` table)
   - Admin panel user accounts
   - Authentication credentials

4. **Cameras** (`cameras` table)
   - Basic camera configuration (optional)
   - Currently not actively used

### 📄 JSON File (`config.json`)
The following configuration is stored in `config.json`:

1. **Database Connection Settings**
   ```json
   {
     "database": {
       "host": "localhost",
       "port": 3306,
       "user": "root",
       "password": "",
       "database": "anpr_system",
       "pool_size": 5
     }
   }
   ```

2. **System Mode**
   - `system_mode`: "multi_camera"

3. **Global Settings**
   - `fps_limit`: Frame rate limit
   - `frame_skip`: Frames to skip
   - `save_dir`: Directory for saved frames

4. **Display Settings**
   - `headless_mode`: Run without GUI
   - `show_fps`: Show FPS counter
   - `grid_layout`: Camera grid layout
   - Other display preferences

5. **Headless Settings**
   - `log_level`: Logging level
   - `save_frames`: Save frames in headless mode
   - `log_file`: Log file path

6. **Camera Configuration** (Array of cameras)
   - Camera ID, name, location
   - RTSP source URL
   - Deduplication window
   - Confidence threshold
   - Enabled/disabled status
   - API settings
   - ROI (Region of Interest) settings
   - ROI polygon coordinates

## Why Camera Config is in JSON

Camera configuration remains in `config.json` because:
1. **Complex nested structures**: ROI polygons, API settings, etc.
2. **Easy editing**: JSON is human-readable and easy to modify
3. **No frequent changes**: Camera config doesn't change as often as detections
4. **Compatibility**: `app_multi_camera_lprnet.py` reads directly from JSON

## Configuration Files Location

```
ANPR-Production/
├── config.json              # Main configuration (cameras, settings)
├── database_schema.sql      # MySQL database schema
├── db_connection.py         # Database connection module
│
├── admin_panel/
│   ├── app.py              # Admin panel (reads from MySQL)
│   ├── camera_manager.py   # Camera management (reads/writes config.json)
│   ├── plate_manager.py    # Plate management (reads/writes MySQL)
│   └── detection_manager.py # Detection management (reads from MySQL)
│
└── app_multi_camera_lprnet.py     # Main ANPR service (reads config.json)
```

## How to Update Configuration

### Camera Configuration
1. **Via Admin Panel**: 
   - Go to `/cameras` page
   - Add/Edit/Delete cameras
   - Changes saved to `config.json`

2. **Manually**:
   - Edit `config.json` directly
   - Restart ANPR service for changes to take effect

### Allowed Plates
1. **Via Admin Panel**:
   - Go to `/plates` page
   - Add/Delete plates
   - Changes saved to MySQL database

2. **Via Script**:
   ```bash
   python create_admin_user.py
   ```

### Database Settings
- Edit `config.json` → `database` section
- Restart services for changes to take effect

## Migration to Full MySQL (Optional)

If you want to move camera configuration to MySQL as well:

1. **Update database schema** to store full camera config
2. **Update `app_multi_camera_lprnet.py`** to read from MySQL
3. **Update `camera_manager.py`** to use MySQL
4. **Create migration script** to import cameras from JSON

**Note**: This is optional. The current hybrid approach (JSON for cameras, MySQL for data) works well and is simpler.

## Summary

| Data Type | Storage Location | Managed By |
|-----------|-----------------|------------|
| Detections | MySQL (`detections`) | `plate_logger.py` |
| Allowed Plates | MySQL (`allowed_plates`) | Admin Panel |
| Users | MySQL (`users`) | `create_admin_user.py` |
| Camera Config | `config.json` | Admin Panel / Manual |
| System Settings | `config.json` | Manual edit |
| Database Config | `config.json` | Manual edit |

## Quick Reference

- **View detections**: Admin Panel → Detections (from MySQL)
- **Manage plates**: Admin Panel → Plates (MySQL)
- **Manage cameras**: Admin Panel → Cameras (config.json)
- **Edit system settings**: Edit `config.json` directly
- **Database connection**: Edit `config.json` → `database` section

