# MySQL Migration Guide

This document explains how to migrate your ANPR system from CSV/JSON to MySQL database.

## Prerequisites

1. **XAMPP installed and running**
   - Start MySQL service in XAMPP Control Panel
   - Default MySQL port: 3306
   - Default username: `root`
   - Default password: (empty)

2. **Python MySQL connector installed**
   ```bash
   pip install mysql-connector-python
   ```

## Setup Steps

### 1. Create Database

Open phpMyAdmin (http://localhost/phpmyadmin) or MySQL command line and run:

```sql
CREATE DATABASE anpr_system CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 2. Configure Database Connection

Edit `config.json` and add database configuration:

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

### 3. Initialize Database Tables

The database tables will be created automatically when you run the system, or you can run:

```bash
python db_connection.py
```

This will create the following tables:
- `detections` - Stores all license plate detections
- `allowed_plates` - Stores authorized license plates
- `users` - Stores admin panel users (optional)
- `cameras` - Stores camera configuration (optional)

### 4. Migrate Existing Data

Run the migration script to import existing CSV/JSON data:

```bash
python migrate_to_mysql.py
```

This will:
- Import all detections from `plate_detections.csv`
- Import all allowed plates from `allowed_plates.json`
- Skip duplicates automatically

### 5. Test the System

1. Start the ANPR service:
   ```bash
   python app_multi_camera_lprnet.py
   ```

2. Start the admin panel:
   ```bash
   cd admin_panel
   python app.py
   ```

3. Verify data is being saved to MySQL instead of CSV

## Database Schema

### detections Table
- `id` - Auto-increment primary key
- `timestamp` - Detection timestamp
- `license_plate` - Detected license plate
- `verification_status` - VERIFIED or NOT_VERIFIED
- `access_granted` - YES or NO
- `detection_confidence` - Confidence score
- `processing_time_ms` - Processing time
- `camera_source` - Camera name/location
- `frame_number` - Frame number
- `detection_count` - Detection count
- `log_reason` - Reason for logging
- `image_full_raw` - Path to raw image
- `image_full_annotated` - Path to annotated image
- `image_plate_crop` - Path to cropped plate image

### allowed_plates Table
- `id` - Auto-increment primary key
- `license_plate` - License plate (unique)
- `description` - Optional description
- `added_by` - User who added it
- `created_at` - Creation timestamp
- `updated_at` - Last update timestamp

## Changes Made

### Files Updated:
1. `plate_logger.py` - Now uses MySQL instead of CSV
2. `admin_panel/app.py` - Dashboard reads from MySQL
3. `admin_panel/detection_manager.py` - Detection management uses MySQL
4. `admin_panel/plate_manager.py` - Plate management uses MySQL
5. `admin_panel/websocket_server.py` - WebSocket updates from MySQL
6. `admin_panel/api_bridge.py` - API endpoints use MySQL

### New Files:
1. `db_connection.py` - Database connection module
2. `database_schema.sql` - Database schema SQL file
3. `migrate_to_mysql.py` - Migration script

## Troubleshooting

### Connection Errors
- Ensure MySQL is running in XAMPP
- Check database credentials in `config.json`
- Verify database `anpr_system` exists

### Import Errors
- Check CSV/JSON file formats
- Ensure database tables are created
- Check file permissions

### Performance Issues
- Adjust connection pool size in `config.json`
- Add database indexes if needed
- Consider archiving old detections

## Rollback

If you need to rollback to CSV/JSON:
1. Export data from MySQL to CSV
2. Update `plate_logger.py` to use CSV (revert changes)
3. Update admin panel files to use CSV/JSON

## Support

For issues or questions, check:
- Database connection logs
- Application error logs
- MySQL error logs in XAMPP

