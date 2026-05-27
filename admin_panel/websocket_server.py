"""
WebSocket Server for Real-Time Communication
Handles real-time updates between admin panel and ANPR system
"""

import json
import time
import threading
import queue
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Set, Any
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask import request

# Add parent directory to path for db_connection import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db_connection import DatabaseConnection

class WebSocketManager:
    """Manages WebSocket connections and real-time updates"""
    
    def __init__(self, socketio: SocketIO):
        self.socketio = socketio
        self.connected_clients: Set[str] = set()
        self.rooms = {
            'dashboard': set(),
            'detections': set(),
            'cameras': set(),
            'system': set()
        }
        self.update_queue = queue.Queue()
        self.running = False
        self.last_detection_time = None
        self.last_detection_count = 0
        
        # Start background update thread
        self.start_update_thread()
    
    def start_update_thread(self):
        """Start background thread for sending updates"""
        self.running = True
        update_thread = threading.Thread(target=self._update_loop, daemon=True)
        update_thread.start()
    
    def _update_loop(self):
        """Background loop for sending real-time updates"""
        while self.running:
            try:
                # Check for new detections
                self._check_new_detections()
                
                # Send system status updates
                self._send_system_status()
                
                # Send camera status updates
                self._send_camera_status()
                
                time.sleep(2)  # Update every 2 seconds
                
            except Exception as e:
                print(f"Error in WebSocket update loop: {e}")
                time.sleep(5)
    
    def _check_new_detections(self):
        """Check for new detections and broadcast to clients"""
        try:
            with DatabaseConnection() as db:
                # Count current detections
                db.execute("SELECT COUNT(*) as count FROM detections")
                result = db.fetchone()
                current_count = result['count'] if result else 0
                
                # If count increased, get new detections
                if current_count > self.last_detection_count:
                    new_detections = self._get_recent_detections(5)  # Get last 5
                    
                    if new_detections:
                        # broadcast to ALL rooms (not just 'detections'),
                        # so Dashboard users also receive real-time updates
                        self.socketio.emit('new_detections', {
                            'detections': new_detections,
                            'count': current_count,
                            'timestamp': datetime.now().isoformat()
                        }, broadcast=True)
                        
                        # Also send to dashboard
                        self.socketio.emit('detection_update', {
                            'new_count': current_count - self.last_detection_count,
                            'total_count': current_count,
                            'latest_detection': new_detections[0] if new_detections else None
                        }, room='dashboard')
                    
                    self.last_detection_count = current_count
                    self.last_detection_time = datetime.now().isoformat()
                
        except Exception as e:
            print(f"Error checking new detections: {e}")
    
    def _get_recent_detections(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get recent detections from MySQL"""
        try:
            with DatabaseConnection() as db:
                query = """
                    SELECT timestamp, license_plate, camera_source, detection_confidence,
                           verification_status, access_granted, frame_number,
                           image_full_annotated, bbox_x1, bbox_y1, bbox_x2, bbox_y2
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
                        'frame_number': row['frame_number'],
                        # include image paths and bounding boxes
                        'image_full_annotated': row['image_full_annotated'] or '',
                        'bbox_x1': row['bbox_x1'],
                        'bbox_y1': row['bbox_y1'],
                        'bbox_x2': row['bbox_x2'],
                        'bbox_y2': row['bbox_y2']
                    })
                
                return detections  # Already ordered newest first
            
        except Exception as e:
            print(f"Error getting recent detections: {e}")
            return []
    
    def _send_system_status(self):
        """Send system status updates"""
        try:
            # Get system status (simplified for now)
            status = {
                'timestamp': datetime.now().isoformat(),
                'anpr_running': self._check_anpr_running(),
                'detection_count': self.last_detection_count,
                'last_detection': self.last_detection_time if self.last_detection_time else None
            }
            
            self.socketio.emit('system_status', status, room='system')
            self.socketio.emit('system_status', status, room='dashboard')
            
        except Exception as e:
            print(f"Error sending system status: {e}")
    
    def _check_anpr_running(self) -> bool:
        """Check if ANPR system is running"""
        try:
            import psutil
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if proc.info['cmdline'] and 'app_multi_camera_lprnet.py' in ' '.join(proc.info['cmdline']):
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            return False
        except:
            return False
    
    def _send_camera_status(self):
        """Send enhanced camera status updates with real-time monitoring"""
        try:
            config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')
            if not os.path.exists(config_path):
                return
            
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            cameras = config.get('cameras', [])
            camera_status = []
            
            for camera in cameras:
                # Test camera connection in real-time
                connection_status = self._test_camera_connection(camera)
                
                camera_status.append({
                    'id': camera['id'],
                    'name': camera['name'],
                    'location': camera['location'],
                    'rtsp_source': camera.get('rtsp_source', ''),
                    'enabled': camera.get('enabled', False),
                    'api_enabled': camera.get('api_enabled', False),
                    'connection_status': connection_status['status'],
                    'connection_quality': connection_status['quality'],
                    'last_checked': datetime.now().isoformat(),
                    'error_message': connection_status.get('error', ''),
                    'response_time': connection_status.get('response_time', 0)
                })
            
            self.socketio.emit('camera_status', {
                'cameras': camera_status,
                'timestamp': datetime.now().isoformat(),
                'total_cameras': len(cameras),
                'active_cameras': len([c for c in camera_status if c['connection_status'] == 'connected']),
                'enabled_cameras': len([c for c in camera_status if c['enabled']])
            }, room='cameras')
            
        except Exception as e:
            print(f"Error sending camera status: {e}")
    
    def _test_camera_connection(self, camera):
        """Test camera RTSP connection and return status"""
        try:
            rtsp_source = camera.get('rtsp_source', '')
            if not rtsp_source:
                return {
                    'status': 'no_source',
                    'quality': 'unknown',
                    'error': 'No RTSP source configured'
                }
            
            # Test connection using ffprobe
            import subprocess
            import time
            
            start_time = time.time()
            result = subprocess.run([
                'ffprobe', '-v', 'quiet', '-print_format', 'json', 
                '-show_streams', '-timeout', '5000000',  # 5 second timeout in microseconds
                rtsp_source
            ], capture_output=True, text=True, timeout=5)
            
            response_time = round((time.time() - start_time) * 1000, 2)  # Convert to milliseconds
            
            if result.returncode == 0:
                # Parse stream info to determine quality
                try:
                    import json
                    stream_info = json.loads(result.stdout)
                    streams = stream_info.get('streams', [])
                    
                    # Determine connection quality based on response time and stream info
                    if response_time < 1000:  # Less than 1 second
                        quality = 'excellent'
                    elif response_time < 3000:  # Less than 3 seconds
                        quality = 'good'
                    elif response_time < 5000:  # Less than 5 seconds
                        quality = 'fair'
                    else:
                        quality = 'poor'
                    
                    return {
                        'status': 'connected',
                        'quality': quality,
                        'response_time': response_time,
                        'streams_found': len(streams)
                    }
                except:
                    return {
                        'status': 'connected',
                        'quality': 'unknown',
                        'response_time': response_time
                    }
            else:
                return {
                    'status': 'disconnected',
                    'quality': 'none',
                    'error': result.stderr.strip() or 'Connection failed',
                    'response_time': response_time
                }
                
        except subprocess.TimeoutExpired:
            return {
                'status': 'timeout',
                'quality': 'none',
                'error': 'Connection timeout (5s)',
                'response_time': 5000
            }
        except FileNotFoundError:
            return {
                'status': 'no_ffprobe',
                'quality': 'unknown',
                'error': 'ffprobe not available for testing'
            }
        except Exception as e:
            return {
                'status': 'error',
                'quality': 'none',
                'error': str(e)
            }
    
    def add_client(self, client_id: str, room: str = 'dashboard'):
        """Add client to room"""
        self.connected_clients.add(client_id)
        if room in self.rooms:
            self.rooms[room].add(client_id)
    
    def remove_client(self, client_id: str):
        """Remove client from all rooms"""
        self.connected_clients.discard(client_id)
        for room_clients in self.rooms.values():
            room_clients.discard(client_id)
    
    def _get_detections_today(self) -> int:
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
    
    def _get_detections_this_week(self) -> int:
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
    
    def _get_detections_this_month(self) -> int:
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
    
    def stop(self):
        """Stop the WebSocket manager"""
        self.running = False

