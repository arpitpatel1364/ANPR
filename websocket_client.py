"""
WebSocket Client for ANPR System
Sends real-time detection events to admin panel
"""

import socketio
import json
import time
import threading
from datetime import datetime
from typing import Dict, Any, Optional
import logging

class ANPRWebSocketClient:
    """WebSocket client for sending real-time ANPR data to admin panel"""
    
    def __init__(self, admin_panel_url: str = "http://localhost:8084"):
        self.admin_panel_url = admin_panel_url
        self.sio = socketio.Client()
        self.connected = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.reconnect_delay = 5  # seconds
        
        # Callbacks for incoming messages from admin panel
        self.reload_plates_callback = None
        
        # Setup event handlers
        self._setup_event_handlers()
        
        # Start connection in background thread
        self.connection_thread = threading.Thread(target=self._connect, daemon=True)
        self.connection_thread.start()
    
    def _setup_event_handlers(self):
        """Setup WebSocket event handlers"""
        
        @self.sio.event
        def connect():
            self.connected = True
            self.reconnect_attempts = 0
            print("✅ Connected to ANPR Admin Panel WebSocket")
            
            # Join the ANPR system room
            self.sio.emit('join_room', {'room': 'anpr_system'})
        
        @self.sio.event
        def disconnect():
            self.connected = False
            print("❌ Disconnected from ANPR Admin Panel WebSocket")
            self._attempt_reconnect()
        
        @self.sio.event
        def connect_error(data):
            self.connected = False
            print(f"❌ WebSocket connection error: {data}")
            self._attempt_reconnect()
        
        @self.sio.event
        def joined_room(data):
            print(f"✅ Joined room: {data.get('room', 'unknown')}")
        
        @self.sio.event
        def reload_plates(data):
            """Handle reload_plates message from admin panel"""
            print(f"🔄 Received reload_plates signal from admin panel")
            if self.reload_plates_callback:
                try:
                    self.reload_plates_callback()
                    print(f"✅ Plates reloaded successfully")
                except Exception as e:
                    print(f"❌ Error reloading plates: {e}")
    
    def _connect(self):
        """Connect to WebSocket server"""
        while not self.connected and self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                print(f"🔄 Attempting to connect to {self.admin_panel_url} (attempt {self.reconnect_attempts + 1})")
                self.sio.connect(self.admin_panel_url)
                break
            except Exception as e:
                self.reconnect_attempts += 1
                print(f"❌ Connection failed: {e}")
                if self.reconnect_attempts < self.max_reconnect_attempts:
                    print(f"⏳ Retrying in {self.reconnect_delay} seconds...")
                    time.sleep(self.reconnect_delay)
                else:
                    print("❌ Max reconnection attempts reached. WebSocket features disabled.")
    
    def _attempt_reconnect(self):
        """Attempt to reconnect to WebSocket server"""
        if self.reconnect_attempts < self.max_reconnect_attempts:
            self.reconnect_attempts += 1
            print(f"🔄 Attempting reconnection {self.reconnect_attempts}/{self.max_reconnect_attempts}")
            threading.Timer(self.reconnect_delay, self._connect).start()
    
    def send_detection(self, detection_data: Dict[str, Any]):
        """Send detection event to admin panel"""
        if not self.connected:
            print("⚠️ WebSocket not connected, skipping detection broadcast")
            return
        
        try:
            # Add timestamp and source info
            detection_data.update({
                'timestamp': datetime.now().isoformat(),
                'source': 'anpr_system',
                'event_type': 'detection'
            })
            
            # Send to admin panel
            self.sio.emit('anpr_detection', detection_data)
            print(f"📡 Sent detection: {detection_data.get('plate', 'unknown')}")
            
        except Exception as e:
            print(f"❌ Error sending detection: {e}")
    
    def send_system_status(self, status_data: Dict[str, Any]):
        """Send system status update to admin panel"""
        if not self.connected:
            return
        
        try:
            status_data.update({
                'timestamp': datetime.now().isoformat(),
                'source': 'anpr_system',
                'event_type': 'system_status'
            })
            
            self.sio.emit('anpr_system_status', status_data)
            
        except Exception as e:
            print(f"❌ Error sending system status: {e}")
    
    def send_camera_status(self, camera_id: str, status: Dict[str, Any]):
        """Send camera status update to admin panel"""
        if not self.connected:
            return
        
        try:
            status_data = {
                'camera_id': camera_id,
                'timestamp': datetime.now().isoformat(),
                'source': 'anpr_system',
                'event_type': 'camera_status',
                **status
            }
            
            self.sio.emit('anpr_camera_status', status_data)
            
        except Exception as e:
            print(f"❌ Error sending camera status: {e}")
    
    def is_connected(self) -> bool:
        """Check if WebSocket is connected"""
        return self.connected
    
    def set_reload_plates_callback(self, callback):
        """Register callback function to be called when plates need to be reloaded"""
        self.reload_plates_callback = callback
    
    def disconnect(self):
        """Disconnect from WebSocket server"""
        if self.connected:
            self.sio.disconnect()
            self.connected = False

# Global WebSocket client instance
websocket_client = None

def initialize_websocket_client(admin_panel_url: str = "http://localhost:8084") -> ANPRWebSocketClient:
    """Initialize the global WebSocket client"""
    global websocket_client
    if websocket_client is None:
        websocket_client = ANPRWebSocketClient(admin_panel_url)
    return websocket_client

def get_websocket_client() -> Optional[ANPRWebSocketClient]:
    """Get the global WebSocket client instance"""
    return websocket_client
