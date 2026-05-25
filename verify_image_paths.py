#!/usr/bin/env python3
"""
Verify Image Paths in Database
Shows detailed status of image paths in the database
"""

from db_connection import DatabaseConnection

def verify_image_paths():
    """Verify image paths in database"""
    print("=" * 60)
    print("🔍 ANPR System: Image Paths Verification")
    print("=" * 60)
    print()
    
    with DatabaseConnection() as db:
        # Overall statistics
        db.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(image_full_raw) as with_raw,
                COUNT(image_full_annotated) as with_ann,
                COUNT(image_plate_crop) as with_crop,
                COUNT(CASE WHEN image_full_raw IS NOT NULL AND image_full_annotated IS NOT NULL AND image_plate_crop IS NOT NULL THEN 1 END) as with_all
            FROM detections
        """)
        stats = db.fetchone()
        
        print("📊 Overall Statistics:")
        print(f"  Total detections: {stats['total']}")
        print(f"  With image_full_raw: {stats['with_raw']} ({stats['with_raw']*100//stats['total'] if stats['total'] > 0 else 0}%)")
        print(f"  With image_full_annotated: {stats['with_ann']} ({stats['with_ann']*100//stats['total'] if stats['total'] > 0 else 0}%)")
        print(f"  With image_plate_crop: {stats['with_crop']} ({stats['with_crop']*100//stats['total'] if stats['total'] > 0 else 0}%)")
        print(f"  With all three images: {stats['with_all']} ({stats['with_all']*100//stats['total'] if stats['total'] > 0 else 0}%)")
        print()
        
        # Sample detections with images
        print("📸 Sample Detections WITH Image Paths:")
        db.execute("""
            SELECT license_plate, timestamp, 
                   image_full_raw, image_full_annotated, image_plate_crop
            FROM detections 
            WHERE image_full_raw IS NOT NULL 
            ORDER BY timestamp DESC 
            LIMIT 5
        """)
        rows_with = db.fetchall()
        
        if rows_with:
            for i, row in enumerate(rows_with, 1):
                print(f"  {i}. {row['license_plate']} ({row['timestamp']})")
                print(f"     Raw: {row['image_full_raw'][:60]}...")
                print(f"     Annotated: {row['image_full_annotated'][:60]}...")
                print(f"     Crop: {row['image_plate_crop'][:60]}...")
                print()
        else:
            print("  ⚠️ No detections with image paths found")
            print()
        
        # Sample detections without images
        print("❌ Sample Detections WITHOUT Image Paths:")
        db.execute("""
            SELECT license_plate, timestamp, verification_status
            FROM detections 
            WHERE image_full_raw IS NULL 
            ORDER BY timestamp DESC 
            LIMIT 5
        """)
        rows_without = db.fetchall()
        
        if rows_without:
            for i, row in enumerate(rows_without, 1):
                print(f"  {i}. {row['license_plate']} ({row['timestamp']}) - {row['verification_status']}")
            print()
        else:
            print("  ✅ All detections have image paths!")
            print()
        
        # Check for partial image paths
        print("⚠️ Detections with Partial Image Paths:")
        db.execute("""
            SELECT license_plate, timestamp,
                   CASE WHEN image_full_raw IS NULL THEN 'Missing Raw' ELSE '' END as missing_raw,
                   CASE WHEN image_full_annotated IS NULL THEN 'Missing Annotated' ELSE '' END as missing_ann,
                   CASE WHEN image_plate_crop IS NULL THEN 'Missing Crop' ELSE '' END as missing_crop
            FROM detections 
            WHERE (image_full_raw IS NULL AND (image_full_annotated IS NOT NULL OR image_plate_crop IS NOT NULL))
               OR (image_full_annotated IS NULL AND (image_full_raw IS NOT NULL OR image_plate_crop IS NOT NULL))
               OR (image_plate_crop IS NULL AND (image_full_raw IS NOT NULL OR image_full_annotated IS NOT NULL))
            LIMIT 5
        """)
        partial = db.fetchall()
        
        if partial:
            for i, row in enumerate(partial, 1):
                missing = [v for v in [row['missing_raw'], row['missing_ann'], row['missing_crop']] if v]
                print(f"  {i}. {row['license_plate']} ({row['timestamp']}) - {', '.join(missing)}")
            print()
        else:
            print("  ✅ No detections with partial image paths")
            print()
    
    print("=" * 60)
    print("✅ Verification complete!")
    print("=" * 60)

if __name__ == "__main__":
    verify_image_paths()

