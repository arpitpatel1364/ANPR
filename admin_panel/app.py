from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from flask_socketio import SocketIO, emit
from werkzeug.security import check_password_hash, generate_password_hash
import os
import json
import sys
import time
from datetime import datetime, timedelta
from functools import wraps

# Add parent directory to path for db_connection import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db_connection import DatabaseConnection, execute_query

# Import our custom modules
from auth import auth_bp, require_auth, is_session_valid
from plate_manager import plate_bp
from camera_manager import camera_bp
from detection_manager import detection_bp
from api_bridge import api_bridge_bp
from anpr_interface import anpr_interface
from settings import settings_bp
from websocket_server import register_websocket_events, set_socketio
from config_db import load_config_from_db

app = Flask(__name__)
app.secret_key = 'anpr_admin_secret_key_2024'

# Initialize SocketIO with better error handling
# Explicitly use threading mode to avoid auto-detection issues
socketio = SocketIO(
    app, 
    cors_allowed_origins="*", 
    async_mode='threading',  # Explicitly use threading mode
    logger=False,  # Disable SocketIO logging to reduce noise
    engineio_logger=False,  # Disable EngineIO logging
    ping_timeout=60,  # Increase ping timeout
    ping_interval=25,  # Increase ping interval
    transports=['polling', 'websocket']  # Allow both; client will upgrade from polling to websocket
)

# Security configuration
app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # 1 hour
app.config['UPLOAD_FOLDER'] = 'static/images/verified_plates'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Security headers
@app.after_request
def after_request(response):
    # Security headers
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://code.jquery.com https://cdn.socket.io https://cdnjs.cloudflare.com; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: blob:; font-src 'self' https://cdn.jsdelivr.net; connect-src 'self' ws://localhost:8084 wss://localhost:8084 https://cdn.jsdelivr.net https://cdn.socket.io https://cdnjs.cloudflare.com; frame-src 'self'; object-src 'none'; base-uri 'self';"
    return response

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Register blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(plate_bp)
app.register_blueprint(camera_bp)
app.register_blueprint(detection_bp)
app.register_blueprint(api_bridge_bp)
app.register_blueprint(settings_bp)

# Register WebSocket events
ws_manager = register_websocket_events(socketio)
set_socketio(socketio)  # Make socketio available for broadcasting in other modules

# Error handler for WSGI issues
@app.errorhandler(500)
def handle_wsgi_error(e):
    """Handle WSGI errors gracefully"""
    print(f"WSGI Error: {e}")
    return "Internal Server Error", 500

# Error handler for SocketIO errors
@socketio.on_error_default
def default_error_handler(e):
    """Handle SocketIO errors gracefully"""
    print(f"SocketIO Error: {e}")
    # return False  # Don't emit error to avoid WSGI issues
    
    # Don't return False or anything that triggers WSGI response
    # Just log and let SocketIO handle it internally
    pass

# Enhanced login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_session_valid():
            session.clear()
            flash('Session expired. Please login again.', 'warning')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

# Security middleware - protect all routes except login
@app.before_request
def security_check():
    # Allow access to login page, static files, API endpoints, and camera test/ROI endpoints
    if (request.endpoint in ['auth.login', 'auth.check_session', 'static'] or 
        request.path.startswith('/api/') or 
        request.path.startswith('/cameras/test/') or
        request.path.startswith('/cameras/set_roi/') or
        request.path.startswith('/cameras/save_roi/')):
        return
    
    # Check if user is authenticated
    if not is_session_valid():
        session.clear()
        flash('Access denied. Please login first.', 'error')
        return redirect(url_for('auth.login'))
    
    # Update session activity time
    session['last_activity'] = time.time()