# WebSocket event handlers
def register_websocket_events(socketio: SocketIO):
    """Register WebSocket event handlers"""
    
    ws_manager = WebSocketManager(socketio)
    
    @socketio.on('connect')
    def handle_connect():
        """Handle client connection"""
        try:
            client_id = request.sid
            print(f"Client connected: {client_id}")
            emit('connected', {'message': 'Connected to ANPR Admin Panel'})
        except Exception as e:
            print(f"❌ Error in connect handler: {e}")
            # Don't emit on error to avoid WSGI issues
    
    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle client disconnection"""
        try:
            client_id = request.sid
            ws_manager.remove_client(client_id)
            print(f"Client disconnected: {client_id}")
        except Exception as e:
            print(f"❌ Error in disconnect handler: {e}")
    
    @socketio.on('join_room')
    def handle_join_room(data):
        """Handle joining a specific room"""
        client_id = request.sid
        room = data.get('room', 'dashboard')
        
        if room in ws_manager.rooms:
            join_room(room)
            ws_manager.add_client(client_id, room)
            emit('joined_room', {'room': room})
            print(f"Client {client_id} joined room: {room}")
    
    @socketio.on('leave_room')
    def handle_leave_room(data):
        """Handle leaving a specific room"""
        client_id = request.sid
        room = data.get('room', 'dashboard')
        
        if room in ws_manager.rooms:
            leave_room(room)
            ws_manager.rooms[room].discard(client_id)
            emit('left_room', {'room': room})
            print(f"Client {client_id} left room: {room}")
    
    @socketio.on('request_update')
    def handle_request_update(data):
        """Handle client requesting specific update"""
        update_type = data.get('type', 'all')
        client_id = request.sid
        
        if update_type == 'detections':
            detections = ws_manager._get_recent_detections(10)
            emit('detections_update', {
                'detections': detections,
                'timestamp': datetime.now().isoformat()
            })
        elif update_type == 'system':
            status = {
                'timestamp': datetime.now().isoformat(),
                'anpr_running': ws_manager._check_anpr_running(),
                'detection_count': ws_manager.last_detection_count
            }
            emit('system_update', status)
        elif update_type == 'cameras':
            ws_manager._send_camera_status()
        else:
            # Send all updates
            ws_manager._send_system_status()
            ws_manager._send_camera_status()
    
    @socketio.on('ping')
    def handle_ping(data=None):
        """Handle ping from client for health check"""
        try:
            client_id = request.sid
            timestamp = data.get('timestamp', time.time()) if data else time.time()
            
            # Send pong response
            emit('pong', {
                'timestamp': timestamp,
                'server_time': datetime.now().isoformat(),
                'client_id': client_id
            })
            
            print(f"🏓 Ping received from {client_id}")
        except Exception as e:
            print(f"❌ Error handling ping: {e}")
            emit('pong', {'error': str(e)})
    
    @socketio.on('anpr_detection')
    def handle_anpr_detection(data):
        """Handle detection event from ANPR system"""
        try:
            print(f"📡 Received ANPR detection: {data.get('plate', 'unknown')}")
            
            # Broadcast to all connected clients
            emit('new_detections', {
                'detections': [data],
                'count': 1,
                'timestamp': datetime.now().isoformat()
            }, broadcast=True)
            
            # Also send to specific rooms
            emit('detection_update', {
                'total_detections': ws_manager.last_detection_count + 1,
                'verified_detections': 1 if data.get('verification_status') == 'VERIFIED' else 0,
                'not_verified_detections': 1 if data.get('verification_status') != 'VERIFIED' else 0,
                'last_detection_time': data.get('timestamp'),
                'detections_today': ws_manager._get_detections_today(),
                'detections_this_week': ws_manager._get_detections_this_week(),
                'detections_this_month': ws_manager._get_detections_this_month()
            }, room='dashboard')
            
            # Update detection count
            ws_manager.last_detection_count += 1
            timestamp = data.get('timestamp')
            if timestamp:
                # Ensure timestamp is a string (ISO format)
                if hasattr(timestamp, 'isoformat'):
                    ws_manager.last_detection_time = timestamp.isoformat()
                else:
                    ws_manager.last_detection_time = str(timestamp)
            else:
                ws_manager.last_detection_time = datetime.now().isoformat()
            
        except Exception as e:
            print(f"❌ Error handling ANPR detection: {e}")
    
    @socketio.on('anpr_system_status')
    def handle_anpr_system_status(data):
        """Handle system status update from ANPR system"""
        try:
            print(f"📡 Received ANPR system status update")
            
            # Broadcast to all connected clients
            emit('system_status', {
                'anpr_running': True,
                'last_detection': data.get('timestamp'),
                'detection_count': ws_manager.last_detection_count,
                'timestamp': datetime.now().isoformat()
            }, broadcast=True)
            
        except Exception as e:
            print(f"❌ Error handling ANPR system status: {e}")
    
    @socketio.on('anpr_camera_status')
    def handle_anpr_camera_status(data):
        """Handle camera status update from ANPR system"""
        try:
            print(f"📡 Received ANPR camera status: {data.get('camera_id', 'unknown')}")
            
            # Broadcast to all connected clients
            emit('camera_status', {
                'cameras': [data],
                'timestamp': datetime.now().isoformat()
            }, broadcast=True)
            
        except Exception as e:
            print(f"❌ Error handling ANPR camera status: {e}")
    
    @socketio.on('camera_toggle')
    def handle_camera_toggle(data):
        """Handle camera enable/disable toggle"""
        try:
            camera_id = data.get('camera_id')
            enabled = data.get('enabled', False)
            
            if not camera_id:
                emit('camera_toggle_result', {
                    'success': False,
                    'error': 'Camera ID required'
                })
                return
            
            # Load current config
            config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')
            if not os.path.exists(config_path):
                emit('camera_toggle_result', {
                    'success': False,
                    'error': 'Config file not found'
                })
                return
            
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            # Find and update camera
            cameras = config.get('cameras', [])
            camera_found = False
            
            for camera in cameras:
                if camera['id'] == camera_id:
                    camera['enabled'] = enabled
                    camera_found = True
                    break
            
            if not camera_found:
                emit('camera_toggle_result', {
                    'success': False,
                    'error': 'Camera not found'
                })
                return
            
            # Save updated config
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=2)
            
            # Broadcast updated camera status
            ws_manager._send_camera_status()
            
            # Send confirmation
            emit('camera_toggle_result', {
                'success': True,
                'camera_id': camera_id,
                'enabled': enabled,
                'message': f'Camera {"enabled" if enabled else "disabled"} successfully'
            })
            
            print(f"📹 Camera {camera_id} {'enabled' if enabled else 'disabled'} by client {request.sid}")
            
        except Exception as e:
            print(f"❌ Error toggling camera: {e}")
            emit('camera_toggle_result', {
                'success': False,
                'error': str(e)
            })
    
    @socketio.on('camera_test')
    def handle_camera_test(data):
        """Handle camera connection test"""
        try:
            camera_id = data.get('camera_id')
            
            if not camera_id:
                emit('camera_test_result', {
                    'success': False,
                    'error': 'Camera ID required'
                })
                return
            
            # Load camera config
            config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')
            if not os.path.exists(config_path):
                emit('camera_test_result', {
                    'success': False,
                    'error': 'Config file not found'
                })
                return
            
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            # Find camera
            cameras = config.get('cameras', [])
            camera = None
            
            for cam in cameras:
                if cam['id'] == camera_id:
                    camera = cam
                    break
            
            if not camera:
                emit('camera_test_result', {
                    'success': False,
                    'error': 'Camera not found'
                })
                return
            
            # Test camera connection
            connection_status = ws_manager._test_camera_connection(camera)
            
            # Send test result
            emit('camera_test_result', {
                'success': connection_status['status'] == 'connected',
                'camera_id': camera_id,
                'connection_status': connection_status,
                'message': f"Camera test {'passed' if connection_status['status'] == 'connected' else 'failed'}"
            })
            
            print(f"📹 Camera {camera_id} test: {connection_status['status']}")
            
        except Exception as e:
            print(f"❌ Error testing camera: {e}")
            emit('camera_test_result', {
                'success': False,
                'error': str(e)
            })
    
    @socketio.on('refresh_cameras')
    def handle_refresh_cameras():
        """Handle camera status refresh request"""
        try:
            # Send updated camera status
            ws_manager._send_camera_status()
            
            emit('cameras_refreshed', {
                'success': True,
                'message': 'Camera status refreshed',
                'timestamp': datetime.now().isoformat()
            })
            
            print(f"📹 Camera status refreshed by client {request.sid}")
            
        except Exception as e:
            print(f"❌ Error refreshing cameras: {e}")
            emit('cameras_refreshed', {
                'success': False,
                'error': str(e)
            })
    
    return ws_manager

# Export socketio instance for use in other modules
socketio = None

def set_socketio(sio):
    """Set the socketio instance for broadcasting events"""
    global socketio
    socketio = sio

def broadcast_reload_plates():
    """Broadcast reload_plates signal to all connected ANPR clients"""
    if socketio:
        try:
            socketio.emit('reload_plates', {
                'timestamp': datetime.now().isoformat(),
                'message': 'Allowed plates updated in admin panel'
            }, broadcast=True)
            print("📡 Broadcast reload_plates signal to ANPR service")
        except Exception as e:
            print(f"⚠️ Error broadcasting reload_plates: {e}")
