from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
import json
import os
import subprocess
from datetime import datetime
from camera_status import get_camera_status
from scripts.config_db import (
    load_config_from_db,
    add_camera_to_db,
    update_camera_in_db,
    delete_camera_from_db,
    update_camera_status_in_db,
    trigger_hot_reload
)

def safe_int(value, default=0):
    try:
        if value is None or str(value).strip() == '':
            return default
        return int(value)
    except (ValueError, TypeError):
        return default

def safe_float(value, default=0.0):
    try:
        if value is None or str(value).strip() == '':
            return default
        return float(value)
    except (ValueError, TypeError):
        return default

camera_bp = Blueprint('camera', __name__)
import threading
import time

_CAMERA_STATUS_CACHE = {}
_CAMERA_STATUS_LAST_UPDATE = 0
_CAMERA_STATUS_LOCK = threading.Lock()
def parse_roi_from_form(form):
    """Parse ROI bounding box values from the submitted form."""
    try:
        x1 = form.get('roi_x1', '').strip()
        y1 = form.get('roi_y1', '').strip()
        x2 = form.get('roi_x2', '').strip()
        y2 = form.get('roi_y2', '').strip()

        if x1 != '' and y1 != '' and x2 != '' and y2 != '':
            x1 = int(x1)
            y1 = int(y1)
            x2 = int(x2)
            y2 = int(y2)
            if x2 > x1 and y2 > y1:
                return {'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2}
    except (ValueError, TypeError):
        pass

    return None


@camera_bp.route('/cameras')
def cameras():
    """Camera management page"""
    config = load_config_from_db()
    cameras = config.get('cameras', []) if config else [] if config else []
    
    return render_template('cameras.html', cameras=cameras)

@camera_bp.route('/cameras/add', methods=['POST'])
def add_camera():
    """Add new camera"""
    camera_data = {
        'id': request.form.get('id', '').strip(),
        'name': request.form.get('name', '').strip(),
        'location': request.form.get('location', '').strip(),
        'rtsp_source': request.form.get('rtsp_source', '').strip(),
        'dedup_window': safe_int(request.form.get('dedup_window'), 50),
        'confidence_threshold': safe_float(request.form.get('confidence_threshold'), 0.8),
        'enabled': request.form.get('enabled') == 'on',
        'api_enabled': request.form.get('api_enabled') == 'on',
        'api_settings': {
            'base_url': request.form.get('api_base_url', '').strip(),
            'username': request.form.get('api_username', 'admin').strip(),
            'password': request.form.get('api_password', 'Admin@123').strip(),
            'modes': [1, 2],
            'timeout': safe_int(request.form.get('api_timeout'), 5),
            'max_retries': safe_int(request.form.get('api_max_retries'), 3)
        }
    }

    roi = parse_roi_from_form(request.form)
    if roi is not None:
        camera_data['roi'] = roi
        
    # Process optional JSON roi_data from 2-step setup
    roi_data_str = request.form.get('roi_data', '')
    if roi_data_str:
        import json
        try:
            roi_data_json = json.loads(roi_data_str)
            roi_type = roi_data_json.get('roi_type')
            coordinates = roi_data_json.get('coordinates', [])
            
            if roi_type == 'rectangle' and len(coordinates) == 4:
                camera_data['roi'] = {
                    'x1': int(coordinates[0]),
                    'y1': int(coordinates[1]),
                    'x2': int(coordinates[2]),
                    'y2': int(coordinates[3])
                }
                camera_data['roi_polygon'] = []
            elif roi_type == 'polygon' and len(coordinates) >= 3:
                camera_data['roi_polygon'] = [{'x': int(pt[0]), 'y': int(pt[1])} for pt in coordinates]
                camera_data['roi'] = None
        except Exception as e:
            print(f"Error parsing roi_data: {e}")
    
    # Validate required fields
    if not camera_data['id'] or not camera_data['name'] or not camera_data['rtsp_source']:
        flash('ID, Name, and RTSP Source are required!', 'error')
        return redirect(url_for('camera.cameras'))
    
    config = load_config_from_db()
    cameras = config.get('cameras', []) if config else [] if config else []
    
    # Check if ID already exists
    if any(cam['id'] == camera_data['id'] for cam in cameras):
        flash(f'Camera ID {camera_data["id"]} already exists!', 'error')
        return redirect(url_for('camera.cameras'))

    if add_camera_to_db(camera_data):
        flash(f'Camera {camera_data["name"]} added successfully! Hot reload triggered.', 'success')
        return redirect(url_for('camera.cameras'))
    else:
        flash('Error adding camera to database!', 'error')
    return redirect(url_for('camera.cameras'))

@camera_bp.route('/cameras/edit/<camera_id>', methods=['POST'])
def edit_camera(camera_id):
    """Edit existing camera"""
    config = load_config_from_db()
    cameras = config.get('cameras', []) if config else [] if config else []
    
    camera_index = None
    for i, cam in enumerate(cameras):
        if cam['id'] == camera_id:
            camera_index = i
            break
    
    if camera_index is None:
        flash('Camera not found!', 'error')
        return redirect(url_for('camera.cameras'))
    
    update_data = {
        'name': request.form.get('name', '').strip(),
        'location': request.form.get('location', '').strip(),
        'rtsp_source': request.form.get('rtsp_source', '').strip(),
        'dedup_window': safe_int(request.form.get('dedup_window'), 50),
        'confidence_threshold': safe_float(request.form.get('confidence_threshold'), 0.8),
        'enabled': request.form.get('enabled') == 'on',
        'api_enabled': request.form.get('api_enabled') == 'on',
        'api_settings': {
            'base_url': request.form.get('api_base_url', '').strip(),
            'username': request.form.get('api_username', 'admin').strip(),
            'password': request.form.get('api_password', 'Admin@123').strip(),
            'modes': [1, 2],
            'timeout': safe_int(request.form.get('api_timeout'), 5),
            'max_retries': safe_int(request.form.get('api_max_retries'), 3)
        }
    }

    roi = parse_roi_from_form(request.form)
    if roi is not None:
        update_data['roi'] = roi
    elif 'roi' in cameras[camera_index]:
        update_data['roi'] = None
    
    if update_camera_in_db(camera_id, update_data):
        flash(f'Camera {update_data["name"]} updated successfully! Hot reload triggered.', 'success')
    else:
        flash('Error updating camera!', 'error')
    return redirect(url_for('camera.cameras'))

@camera_bp.route('/cameras/delete/<camera_id>', methods=['POST'])
def delete_camera(camera_id):
    """Delete camera"""
    config = load_config_from_db()
    cameras = config.get('cameras', []) if config else [] if config else []
    
    camera_name = "Unknown"
    for cam in cameras:
        if cam['id'] == camera_id:
            camera_name = cam['name']
            break
    
    if camera_name == "Unknown":
        flash('Camera not found!', 'error')
        return redirect(url_for('camera.cameras'))

    snapshot_path = os.path.join(os.path.dirname(__file__), 'static', 'images', 'roi_snapshots', f'{camera_id}.jpg')
    try:
        if os.path.exists(snapshot_path):
            os.remove(snapshot_path)
    except Exception as e:
        print(f"⚠️ Could not remove ROI snapshot for {camera_id}: {e}")
    
    if delete_camera_from_db(camera_id):
        flash(f'Camera {camera_name} deleted successfully! Hot reload triggered.', 'success')
    else:
        flash('Error deleting camera!', 'error')
    return redirect(url_for('camera.cameras'))

@camera_bp.route('/cameras/toggle/<camera_id>', methods=['POST'])
def toggle_camera(camera_id):
    """Toggle camera enabled/disabled status"""
    try:
        config = load_config_from_db()
        cameras = config.get('cameras', []) if config else [] if config else []
        
        for camera in cameras:
            if camera['id'] == camera_id:
                new_status = not camera['enabled']
                status_text = 'enabled' if new_status else 'disabled'
                
                if update_camera_status_in_db(camera_id, new_status):
                    return jsonify({
                        'success': True,
                        'message': f'Camera {camera["name"]} {status_text} successfully!',
                        'enabled': new_status
                    })
                else:
                    return jsonify({
                        'success': False,
                        'message': 'Error updating camera status!'
                    })
        return jsonify({
            'success': False,
            'message': 'Camera not found!'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        })

@camera_bp.route('/cameras/test/<camera_id>')
def test_camera(camera_id):
    """Test camera connection"""
    config = load_config_from_db()
    cameras = config.get('cameras', []) if config else []
    
    for camera in cameras:
        if camera['id'] == camera_id:
            try:
                status = get_camera_status(camera)
                
                if status['connection']['connected']:
                    latency = status['connection'].get('latency_ms', 0)
                    message = f'Camera connection successful! Latency: {latency}ms'
                    if status['connection'].get('frame_size'):
                        message += f" | Resolution: {status['connection']['frame_size']}"
                    return jsonify({
                        'status': 'success',
                        'message': message,
                        'data': status
                    })
                else:
                    error = status['connection'].get('error', 'Connection failed')
                    return jsonify({
                        'status': 'error',
                        'message': f'Connection failed: {error}',
                        'data': status
                    })
                    
            except Exception as e:
                return jsonify({
                    'status': 'error',
                    'message': f'Test failed: {str(e)}'
                })
    
    return jsonify({'status': 'error', 'message': 'Camera not found'})

@camera_bp.route('/cameras/status/<camera_id>')
def get_camera_status_endpoint(camera_id):
    """Get real-time camera status"""
    config = load_config_from_db()
    cameras = config.get('cameras', []) if config else []
    
    for camera in cameras:
        if camera['id'] == camera_id:
            try:
                status = get_camera_status(camera)
                return jsonify({
                    'success': True,
                    'data': status
                })
            except Exception as e:
                return jsonify({
                    'success': False,
                    'error': str(e)
                }), 500
    
    return jsonify({
        'success': False,
        'error': 'Camera not found'
    }), 404

@camera_bp.route('/cameras/status/all')
def get_all_cameras_status():
    """Get status for all cameras"""
    global _CAMERA_STATUS_LAST_UPDATE
    config = load_config_from_db()
    cameras = config.get('cameras', []) if config else []
    
    with _CAMERA_STATUS_LOCK:
        current_time = time.time()
        if current_time - _CAMERA_STATUS_LAST_UPDATE < 30 and 'all' in _CAMERA_STATUS_CACHE:
            return jsonify({
                'success': True,
                'data': _CAMERA_STATUS_CACHE['all'],
                'timestamp': datetime.now().isoformat()
            })
            
    try:
        import concurrent.futures
        all_status = []
        
        # Parallelize camera status checks since they are IO-bound and slow
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(10, len(cameras) or 1)) as executor:
            future_to_cam = {executor.submit(get_camera_status, cam): cam for cam in cameras}
            for future in concurrent.futures.as_completed(future_to_cam):
                try:
                    status = future.result()
                    all_status.append(status)
                except Exception as exc:
                    print(f"Camera status check generated an exception: {exc}")
        
        with _CAMERA_STATUS_LOCK:
            _CAMERA_STATUS_CACHE['all'] = all_status
            _CAMERA_STATUS_LAST_UPDATE = time.time()
            
        return jsonify({
            'success': True,
            'data': all_status,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@camera_bp.route('/cameras/set_roi/<camera_id>', methods=['POST'])
def set_camera_roi(camera_id):
    """Capture latest frame for ROI selection with timeout protection"""
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    import cv2
    import base64
    import threading
    
    config = load_config_from_db()
    cameras = config.get('cameras', []) if config else []
    camera_cfg = next((cam for cam in cameras if cam.get('id') == camera_id), None)

    if camera_cfg is None:
        return jsonify({'success': False, 'message': 'Camera not found'}), 404

    try:
        # First, try to use cached snapshot (fastest path)
        snapshot_dir = os.path.join(os.path.dirname(__file__), 'static', 'images', 'roi_snapshots')
        snapshot_path = os.path.join(snapshot_dir, f'{camera_id}.jpg')
        
        import time
        # Wait up to 3 seconds for the background process to create the snapshot
        for _ in range(15):
            if os.path.exists(snapshot_path):
                break
            time.sleep(0.2)
            
        if os.path.exists(snapshot_path):
            frame = cv2.imread(snapshot_path)
            if frame is not None and frame.size > 0:
                # Use cached snapshot - much faster than opening RTSP stream
                _, buffer = cv2.imencode('.jpg', frame)
                frame_b64 = base64.b64encode(buffer).decode('utf-8')
                
                return jsonify({
                    'success': True,
                    'mode': 'web_roi',
                    'frame': frame_b64,
                    'camera_id': camera_id,
                    'camera_name': camera_cfg.get('name', 'Unknown Camera'),
                    'frame_width': int(frame.shape[1]),
                    'frame_height': int(frame.shape[0]),
                    'message': 'Frame loaded from cache. Use the web interface to set ROI.'
                })
        
        # If no cached snapshot, try to capture fresh frame with timeout protection
        rtsp_source = camera_cfg.get('rtsp_source')
        if rtsp_source is None or (isinstance(rtsp_source, str) and rtsp_source.strip() == ""):
            return jsonify({'success': False, 'message': 'No RTSP source configured for this camera'}), 400

        frame_container = {'frame': None, 'cap': None}
        capture_timeout = 10  # 10 second timeout for frame capture
        
        def capture_frame_with_timeout():
            """Capture frame in a separate thread with timeout"""
            try:
                if isinstance(rtsp_source, int) or (isinstance(rtsp_source, str) and rtsp_source.isdigit()):
                    cap = cv2.VideoCapture(int(rtsp_source))
                else:
                    cap = cv2.VideoCapture(rtsp_source, cv2.CAP_FFMPEG)
                frame_container['cap'] = cap
                
                # Set minimal properties to speed up connection
                try:
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                except:
                    pass
                
                if not cap or not cap.isOpened():
                    return
                
                # Try to read one frame
                ret, captured_frame = cap.read()
                if ret and captured_frame is not None and captured_frame.size > 0:
                    frame_container['frame'] = captured_frame
            except Exception as e:
                pass  # Silently fail in timeout thread
            finally:
                # Release capture in thread
                if frame_container['cap'] is not None:
                    try:
                        frame_container['cap'].release()
                    except:
                        pass
        
        # Run frame capture with timeout
        capture_thread = threading.Thread(target=capture_frame_with_timeout, daemon=True)
        capture_thread.start()
        capture_thread.join(timeout=capture_timeout)  # Wait max 5 seconds
        
        frame = frame_container['frame']
        
        if frame is None:
            return jsonify({
                'success': False, 
                'message': f'Unable to capture frame from camera stream (timeout after {capture_timeout}s). Please ensure RTSP stream is accessible.'
            }), 500

        # Convert frame to base64 for web display
        _, buffer = cv2.imencode('.jpg', frame)
        frame_b64 = base64.b64encode(buffer).decode('utf-8')
        
        return jsonify({
            'success': True,
            'mode': 'web_roi',
            'frame': frame_b64,
            'camera_id': camera_id,
            'camera_name': camera_cfg.get('name', 'Unknown Camera'),
            'frame_width': int(frame.shape[1]),
            'frame_height': int(frame.shape[0]),
            'message': 'Frame captured successfully. Use the web interface to set ROI.'
        })

    except Exception as e:
        return jsonify({'success': False, 'message': f'Error capturing frame: {str(e)[:100]}'}), 500


@camera_bp.route('/cameras/save_roi/<camera_id>', methods=['POST'])
def save_camera_roi(camera_id):
    """Save ROI coordinates from web-based selection"""
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400
    
    roi_type = data.get('roi_type')  # 'rectangle' or 'polygon'
    coordinates = data.get('coordinates', [])
    
    if not coordinates:
        return jsonify({'success': False, 'message': 'No ROI coordinates provided'}), 400
    
    try:
        config = load_config_from_db()
        cameras = config.get('cameras', []) if config else [] if config else []
        camera_cfg = next((cam for cam in cameras if cam.get('id') == camera_id), None)

        if camera_cfg is None:
            return jsonify({'success': False, 'message': 'Camera not found'}), 404

        # Update camera configuration
        update_data = {}
        if roi_type == 'rectangle':
            if len(coordinates) == 4:
                update_data['roi'] = {
                    'x1': int(coordinates[0]),
                    'y1': int(coordinates[1]),
                    'x2': int(coordinates[2]),
                    'y2': int(coordinates[3])
                }
                update_data['roi_polygon'] = []
            else:
                return jsonify({'success': False, 'message': 'Invalid rectangle coordinates'}), 400
        elif roi_type == 'polygon':
            if len(coordinates) >= 3:
                update_data['roi_polygon'] = [{'x': int(pt[0]), 'y': int(pt[1])} for pt in coordinates]
                update_data['roi'] = None
            else:
                return jsonify({'success': False, 'message': 'Polygon must have at least 3 points'}), 400
        else:
            return jsonify({'success': False, 'message': 'Invalid ROI type'}), 400

        if update_camera_in_db(camera_id, update_data):
            return jsonify({
                'success': True,
                'message': f'ROI saved successfully for camera {camera_cfg.get("name", camera_id)}'
            })
        else:
            return jsonify({'success': False, 'message': 'Error saving ROI to database'}), 500

    except Exception as e:
        return jsonify({'success': False, 'message': f'Error saving ROI: {e}'}), 500


@camera_bp.route('/cameras/capture_test_frame', methods=['POST'])
def capture_test_frame():
    """Capture a test frame from an RTSP source before saving camera"""
    data = request.get_json()
    rtsp_source = data.get('rtsp_source') if data and 'rtsp_source' in data else data.get('rtsp_url') if data else None
    if rtsp_source is None or str(rtsp_source).strip() == '':
        return jsonify({'success': False, 'message': 'No RTSP source provided'}), 400
    
    try:
        import cv2
        import threading
        import base64
        
        frame_container = {'frame': None, 'cap': None}
        capture_timeout = 10  # 10 second timeout
        
        def capture_frame_with_timeout():
            try:
                source = int(rtsp_source) if str(rtsp_source).isdigit() else rtsp_source
                cap = cv2.VideoCapture(source)
                frame_container['cap'] = cap
                if not cap.isOpened():
                    return
                # Try to read one frame
                ret, captured_frame = cap.read()
                if ret and captured_frame is not None and captured_frame.size > 0:
                    frame_container['frame'] = captured_frame
            except Exception:
                pass
            finally:
                if frame_container['cap'] is not None:
                    try:
                        frame_container['cap'].release()
                    except:
                        pass
        
        # Run frame capture with timeout
        capture_thread = threading.Thread(target=capture_frame_with_timeout, daemon=True)
        capture_thread.start()
        capture_thread.join(timeout=capture_timeout)
        
        frame = frame_container['frame']
        
        if frame is None:
            return jsonify({
                'success': False, 
                'message': f'Unable to capture frame from camera stream (timeout after {capture_timeout}s). Please check RTSP URL.'
            }), 500

        # Convert frame to base64
        _, buffer = cv2.imencode('.jpg', frame)
        frame_b64 = base64.b64encode(buffer).decode('utf-8')
        
        return jsonify({
            'success': True,
            'frame': frame_b64,
            'frame_width': int(frame.shape[1]),
            'frame_height': int(frame.shape[0])
        })

    except Exception as e:
        return jsonify({'success': False, 'message': f'Error capturing frame: {str(e)[:100]}'}), 500


@camera_bp.route('/cameras/reload/<camera_id>', methods=['POST'])
def reload_camera(camera_id):
    """Trigger hot reload of a specific camera after ROI change"""
    try:
        trigger_hot_reload()
        return jsonify({
            'success': True,
            'message': f'Camera {camera_id} reloaded successfully'
        })
            
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error reloading camera: {e}'}), 500

@camera_bp.route('/cameras/preview_rtsp', methods=['POST'])
def preview_rtsp():
    """Capture a single frame from an arbitrary RTSP URL for preview"""
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    import cv2
    import base64
    import threading

    data = request.get_json()
    rtsp_source = data.get('rtsp_url') if data else None

    if not rtsp_source or not str(rtsp_source).strip():
        return jsonify({'success': False, 'message': 'No RTSP source provided'}), 400

    frame_container = {'frame': None, 'cap': None}
    capture_timeout = 5
    
    def capture_frame_with_timeout():
        try:
            if isinstance(rtsp_source, int) or (isinstance(rtsp_source, str) and rtsp_source.isdigit()):
                cap = cv2.VideoCapture(int(rtsp_source))
            else:
                cap = cv2.VideoCapture(rtsp_source, cv2.CAP_FFMPEG)
            frame_container['cap'] = cap
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except:
                pass
            if not cap or not cap.isOpened():
                return
            ret, captured_frame = cap.read()
            if ret and captured_frame is not None and captured_frame.size > 0:
                frame_container['frame'] = captured_frame
        except Exception:
            pass
        finally:
            if frame_container['cap'] is not None:
                try:
                    frame_container['cap'].release()
                except:
                    pass
    
    capture_thread = threading.Thread(target=capture_frame_with_timeout, daemon=True)
    capture_thread.start()
    capture_thread.join(timeout=capture_timeout)
    
    frame = frame_container['frame']
    
    if frame is None:
        return jsonify({
            'success': False, 
            'message': f'Unable to capture frame from stream (timeout after {capture_timeout}s).'
        }), 500

    _, buffer = cv2.imencode('.jpg', frame)
    frame_b64 = base64.b64encode(buffer).decode('utf-8')
    
    return jsonify({
        'success': True,
        'frame': frame_b64,
        'frame_width': int(frame.shape[1]),
        'frame_height': int(frame.shape[0])
    })

