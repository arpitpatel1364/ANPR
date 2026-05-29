import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from werkzeug.security import generate_password_hash
from db_connection import DatabaseConnection

def migrate_db():
    print("Starting DB migration...")
    
    # 1. Alter users table
    try:
        with DatabaseConnection() as db:
            print("Altering users table...")
            db.execute("ALTER TABLE users MODIFY COLUMN role ENUM('admin', 'viewer', 'superadmin') DEFAULT 'viewer'")
    except Exception as e:
        print(f"Notice: {e}")

    # 2. Add SAdmin user
    try:
        with DatabaseConnection() as db:
            print("Adding SAdmin user...")
            pw_hash = generate_password_hash("Admin@123")
            db.execute(
                "INSERT INTO users (username, password_hash, role, is_active) VALUES (%s, %s, %s, 1) ON DUPLICATE KEY UPDATE password_hash = VALUES(password_hash), role = VALUES(role)",
                ('SAdmin', pw_hash, 'superadmin')
            )
    except Exception as e:
        print(f"Error adding SAdmin: {e}")

    # 3. Alter cameras table
    try:
        with DatabaseConnection() as db:
            print("Altering cameras table...")
            db.execute("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS roi_polygon TEXT DEFAULT NULL")
            db.execute("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS api_settings TEXT DEFAULT NULL")
    except Exception as e:
        print(f"Notice: {e}")

    # 4. Create system_settings table
    try:
        with DatabaseConnection() as db:
            print("Creating system_settings table...")
            db.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                id INT AUTO_INCREMENT PRIMARY KEY,
                setting_key VARCHAR(100) NOT NULL UNIQUE,
                setting_value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)
    except Exception as e:
        print(f"Error creating system_settings: {e}")

    # 5. Load config.json
    try:
        if os.path.exists('config.json'):
            with open('config.json', 'r') as f:
                config = json.load(f)
            print("Loaded config.json")
            
            with DatabaseConnection() as db:
                # Migrate settings
                settings_to_migrate = ['system_mode', 'global_settings', 'display_settings', 'headless_settings']
                for key in settings_to_migrate:
                    if key in config:
                        val = json.dumps(config[key]) if isinstance(config[key], (dict, list)) else str(config[key])
                        db.execute(
                            "INSERT INTO system_settings (setting_key, setting_value) VALUES (%s, %s) ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)",
                            (key, val)
                        )
                print("Settings migrated.")
                
                # Migrate cameras
                if 'cameras' in config:
                    # Clear old cameras to avoid duplicates or orphans during migration
                    db.execute("TRUNCATE TABLE cameras")
                    for cam in config['cameras']:
                        api_settings = json.dumps(cam.get('api_settings', {}))
                        roi_polygon = json.dumps(cam.get('roi_polygon', []))
                        
                        db.execute("""
                            INSERT INTO cameras (camera_id, name, location, rtsp_source, enabled, dedup_window, confidence_threshold, api_enabled, api_settings, roi_polygon)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (
                            cam.get('id'), cam.get('name'), cam.get('location', ''), cam.get('rtsp_source'),
                            cam.get('enabled', True), cam.get('dedup_window', 30), cam.get('confidence_threshold', 0.8),
                            cam.get('api_enabled', False), api_settings, roi_polygon
                        ))
                    print(f"Migrated {len(config['cameras'])} cameras.")
                    
        else:
            print("config.json not found, skipping data migration.")
    except Exception as e:
        print(f"Error during data migration: {e}")

if __name__ == "__main__":
    migrate_db()
