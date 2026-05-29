import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db_connection import DatabaseConnection

with DatabaseConnection() as db:
    for col in ["api_settings", "roi_polygon", "roi"]:
        try:
            db.execute(f"ALTER TABLE cameras ADD COLUMN {col} JSON DEFAULT NULL")
            print(f"Added {col}")
        except Exception as e:
            print(f"{col} error: {e}")
