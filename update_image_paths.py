#!/usr/bin/env python3
"""
Update Image Paths in Database
Updates image paths for detections that were migrated without them
"""

import csv
import os
from datetime import datetime
from db_connection import DatabaseConnection

def update_image_paths(csv_file='plate_detections.csv'):
    """Update image paths from CSV for detections missing them"""
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
        
        print(f"📊 Found {len(rows)} detections in CSV...")
        
        # Helper function to clean image path values
        def clean_image_path(value):
            if value is None:
                return None
            value_str = str(value).strip()
            if not value_str or value_str.lower() in ['nan', 'none', 'null', '']:
                return None
            return value_str
        
        updated = 0
        skipped = 0
        not_found = 0
        
        with DatabaseConnection() as db:
            for row in rows:
                try:
                    license_plate = row.get('License_Plate', '').strip()
                    timestamp_str = row.get('Timestamp', '')
                    
                    # Parse timestamp to match
                    try:
                        if '.' in timestamp_str:
                            timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S.%f')
                        else:
                            timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                    except:
                        timestamp = None
                    
                    # Get image paths from CSV
                    image_full_raw = clean_image_path(row.get('Image_Full_Raw'))
                    image_full_annotated = clean_image_path(row.get('Image_Full_Annotated'))
                    image_plate_crop = clean_image_path(row.get('Image_Plate_Crop'))
                    
                    # Skip if no image paths in CSV
                    if not (image_full_raw or image_full_annotated or image_plate_crop):
                        skipped += 1
                        continue
                    
                    # Find matching detection in database
                    if timestamp:
                        query = """
                            SELECT id FROM detections 
                            WHERE license_plate = %s AND timestamp = %s
                            LIMIT 1
                        """
                        db.execute(query, (license_plate, timestamp))
                    else:
                        query = """
                            SELECT id FROM detections 
                            WHERE license_plate = %s
                            ORDER BY timestamp DESC
                            LIMIT 1
                        """
                        db.execute(query, (license_plate,))
                    
                    result = db.fetchone()
                    
                    if not result:
                        not_found += 1
                        continue
                    
                    detection_id = result['id']
                    
                    # Check if this detection already has image paths
                    check_query = """
                        SELECT image_full_raw, image_full_annotated, image_plate_crop 
                        FROM detections 
                        WHERE id = %s
                    """
                    db.execute(check_query, (detection_id,))
                    existing = db.fetchone()
                    
                    # Only update if missing image paths
                    if existing and (not existing['image_full_raw'] or not existing['image_full_annotated'] or not existing['image_plate_crop']):
                        update_query = """
                            UPDATE detections 
                            SET image_full_raw = %s,
                                image_full_annotated = %s,
                                image_plate_crop = %s
                            WHERE id = %s
                        """
                        db.execute(update_query, (image_full_raw, image_full_annotated, image_plate_crop, detection_id))
                        updated += 1
                        
                        if updated % 10 == 0:
                            print(f"  ✅ Updated {updated} detections...")
                    else:
                        skipped += 1
                
                except Exception as e:
                    skipped += 1
                    if skipped <= 5:
                        print(f"  ⚠️ Skipped row: {e}")
        
        print(f"\n✅ Updated {updated} detections with image paths")
        print(f"⚠️ Skipped {skipped} detections (already have paths or no paths in CSV)")
        if not_found > 0:
            print(f"⚠️ {not_found} detections not found in database")
        
        return updated
        
    except Exception as e:
        print(f"❌ Error updating image paths: {e}")
        import traceback
        traceback.print_exc()
        return 0


def main():
    """Main function"""
    print("=" * 60)
    print("🔄 ANPR System: Update Image Paths")
    print("=" * 60)
    print()
    
    # Check current status
    print("📊 Checking current database status...")
    with DatabaseConnection() as db:
        db.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(image_full_raw) as with_raw,
                COUNT(image_full_annotated) as with_ann,
                COUNT(image_plate_crop) as with_crop
            FROM detections
        """)
        result = db.fetchone()
        print(f"  Total detections: {result['total']}")
        print(f"  With image_full_raw: {result['with_raw']}")
        print(f"  With image_full_annotated: {result['with_ann']}")
        print(f"  With image_plate_crop: {result['with_crop']}")
        print()
    
    # Ask for confirmation
    response = input("Update image paths from CSV? (y/n): ").strip().lower()
    
    if response != 'y':
        print("Update cancelled.")
        return
    
    print()
    
    # Update image paths
    updated = update_image_paths()
    
    print()
    print("=" * 60)
    if updated > 0:
        print(f"✅ Update completed! {updated} detections updated.")
    else:
        print("ℹ️ No updates needed - all detections already have image paths or CSV has no paths.")
    print("=" * 60)


if __name__ == "__main__":
    main()

