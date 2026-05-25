import json
import os
import time
from db_connection import DatabaseConnection

def load_config_from_db():
    """Load configuration from database to match the structure of config.json"""
    config = {
        'global_settings': {},
        'display_settings': {},
        'headless_settings': {},
        'cameras': []
    }
    
    try:
        with DatabaseConnection() as db:
            # 1. Load settings
            db.execute("SELECT setting_key, setting_value FROM system_settings")
            settings = db.fetchall()
            for row in settings:
                key = row['setting_key']
                val = row['setting_value']
                
                try:
                    # Attempt to parse as JSON, otherwise keep as string
                    parsed_val = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    parsed_val = val
                
                if key in config:
                    config[key] = parsed_val
                else:
                    config[key] = parsed_val
            
            # 2. Load cameras
            db.execute("SELECT * FROM cameras ORDER BY id")
            cameras = db.fetchall()
            for cam in cameras:
                cam_obj = {
                    "id": cam['camera_id'],
                    "name": cam['name'],
                    "location": cam['location'],
                    "rtsp_source": int(cam['rtsp_source']) if str(cam['rtsp_source']).isdigit() else cam['rtsp_source'],
                    "dedup_window": cam['dedup_window'],
                    "confidence_threshold": float(cam['confidence_threshold']) if cam['confidence_threshold'] else 0.8,
                    "enabled": bool(cam['enabled']),
                    "api_enabled": bool(cam['api_enabled'])
                }
                
                try:
                    cam_obj['api_settings'] = json.loads(cam['api_settings']) if cam['api_settings'] else {}
                except json.JSONDecodeError:
                    cam_obj['api_settings'] = {}
                
                try:
                    cam_obj['roi_polygon'] = json.loads(cam['roi_polygon']) if cam['roi_polygon'] else []
                except json.JSONDecodeError:
                    cam_obj['roi_polygon'] = []
                
                try:
                    cam_obj['roi'] = json.loads(cam['roi']) if cam.get('roi') else None
                except json.JSONDecodeError:
                    cam_obj['roi'] = None
                
                config['cameras'].append(cam_obj)
                
        print("✅ Configuration loaded from Database")
        return config
    except Exception as e:
        print(f"❌ Error loading config from DB: {e}")
        return None

def trigger_hot_reload():
    """Touch the reload_trigger.txt file to notify backend processes to reload config."""
    trigger_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reload_trigger.txt')
    try:
        with open(trigger_file, 'a'):
            os.utime(trigger_file, None)
        print("🔄 Triggered hot reload (touched reload_trigger.txt)")
    except Exception as e:
        print(f"❌ Error triggering hot reload: {e}")

def save_setting_to_db(key, value):
    """Save a specific setting to the system_settings table"""
    try:
        with DatabaseConnection() as db:
            val_str = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
            db.execute(
                "INSERT INTO system_settings (setting_key, setting_value) VALUES (%s, %s) ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)",
                (key, val_str)
            )
            return True
    except Exception as e:
        print(f"Error saving setting {key}: {e}")
        return False

def save_settings_to_db(settings_dict):
    """Save multiple settings to the system_settings table"""
    try:
        with DatabaseConnection() as db:
            for key, value in settings_dict.items():
                val_str = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
                db.execute(
                    "INSERT INTO system_settings (setting_key, setting_value) VALUES (%s, %s) ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)",
                    (key, val_str)
                )
        trigger_hot_reload()
        return True
    except Exception as e:
        print(f"Error saving settings: {e}")
        return False

def add_camera_to_db(camera_data):
    """Add a new camera to the database"""
    try:
        with DatabaseConnection() as db:
            api_settings = json.dumps(camera_data.get('api_settings', {}))
            roi_polygon = json.dumps(camera_data.get('roi_polygon', []))
            roi = json.dumps(camera_data.get('roi', {})) if camera_data.get('roi') else None
            
            db.execute("""
                INSERT INTO cameras (camera_id, name, location, rtsp_source, enabled, dedup_window, confidence_threshold, api_enabled, api_settings, roi_polygon, roi)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                camera_data.get('id'), camera_data.get('name'), camera_data.get('location', ''), 
                camera_data.get('rtsp_source'), camera_data.get('enabled', True), 
                camera_data.get('dedup_window', 30), camera_data.get('confidence_threshold', 0.8),
                camera_data.get('api_enabled', False), api_settings, roi_polygon, roi
            ))
        trigger_hot_reload()
        return True
    except Exception as e:
        print(f"Error adding camera to DB: {e}")
        return False

def update_camera_in_db(camera_id, camera_data):
    """Update an existing camera in the database"""
    try:
        with DatabaseConnection() as db:
            api_settings = json.dumps(camera_data.get('api_settings', {}))
            
            # Prepare update fields and values dynamically
            update_fields = []
            values = []
            
            # Map of python keys to DB columns
            field_map = {
                'name': 'name',
                'location': 'location',
                'rtsp_source': 'rtsp_source',
                'enabled': 'enabled',
                'dedup_window': 'dedup_window',
                'confidence_threshold': 'confidence_threshold',
                'api_enabled': 'api_enabled'
            }
            
            for key, db_col in field_map.items():
                if key in camera_data:
                    update_fields.append(f"{db_col} = %s")
                    values.append(camera_data[key])
            
            # Handle JSON fields explicitly
            update_fields.append("api_settings = %s")
            values.append(api_settings)
            
            if 'roi_polygon' in camera_data:
                update_fields.append("roi_polygon = %s")
                values.append(json.dumps(camera_data['roi_polygon']))
            
            if 'roi' in camera_data:
                update_fields.append("roi = %s")
                values.append(json.dumps(camera_data['roi']) if camera_data['roi'] else None)
            
            # Append camera_id for WHERE clause
            values.append(camera_id)
            
            query = f"UPDATE cameras SET {', '.join(update_fields)} WHERE camera_id = %s"
            db.execute(query, tuple(values))
            
        trigger_hot_reload()
        return True
    except Exception as e:
        print(f"Error updating camera {camera_id}: {e}")
        return False

def delete_camera_from_db(camera_id):
    """Delete a camera from the database"""
    try:
        with DatabaseConnection() as db:
            db.execute("DELETE FROM cameras WHERE camera_id = %s", (camera_id,))
        trigger_hot_reload()
        return True
    except Exception as e:
        print(f"Error deleting camera {camera_id}: {e}")
        return False

def update_camera_status_in_db(camera_id, enabled):
    """Update just the enabled status of a camera"""
    try:
        with DatabaseConnection() as db:
            db.execute("UPDATE cameras SET enabled = %s WHERE camera_id = %s", (enabled, camera_id))
        trigger_hot_reload()
        return True
    except Exception as e:
        print(f"Error toggling camera status: {e}")
        return False
