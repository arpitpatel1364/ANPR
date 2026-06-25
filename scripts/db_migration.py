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

    # 2. Add superadmin user
    try:
        with DatabaseConnection() as db:
            print("Adding superadmin user...")
            pw_hash = generate_password_hash("superadmin@123")
            db.execute(
                "INSERT INTO users (username, password_hash, role, is_active) VALUES (%s, %s, %s, 1) ON DUPLICATE KEY UPDATE password_hash = VALUES(password_hash), role = VALUES(role)",
                ('superadmin', pw_hash, 'superadmin')
            )
    except Exception as e:
        print(f"Error adding superadmin: {e}")

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

    print("DB migration completed.")

if __name__ == "__main__":
    migrate_db()
