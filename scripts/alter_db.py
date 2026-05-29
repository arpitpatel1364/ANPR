import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db_connection import DatabaseConnection

with DatabaseConnection() as db:
    try:
        db.execute("ALTER TABLE detections ADD COLUMN bbox_x1 INT DEFAULT NULL")
        print("Added bbox_x1")
    except Exception as e:
        print(f"bbox_x1 error: {e}")
    try:
        db.execute("ALTER TABLE detections ADD COLUMN bbox_y1 INT DEFAULT NULL")
        print("Added bbox_y1")
    except Exception as e:
        print(f"bbox_y1 error: {e}")
    try:
        db.execute("ALTER TABLE detections ADD COLUMN bbox_x2 INT DEFAULT NULL")
        print("Added bbox_x2")
    except Exception as e:
        print(f"bbox_x2 error: {e}")
    try:
        db.execute("ALTER TABLE detections ADD COLUMN bbox_y2 INT DEFAULT NULL")
        print("Added bbox_y2")
    except Exception as e:
        print(f"bbox_y2 error: {e}")