@app.route('/')
@login_required
def dashboard():
    """Main dashboard with statistics and recent detections"""
    try:
        # Get statistics from database
        with DatabaseConnection() as db:
            # Total detections
            db.execute("SELECT COUNT(*) as count FROM detections")
            result = db.fetchone()
            total_detections = result['count'] if result else 0
            
            # Verified detections
            db.execute("SELECT COUNT(*) as count FROM detections WHERE verification_status = 'VERIFIED'")
            result = db.fetchone()
            verified_detections = result['count'] if result else 0
            
            # Unverified detections
            db.execute("SELECT COUNT(*) as count FROM detections WHERE verification_status = 'NOT_VERIFIED'")
            result = db.fetchone()
            unverified_detections = result['count'] if result else 0
            
            verification_rate = (verified_detections / total_detections * 100) if total_detections > 0 else 0
            
            # Recent detections (newest first, last 10)
            db.execute("""
                SELECT timestamp, license_plate, verification_status, access_granted,
                       detection_confidence, camera_source, frame_number,
                       image_full_annotated, bbox_x1, bbox_y1, bbox_x2, bbox_y2
                FROM detections
                ORDER BY timestamp DESC
                LIMIT 10
            """)
            recent_rows = db.fetchall()
            
            # Convert to dict format for template
            recent_detections = []
            for row in recent_rows:
                recent_detections.append({
                    'Timestamp': row['timestamp'].strftime('%Y-%m-%d %H:%M:%S') if row['timestamp'] else '',
                    'License_Plate': row['license_plate'],
                    'Verification_Status': row['verification_status'],
                    'Access_Granted': row['access_granted'],
                    'Detection_Confidence': f"{row['detection_confidence']:.3f}",
                    'Camera_Source': row['camera_source'],
                    'Frame_Number': row['frame_number'],
                    'Image_Full_Annotated': row['image_full_annotated'] or '',
                    'bbox_x1': row['bbox_x1'],
                    'bbox_y1': row['bbox_y1'],
                    'bbox_x2': row['bbox_x2'],
                    'bbox_y2': row['bbox_y2']
                })
            
            # Allowed plates count
            db.execute("SELECT COUNT(*) as count FROM allowed_plates")
            result = db.fetchone()
            total_allowed_plates = result['count'] if result else 0
        
        # Load camera status from DB
        cameras = []
        active_cameras = 0
        total_cameras = 0
        try:
            config = load_config_from_db()
            if config:
                cameras = config.get('cameras', [])
                active_cameras = len([cam for cam in cameras if cam.get('enabled', False)])
                total_cameras = len(cameras)
        except Exception as e:
            print(f"Warning: Could not load camera config from DB: {e}")
        
        stats = {
            'total_detections': total_detections,
            'verified_detections': verified_detections,
            'unverified_detections': unverified_detections,
            'verification_rate': round(verification_rate, 1),
            'active_cameras': active_cameras,
            'total_cameras': total_cameras,
            'total_allowed_plates': total_allowed_plates
        }
        
        return render_template('dashboard.html', 
                             stats=stats, 
                             recent_detections=recent_detections, 
                             cameras=cameras,
                             enabled_cameras=active_cameras,
                             total_cameras=total_cameras)
        
    except Exception as e:
        flash(f'Error loading dashboard: {str(e)}', 'error')
        return render_template('dashboard.html', 
                             stats={}, 
                             recent_detections=[], 
                             cameras=[],
                             enabled_cameras=0,
                             total_cameras=0)

@app.route('/api/stats')
@login_required
def api_stats():
    """API endpoint for real-time statistics"""
    try:
        with DatabaseConnection() as db:
            # Today's detections
            today = datetime.now().date()
            db.execute("SELECT COUNT(*) as count FROM detections WHERE DATE(timestamp) = %s", (today,))
            result = db.fetchone()
            today_detections = result['count'] if result else 0
            
            # Today's verified
            db.execute("""
                SELECT COUNT(*) as count FROM detections 
                WHERE DATE(timestamp) = %s AND verification_status = 'VERIFIED'
            """, (today,))
            result = db.fetchone()
            today_verified = result['count'] if result else 0
            
            # Total detections
            db.execute("SELECT COUNT(*) as count FROM detections")
            result = db.fetchone()
            total_detections = result['count'] if result else 0
            
            # Verified detections
            db.execute("SELECT COUNT(*) as count FROM detections WHERE verification_status = 'VERIFIED'")
            result = db.fetchone()
            verified_detections = result['count'] if result else 0
            
            verification_rate = round(
                (verified_detections / total_detections * 100) if total_detections > 0 else 0, 1
            )
        
        stats = {
            'today_detections': today_detections,
            'today_verified': today_verified,
            'total_detections': total_detections,
            'verification_rate': verification_rate
        }
        
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 Starting ANPR Admin Panel Server...")
    print("=" * 60)
    print(f"📍 Server will be available at: http://0.0.0.0:8084")
    print(f"🔧 Debug mode: {'ON' if True else 'OFF'}")
    print(f"🔄 Auto-reload: {'ON' if True else 'OFF'}")
    print("=" * 60)
    
    # Enable auto-reload for development
    try:
        socketio.run(
            app, 
            debug=True,  # Enable debug mode for auto-reload
            host='0.0.0.0', 
            port=8084, 
            allow_unsafe_werkzeug=True,
            use_reloader=True,  # Enable reloader for auto-reload
            log_output=True
        )
    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user")
    except Exception as e:
        print(f"\n❌ Server error: {e}")
        raise
