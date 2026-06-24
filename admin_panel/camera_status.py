"""
Camera status checking utilities
"""
import cv2
import subprocess
import time
import os

# Prevent OpenCV from hanging on bad RTSP streams
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|max_delay;500000|stimeout;5000000"
from typing import Dict, Any, Optional
from datetime import datetime

def test_rtsp_connection(rtsp_url: str, timeout: int = 5) -> Dict[str, Any]:
    """
    Test RTSP camera connection using OpenCV
    
    Returns:
        dict with 'connected', 'latency_ms', 'error' keys
    """
    start_time = time.time()
    cap = None
    
    try:
        # Try to open RTSP stream with short timeout
        if isinstance(rtsp_url, int) or (isinstance(rtsp_url, str) and rtsp_url.isdigit()):
            cap = cv2.VideoCapture(int(rtsp_url))
        else:
            cap = cv2.VideoCapture(rtsp_url)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        
        # Set timeout for read operation
        start_read = time.time()
        ret, frame = cap.read()
        read_time = (time.time() - start_read) * 1000  # Convert to milliseconds
        
        if ret and frame is not None:
            # Connection successful
            latency = (time.time() - start_time) * 1000
            cap.release()
            return {
                'connected': True,
                'latency_ms': round(latency, 2),
                'read_time_ms': round(read_time, 2),
                'frame_size': f"{frame.shape[1]}x{frame.shape[0]}" if frame is not None else None,
                'error': None
            }
        else:
            cap.release()
            return {
                'connected': False,
                'latency_ms': None,
                'read_time_ms': None,
                'frame_size': None,
                'error': 'Failed to read frame from stream'
            }
            
    except Exception as e:
        if cap:
            try:
                cap.release()
            except:
                pass
        return {
            'connected': False,
            'latency_ms': None,
            'read_time_ms': None,
            'frame_size': None,
            'error': str(e)
        }

def test_rtsp_with_ffprobe(rtsp_url: str, timeout: int = 5) -> Dict[str, Any]:
    """
    Test RTSP camera connection using ffprobe (alternative method)
    
    Returns:
        dict with 'connected', 'latency_ms', 'error' keys
    """
    start_time = time.time()
    
    if isinstance(rtsp_url, int) or (isinstance(rtsp_url, str) and rtsp_url.isdigit()):
        return {
            'connected': None,  # None means ffprobe not available/suitable
            'latency_ms': None,
            'read_time_ms': None,
            'frame_size': None,
            'error': 'ffprobe not suitable for local camera indexes'
        }
        
    try:
        result = subprocess.run([
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_streams', '-timeout', str(timeout * 1000000),  # microseconds
            rtsp_url
        ], capture_output=True, text=True, timeout=timeout)
        
        latency = (time.time() - start_time) * 1000
        
        if result.returncode == 0:
            return {
                'connected': True,
                'latency_ms': round(latency, 2),
                'read_time_ms': round(latency, 2),
                'frame_size': None,
                'error': None
            }
        else:
            return {
                'connected': False,
                'latency_ms': None,
                'read_time_ms': None,
                'frame_size': None,
                'error': result.stderr or 'Connection failed'
            }
            
    except subprocess.TimeoutExpired:
        return {
            'connected': False,
            'latency_ms': None,
            'read_time_ms': None,
            'frame_size': None,
            'error': 'Connection timeout'
        }
    except FileNotFoundError:
        return {
            'connected': None,  # None means ffprobe not available
            'latency_ms': None,
            'read_time_ms': None,
            'frame_size': None,
            'error': 'ffprobe not found'
        }
    except Exception as e:
        return {
            'connected': False,
            'latency_ms': None,
            'read_time_ms': None,
            'frame_size': None,
            'error': str(e)
        }

def get_camera_status(camera: Dict[str, Any], use_ffprobe: bool = False) -> Dict[str, Any]:
    """
    Get comprehensive camera status including connection test
    
    Args:
        camera: Camera configuration dict
        use_ffprobe: Use ffprobe instead of OpenCV (if available)
    
    Returns:
        dict with status information
    """
    rtsp_url = camera.get('rtsp_source', '')
    enabled = camera.get('enabled', False)
    
    # Test connection
    if use_ffprobe:
        connection_result = test_rtsp_with_ffprobe(rtsp_url)
        # If ffprobe not available, fall back to OpenCV
        if connection_result['connected'] is None:
            connection_result = test_rtsp_connection(rtsp_url)
    else:
        connection_result = test_rtsp_connection(rtsp_url)
        # If OpenCV fails and ffprobe might be available, try it
        if not connection_result['connected'] and connection_result.get('error'):
            try:
                ffprobe_result = test_rtsp_with_ffprobe(rtsp_url)
                if ffprobe_result['connected'] is not None:
                    connection_result = ffprobe_result
            except:
                pass
    
    # Determine status
    if not enabled:
        status = 'DISABLED'
        status_badge = 'secondary'
    elif connection_result['connected']:
        status = 'CONNECTED'
        status_badge = 'success'
    else:
        status = 'DISCONNECTED'
        status_badge = 'danger'
    
    # Determine connection quality
    if connection_result['connected']:
        latency = connection_result.get('latency_ms', 0)
        if latency < 500:
            quality = 'EXCELLENT'
            quality_badge = 'success'
        elif latency < 1000:
            quality = 'GOOD'
            quality_badge = 'info'
        elif latency < 2000:
            quality = 'FAIR'
            quality_badge = 'warning'
        else:
            quality = 'POOR'
            quality_badge = 'danger'
    else:
        quality = 'UNKNOWN'
        quality_badge = 'secondary'
    
    return {
        'id': camera.get('id'),
        'name': camera.get('name'),
        'enabled': enabled,
        'status': status,
        'status_badge': status_badge,
        'connection': {
            'connected': connection_result['connected'],
            'latency_ms': connection_result.get('latency_ms'),
            'read_time_ms': connection_result.get('read_time_ms'),
            'frame_size': connection_result.get('frame_size'),
            'error': connection_result.get('error')
        },
        'quality': quality,
        'quality_badge': quality_badge,
        'last_checked': datetime.now().isoformat()
    }

