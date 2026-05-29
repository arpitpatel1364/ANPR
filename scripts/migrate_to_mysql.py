#!/usr/bin/env python3
"""
Migration Script: CSV/JSON to MySQL
Migrates existing data from CSV and JSON files to MySQL database
"""

import os
import sys
import csv
import json
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db_connection import DatabaseConnection, initialize_database, test_connection

def migrate_csv_to_mysql(csv_file='plate_detections.csv'):
    """Migrate detections from CSV to MySQL"""
    if not os.path.exists(csv_file):
        print(f"⚠️ CSV file not found: {csv_file}")
        return 0
    
    print(f"📄 Reading detections from {csv_file}...")
    
    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        if not rows:
            print("⚠️ CSV file is empty")
            return 0
        
        print(f"📊 Found {len(rows)} detections to migrate...")
        
        migrated = 0
        skipped = 0
        
        with DatabaseConnection() as db:
            for row in rows:
                try:
                    # Parse timestamp
                    timestamp_str = row.get('Timestamp', '')
                    try:
                        if '.' in timestamp_str:
                            timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S.%f')
                        else:
                            timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                    except:
                        timestamp = datetime.now()
                    
                    # Insert into database
                    query = """
                        INSERT INTO detections 
                        (timestamp, license_plate, verification_status, access_granted,
                         detection_confidence, processing_time_ms, camera_source,
                         detection_count, log_reason, image_full_raw, image_full_annotated, image_plate_crop)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    
                    # Helper function to clean image path values
                    def clean_image_path(value):
                        if value is None:
                            return None
                        value_str = str(value).strip()
                        # Handle pandas 'nan', empty strings, or None
                        if not value_str or value_str.lower() in ['nan', 'none', 'null', '']:
                            return None
                        return value_str
                    
                    # Get image paths - preserve actual paths, convert empty/nan to None
                    image_full_raw = clean_image_path(row.get('Image_Full_Raw'))
                    image_full_annotated = clean_image_path(row.get('Image_Full_Annotated'))
                    image_plate_crop = clean_image_path(row.get('Image_Plate_Crop'))
                    
                    params = (
                        timestamp,
                        row.get('License_Plate', ''),
                        row.get('Verification_Status', 'NOT_VERIFIED'),
                        row.get('Access_Granted', 'NO'),
                        float(row.get('Detection_Confidence', 0)) if row.get('Detection_Confidence') else 0.0,
                        float(row.get('Processing_Time_MS', 0)) if row.get('Processing_Time_MS') else 0.0,
                        row.get('Camera_Source', 'unknown'),
                        int(row.get('Detection_Count', 1)) if row.get('Detection_Count') else 1,
                        clean_image_path(row.get('Log_Reason', '')) or None,
                        image_full_raw,
                        image_full_annotated,
                        image_plate_crop
                    )
                    
                    db.execute(query, params)
                    migrated += 1
                    
                    if migrated % 100 == 0:
                        print(f"  ✅ Migrated {migrated} detections...")
                
                except Exception as e:
                    skipped += 1
                    if skipped <= 5:  # Only show first 5 errors
                        print(f"  ⚠️ Skipped row: {e}")
        
        print(f"✅ Migrated {migrated} detections successfully")
        if skipped > 0:
            print(f"⚠️ Skipped {skipped} detections due to errors")
        
        return migrated
        
    except Exception as e:
        print(f"❌ Error migrating CSV: {e}")
        return 0


def migrate_json_to_mysql(json_file='allowed_plates.json'):
    """Migrate allowed plates from JSON to MySQL"""
    if not os.path.exists(json_file):
        print(f"⚠️ JSON file not found: {json_file}")
        return 0
    
    print(f"📄 Reading allowed plates from {json_file}...")
    
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        plates = data.get('allowed_plates', [])
        
        if not plates:
            print("⚠️ No plates found in JSON file")
            return 0
        
        print(f"📊 Found {len(plates)} plates to migrate...")
        
        migrated = 0
        skipped = 0
        
        with DatabaseConnection() as db:
            for plate in plates:
                try:
                    clean_plate = plate.strip().upper()
                    if clean_plate:
                        # Use INSERT IGNORE to skip duplicates
                        db.execute(
                            "INSERT IGNORE INTO allowed_plates (license_plate) VALUES (%s)",
                            (clean_plate,)
                        )
                        if db.cursor.rowcount > 0:
                            migrated += 1
                        else:
                            skipped += 1
                except Exception as e:
                    skipped += 1
                    if skipped <= 5:
                        print(f"  ⚠️ Skipped plate {plate}: {e}")
        
        print(f"✅ Migrated {migrated} plates successfully")
        if skipped > 0:
            print(f"ℹ️ {skipped} plates were already in database or had errors")
        
        return migrated
        
    except Exception as e:
        print(f"❌ Error migrating JSON: {e}")
        return 0


def main():
    """Main migration function"""
    print("=" * 60)
    print("🔄 ANPR System: CSV/JSON to MySQL Migration")
    print("=" * 60)
    print()
    
    # Test database connection
    print("🔌 Testing database connection...")
    if not test_connection():
        print("❌ Database connection failed!")
        print("\nPlease ensure:")
        print("1. XAMPP MySQL is running")
        print("2. Database 'anpr_system' exists")
        print("3. User credentials are correct")
        print("\nYou can create the database with:")
        print("  CREATE DATABASE anpr_system CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
        return
    
    print("✅ Database connection successful!")
    print()
    
    # Initialize database (create tables)
    print("📋 Initializing database tables...")
    if initialize_database():
        print("✅ Database tables initialized")
    else:
        print("⚠️ Database initialization had some issues (tables may already exist)")
    print()
    
    # Ask user for confirmation
    print("This will migrate data from CSV and JSON files to MySQL.")
    print("Existing data in MySQL will be preserved (duplicates will be skipped).")
    response = input("Continue? (y/n): ").strip().lower()
    
    if response != 'y':
        print("Migration cancelled.")
        return
    
    print()
    
    # Migrate CSV
    csv_file = 'plate_detections.csv'
    if os.path.exists(csv_file):
        migrate_csv_to_mysql(csv_file)
        print()
    else:
        print(f"⚠️ CSV file not found: {csv_file}")
        print()
    
    # Migrate JSON
    json_file = 'allowed_plates.json'
    if os.path.exists(json_file):
        migrate_json_to_mysql(json_file)
        print()
    else:
        print(f"⚠️ JSON file not found: {json_file}")
        print()
    
    print("=" * 60)
    print("✅ Migration completed!")
    print("=" * 60)
    print()
    print("📝 Next steps:")
    print("1. Verify data in MySQL database")
    print("2. Test the ANPR system with MySQL")
    print("3. Once confirmed working, you can backup/remove old CSV/JSON files")
    print()


if __name__ == "__main__":
    main()

