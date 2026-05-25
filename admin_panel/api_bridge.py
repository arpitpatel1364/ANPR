"""
ANPR API Bridge Module
Provides REST API endpoints for real-time communication with ANPR system
"""

import json
import os
import sys
import subprocess
import time
import psutil
import requests
from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request
from typing import Dict, List, Optional, Any
import threading
import queue

# Add parent directory to path for db_connection import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db_connection import DatabaseConnection
from plate_logger import PlateLogger

api_bridge_bp = Blueprint('api_bridge', __name__)

class ANPRSystemMonitor:
    """Monitor ANPR system status and performance"""
    
    def __init__(self):
        self.anpr_process = None
        self.last_detection_time = None
        self.detection_queue = queue.Queue()
        self.system_stats = {
            'cpu_usage': 0,
            'memory_usage': 0,
            'gpu_usage': 0,
            'last_update': None
        }
        self.camera_status = {}
        self.start_monitoring()
    
    def start_monitoring(self):
        """Start background monitoring thread"""
        monitor_thread = threading.Thread(target=self._monitor_system, daemon=True)
        monitor_thread.start()
    
    def _monitor_system(self):
        """Background system monitoring"""
        while True:
            try:
                # Update system stats
                self.system_stats.update({
                    'cpu_usage': psutil.cpu_percent(interval=1),
                    'memory_usage': psutil.virtual_memory().percent,
                    'last_update': datetime.now().isoformat()
                })
                
                # Check ANPR process
                self._check_anpr_process()
                
                # Check camera status
                self._check_camera_status()
                
                time.sleep(5)  # Update every 5 seconds
                
            except Exception as e:
                print(f"Error in system monitoring: {e}")
                time.sleep(10)
    
    def _check_anpr_process(self):
        """Check if ANPR system process is running"""
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if proc.info['cmdline'] and 'app_multi_camera.py' in ' '.join(proc.info['cmdline']):
                        self.anpr_process = proc
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            self.anpr_process = None
            return False
            
        except Exception as e:
            print(f"Error checking ANPR process: {e}")
            return False
    
    def _check_camera_status(self):
        """Check camera connection status"""
        try:
            config_path = '../config.json'
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    config = json.load(f)
                
                cameras = config.get('cameras', [])
                for camera in cameras:
                    camera_id = camera['id']
                    self.camera_status[camera_id] = {
                        'name': camera['name'],
                        'location': camera['location'],
                        'enabled': camera['enabled'],
                        'rtsp_source': camera['rtsp_source'],
                        'last_check': datetime.now().isoformat(),
                        'status': 'unknown'  # Will be updated by actual connection test
                    }
        except Exception as e:
            print(f"Error checking camera status: {e}")
    
    def get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status"""
        is_running = self.anpr_process is not None and self.anpr_process.is_running()
        
        return {
            'anpr_service': {
                'running': is_running,
                'pid': self.anpr_process.pid if self.anpr_process else None,
                'uptime': self._get_process_uptime() if is_running else 0
            },
            'system_stats': self.system_stats,
            'cameras': self.camera_status,
            'last_detection': self.last_detection_time,
            'timestamp': datetime.now().isoformat()
        }
    
    def _get_process_uptime(self) -> float:
        """Get process uptime in seconds"""
        try:
            if self.anpr_process:
                return time.time() - self.anpr_process.create_time()
        except:
            pass
        return 0
    
    def get_recent_detections(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent detections from MySQL"""
        try:
            with DatabaseConnection() as db:
                query = """
                    SELECT timestamp, license_plate, camera_source, detection_confidence,
                           verification_status, access_granted, frame_number
                    FROM detections
                    ORDER BY timestamp DESC
                    LIMIT %s
                """
                db.execute(query, (limit,))
                rows = db.fetchall()
                
                detections = []
                for row in rows:
                    detections.append({
                        'timestamp': row['timestamp'].isoformat() if row['timestamp'] else '',
                        'plate': row['license_plate'],
                        'camera': row['camera_source'],
                        'confidence': float(row['detection_confidence']),
                        'verification_status': row['verification_status'],
                        'access_granted': row['access_granted'],
                        'frame_number': row['frame_number']
                    })
                
                return detections  # Already ordered newest first
            
        except Exception as e:
            print(f"Error getting recent detections: {e}")
            return []
    
    def get_camera_stats(self) -> Dict[str, Any]:
        """Get camera statistics"""
        try:
            config_path = '../config.json'
            if not os.path.exists(config_path):
                return {}
            
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            cameras = config.get('cameras', [])
            total_cameras = len(cameras)
            enabled_cameras = len([c for c in cameras if c.get('enabled', False)])
            
            return {
                'total_cameras': total_cameras,
                'enabled_cameras': enabled_cameras,
                'disabled_cameras': total_cameras - enabled_cameras,
                'cameras': [
                    {
                        'id': cam['id'],
                        'name': cam['name'],
                        'location': cam['location'],
                        'enabled': cam.get('enabled', False),
                        'api_enabled': cam.get('api_enabled', False)
                    }
                    for cam in cameras
                ]
            }
            
        except Exception as e:
            print(f"Error getting camera stats: {e}")
            return {}

    def get_total_detections(self) -> int:
        """Get total number of detections"""
        try:
            with DatabaseConnection() as db:
                db.execute("SELECT COUNT(*) as count FROM detections")
                result = db.fetchone()
                return result['count'] if result else 0
        except Exception as e:
            print(f"Error getting total detections: {e}")
            return 0

    def get_verified_detections_count(self) -> int:
        """Get count of verified detections"""
        try:
            with DatabaseConnection() as db:
                db.execute("SELECT COUNT(*) as count FROM detections WHERE verification_status = 'VERIFIED'")
                result = db.fetchone()
                return result['count'] if result else 0
        except Exception as e:
            print(f"Error getting verified detections count: {e}")
            return 0

    def get_not_verified_detections_count(self) -> int:
        """Get count of not verified detections"""
        try:
            with DatabaseConnection() as db:
                db.execute("SELECT COUNT(*) as count FROM detections WHERE verification_status = 'NOT_VERIFIED'")
                result = db.fetchone()
                return result['count'] if result else 0
        except Exception as e:
            print(f"Error getting not verified detections count: {e}")
            return 0

    def get_detections_today(self) -> int:
        """Get detections count for today"""
        try:
            with DatabaseConnection() as db:
                today = datetime.now().date()
                db.execute("SELECT COUNT(*) as count FROM detections WHERE DATE(timestamp) = %s", (today,))
                result = db.fetchone()
                return result['count'] if result else 0
        except Exception as e:
            print(f"Error getting today's detections: {e}")
            return 0

    def get_detections_this_week(self) -> int:
        """Get detections count for this week"""
        try:
            with DatabaseConnection() as db:
                today = datetime.now()
                start_of_week = today - timedelta(days=today.weekday())
                db.execute("SELECT COUNT(*) as count FROM detections WHERE DATE(timestamp) >= %s", (start_of_week.date(),))
                result = db.fetchone()
                return result['count'] if result else 0
        except Exception as e:
            print(f"Error getting this week's detections: {e}")
            return 0

    def get_detections_this_month(self) -> int:
        """Get detections count for this month"""
        try:
            with DatabaseConnection() as db:
                this_month = datetime.now().strftime('%Y-%m')
                db.execute("SELECT COUNT(*) as count FROM detections WHERE DATE_FORMAT(timestamp, '%%Y-%%m') = %s", (this_month,))
                result = db.fetchone()
                return result['count'] if result else 0
        except Exception as e:
            print(f"Error getting this month's detections: {e}")
            return 0

    def get_last_detection_time(self) -> str:
        """Get timestamp of last detection"""
        try:
            with DatabaseConnection() as db:
                db.execute("SELECT timestamp FROM detections ORDER BY timestamp DESC LIMIT 1")
                result = db.fetchone()
                if result and result['timestamp']:
                    return result['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
                return 'Never'
        except Exception as e:
            print(f"Error getting last detection time: {e}")
            return 'Unknown'

# Global monitor instance
monitor = ANPRSystemMonitor()

# API Routes
@api_bridge_bp.route('/api/system/status')
def get_system_status():
    """Get real-time system status"""
    try:
        status = monitor.get_system_status()
        
        # Add camera counts to status
        camera_stats = monitor.get_camera_stats()
        if camera_stats:
            status['enabled_cameras'] = camera_stats.get('enabled_cameras', 0)
            status['total_cameras'] = camera_stats.get('total_cameras', 0)
            status['active_cameras'] = camera_stats.get('enabled_cameras', 0)  # For now, enabled = active
        
        return jsonify({
            'success': True,
            'data': status
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@api_bridge_bp.route('/api/detections/recent')
def get_recent_detections():
    """Get recent detections"""
    try:
        limit = request.args.get('limit', 50, type=int)
        detections = monitor.get_recent_detections(limit)
        return jsonify({
            'success': True,
            'data': detections,
            'count': len(detections)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@api_bridge_bp.route('/api/detections/stats')
def get_detection_stats():
    """Get detection statistics"""
    try:
        stats = {
            'total_detections': monitor.get_total_detections(),
            'verified_detections': monitor.get_verified_detections_count(),
            'not_verified_detections': monitor.get_not_verified_detections_count(),
            'last_detection_time': monitor.get_last_detection_time(),
            'detections_today': monitor.get_detections_today(),
            'detections_this_week': monitor.get_detections_this_week(),
            'detections_this_month': monitor.get_detections_this_month()
        }
        
        return jsonify({
            'success': True,
            'data': stats
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@api_bridge_bp.route('/api/cameras/stats')
def get_camera_stats():
    """Get camera statistics"""
    try:
        stats = monitor.get_camera_stats()
        return jsonify({
            'success': True,
            'data': stats
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@api_bridge_bp.route('/api/service/control', methods=['POST'])
def control_service():
    """Control ANPR service (start/stop/restart)"""
    try:
        action = request.json.get('action')
        
        if action not in ['start', 'stop', 'restart', 'status']:
            return jsonify({
                'success': False,
                'error': 'Invalid action. Use: start, stop, restart, status'
            }), 400
        
        if action == 'status':
            is_running = monitor.anpr_process is not None and monitor.anpr_process.is_running()
            return jsonify({
                'success': True,
                'data': {
                    'running': is_running,
                    'pid': monitor.anpr_process.pid if monitor.anpr_process else None
                }
            })
        
        # Execute manage_service script
        manage_service_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'manage_service.sh'
        )
        result = subprocess.run([
            'sudo', manage_service_path, action
        ], capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            return jsonify({
                'success': True,
                'message': f'ANPR service {action}ed successfully',
                'data': {
                    'action': action,
                    'timestamp': datetime.now().isoformat()
                }
            })
        else:
            return jsonify({
                'success': False,
                'error': f'Failed to {action} service: {result.stderr}'
            }), 500
            
    except subprocess.TimeoutExpired:
        return jsonify({
            'success': False,
            'error': 'Service control operation timed out'
        }), 500
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@api_bridge_bp.route('/api/plates/reload', methods=['POST'])
def reload_plates():
    """
    Reload allowed plates from database.
    This endpoint triggers a reload of the allowed plates list.
    The ANPR service also auto-reloads plates every 60 seconds for live updates.
    """
    try:
        # Create a temporary PlateLogger instance to reload from database
        temp_logger = PlateLogger(allowed_plates_file="allowed_plates.json")
        
        # Verify that plates were loaded
        plates_count = len(temp_logger.allowed_plates)
        
        return jsonify({
            'success': True,
            'message': f'Plates reloaded successfully from database',
            'plates_count': plates_count,
            'plates': list(temp_logger.allowed_plates),
            'timestamp': datetime.now().isoformat()
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error reloading plates: {str(e)}',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@api_bridge_bp.route('/api/health')
def health_check():
    """Health check endpoint"""
    try:
        status = monitor.get_system_status()
        return jsonify({
            'success': True,
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'anpr_running': status['anpr_service']['running']
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'status': 'unhealthy',
            'error': str(e)
        }), 500
