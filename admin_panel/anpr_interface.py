"""
ANPR Interface Module
Handles direct communication with ANPR system and configuration management
"""

import json
import os
import subprocess
import time
import threading
from datetime import datetime
from typing import Dict, List, Optional, Any
import requests
from urllib.parse import quote

class ANPRInterface:
    """Interface for ANPR system communication and control"""
    
    def __init__(self):
        self.config_path = None # Removed file based config
        self.allowed_plates_path = '../allowed_plates.json'
        self.detections_path = '../plate_detections.csv'
        self.service_name = 'anpr-multi-camera'
        self.config_lock = threading.Lock()
    
    def get_config(self) -> Dict[str, Any]:
        """Get current configuration"""
        try:
            import sys
            import os
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from scripts.config_db import load_config_from_db
            return load_config_from_db() or {}
        except Exception as e:
            print(f"Error reading config: {e}")
            return {}
    
    def save_config(self, config: Dict[str, Any]) -> bool:
        """Save configuration to file (DEPRECATED - use config_db functions directly)"""
        return True
    
    def get_allowed_plates(self) -> List[str]:
        """Get allowed plates list"""
        try:
            with open(self.allowed_plates_path, 'r') as f:
                data = json.load(f)
                return data.get('allowed_plates', [])
        except Exception as e:
            print(f"Error reading allowed plates: {e}")
            return []
    
    def save_allowed_plates(self, plates: List[str]) -> bool:
        """Save allowed plates list"""
        try:
            data = {
                'allowed_plates': plates,
                'last_updated': datetime.now().isoformat(),
                'count': len(plates)
            }
            
            with open(self.allowed_plates_path, 'w') as f:
                json.dump(data, f, indent=2)
            
            return True
        except Exception as e:
            print(f"Error saving allowed plates: {e}")
            return False
    
    def update_camera_config(self, camera_id: str, updates: Dict[str, Any]) -> bool:
        """Update specific camera configuration"""
        try:
            config = self.get_config()
            cameras = config.get('cameras', [])
            
            for camera in cameras:
                if camera['id'] == camera_id:
                    camera.update(updates)
                    camera['last_updated'] = datetime.now().isoformat()
                    break
            else:
                return False  # Camera not found
            
            return self.save_config(config)
        except Exception as e:
            print(f"Error updating camera config: {e}")
            return False
    
    def toggle_camera(self, camera_id: str) -> Dict[str, Any]:
        """Toggle camera enabled/disabled status"""
        try:
            import sys
            import os
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from scripts.config_db import load_config_from_db, update_camera_status_in_db
            
            config = load_config_from_db()
            cameras = config.get('cameras', []) if config else []
            
            for camera in cameras:
                if camera['id'] == camera_id:
                    old_status = camera.get('enabled', False)
                    new_status = not old_status
                    
                    if update_camera_status_in_db(camera_id, new_status):
                        return {
                            'success': True,
                            'camera_id': camera_id,
                            'name': camera['name'],
                            'enabled': new_status,
                            'previous_status': old_status
                        }
                    else:
                        return {
                            'success': False,
                            'error': 'Failed to save configuration'
                        }
            
            return {
                'success': False,
                'error': 'Camera not found'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def test_camera_connection(self, camera_id: str) -> Dict[str, Any]:
        """Test camera RTSP connection"""
        try:
            config = self.get_config()
            cameras = config.get('cameras', [])
            
            for camera in cameras:
                if camera['id'] == camera_id:
                    rtsp_source = camera.get('rtsp_source', '')
                    
                    # Simple RTSP connection test using ffprobe
                    try:
                        result = subprocess.run([
                            'ffprobe', '-v', 'quiet', '-print_format', 'json',
                            '-show_format', '-show_streams', rtsp_source
                        ], capture_output=True, text=True, timeout=10)
                        
                        if result.returncode == 0:
                            return {
                                'success': True,
                                'camera_id': camera_id,
                                'name': camera['name'],
                                'rtsp_source': rtsp_source,
                                'status': 'connected',
                                'response_time': 'N/A'  # Could be enhanced
                            }
                        else:
                            return {
                                'success': False,
                                'camera_id': camera_id,
                                'name': camera['name'],
                                'rtsp_source': rtsp_source,
                                'status': 'failed',
                                'error': result.stderr
                            }
                    except subprocess.TimeoutExpired:
                        return {
                            'success': False,
                            'camera_id': camera_id,
                            'name': camera['name'],
                            'rtsp_source': rtsp_source,
                            'status': 'timeout',
                            'error': 'Connection timeout'
                        }
            
            return {
                'success': False,
                'error': 'Camera not found'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_service_status(self) -> Dict[str, Any]:
        """Get systemd service status"""
        try:
            result = subprocess.run([
                'systemctl', 'is-active', self.service_name
            ], capture_output=True, text=True)
            
            is_active = result.stdout.strip() == 'active'
            
            # Get more detailed status
            status_result = subprocess.run([
                'systemctl', 'show', self.service_name, '--property=ActiveState,SubState,LoadState,UnitFileState'
            ], capture_output=True, text=True)
            
            status_info = {}
            for line in status_result.stdout.split('\n'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    status_info[key] = value
            
            return {
                'success': True,
                'active': is_active,
                'status': result.stdout.strip(),
                'details': status_info
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def restart_service(self) -> Dict[str, Any]:
        """Restart ANPR service"""
        try:
            result = subprocess.run([
                'sudo', 'systemctl', 'restart', self.service_name
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                return {
                    'success': True,
                    'message': 'Service restarted successfully',
                    'timestamp': datetime.now().isoformat()
                }
            else:
                return {
                    'success': False,
                    'error': result.stderr
                }
        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'error': 'Service restart timed out'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_detection_stats(self, hours: int = 24) -> Dict[str, Any]:
        """Get detection statistics for specified hours"""
        try:
            if not os.path.exists(self.detections_path):
                return {
                    'success': True,
                    'data': {
                        'total_detections': 0,
                        'verified_detections': 0,
                        'not_verified_detections': 0,
                        'time_range': f'Last {hours} hours',
                        'detections_per_hour': 0
                    }
                }
            
            cutoff_time = datetime.now() - timedelta(hours=hours)
            total_detections = 0
            verified_detections = 0
            not_verified_detections = 0
            
            with open(self.detections_path, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        timestamp_str = row.get('Timestamp', '')
                        if timestamp_str:
                            detection_time = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                            if detection_time >= cutoff_time:
                                total_detections += 1
                                
                                verification_status = row.get('Verification_Status', '')
                                if verification_status == 'VERIFIED':
                                    verified_detections += 1
                                else:
                                    not_verified_detections += 1
                    except:
                        continue
            
            detections_per_hour = total_detections / hours if hours > 0 else 0
            
            return {
                'success': True,
                'data': {
                    'total_detections': total_detections,
                    'verified_detections': verified_detections,
                    'not_verified_detections': not_verified_detections,
                    'time_range': f'Last {hours} hours',
                    'detections_per_hour': round(detections_per_hour, 2)
                }
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_live_logs(self, lines: int = 100) -> List[str]:
        """Get recent logs from ANPR system"""
        try:
            # Try to get logs from journalctl
            result = subprocess.run([
                'journalctl', '-u', self.service_name, '-n', str(lines), '--no-pager'
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                return result.stdout.split('\n')
            else:
                # Fallback to log file
                log_file = '../anpr_headless.log'
                if os.path.exists(log_file):
                    with open(log_file, 'r') as f:
                        all_lines = f.readlines()
                        return [line.strip() for line in all_lines[-lines:]]
                else:
                    return []
        except Exception as e:
            print(f"Error getting logs: {e}")
            return []

# Global interface instance
anpr_interface = ANPRInterface()
