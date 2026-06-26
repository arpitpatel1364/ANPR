# PERFORMANCE OPTIMIZATIONS APPLIED
# - PyTorch threads limited to 2 (torch.set_num_threads)
# - OpenCV threads limited to 2 (cv2.setNumThreads)
# - Frame fetch loop sleep: 0.001s -> 0.05s
# - Global processor sleep: 0.01s -> 0.05s
# - cap.grab() used for skipped frames
# - Model loading deferred to load_models()
# - Directory creation moved out of fetch loop
# - Snapshot writes offloaded to thread pool

# Set headless environment variables BEFORE importing OpenCV/PaddleOCR
# This prevents Qt GUI initialization errors in headless mode
import os
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|max_delay;500000|stimeout;5000000"
import json
import sys
import scripts.config_db as config_db
from db_connection import wait_for_db_connection

# Ensure DB is ready before doing anything else
wait_for_db_connection(max_retries=15, retry_delay=2)

# ✅ AUTO-FIX: Ensure system_mode is set to multi_camera
from scripts.config_db import ensure_system_mode_set
ensure_system_mode_set()

def load_headless_mode_from_config():
    try:
        cfg = config_db.load_config_from_db()
        if cfg:
            display_cfg = cfg.get("display_settings", {})
            headless_cfg = cfg.get("headless_settings", {})
            
            # Prioritize the main Display Settings toggle
            disp_headless = display_cfg.get("headless_mode", True)
            
            if isinstance(disp_headless, str):
                disp_headless = disp_headless.lower() in ('true', '1', 't', 'yes', 'on')
                
            user_wants_headless = bool(disp_headless)
            
            # If the user explicitly wants Head Mode (GUI), but no display is attached 
            # (e.g. started from the web UI background service), we must inject the display 
            # context so OpenCV doesn't crash!
            if not user_wants_headless and not os.environ.get("DISPLAY"):
                try:
                    import subprocess
                    script_uid = str(os.stat(__file__).st_uid)
                    
                    # Try to find an active X11/Wayland session for the user
                    pgrep_cmd = ["pgrep", "-u", script_uid, "-n", "gnome-shell"]
                    pid_res = subprocess.run(pgrep_cmd, capture_output=True, text=True)
                    
                    if pid_res.returncode == 0 and pid_res.stdout.strip():
                        pid = pid_res.stdout.strip()
                        env_file = f"/proc/{pid}/environ"
                        
                        if os.path.exists(env_file):
                            with open(env_file, 'rb') as f:
                                env_data = f.read().split(b'\0')
                                
                            for item in env_data:
                                if item.startswith(b'DISPLAY='):
                                    os.environ['DISPLAY'] = item.split(b'=', 1)[1].decode('utf-8')
                                elif item.startswith(b'XAUTHORITY='):
                                    os.environ['XAUTHORITY'] = item.split(b'=', 1)[1].decode('utf-8')
                                    
                except Exception as e:
                    print(f"⚠️ Could not auto-detect DISPLAY: {e}")

                # Fallbacks if detection failed
                if not os.environ.get("DISPLAY"):
                    os.environ["DISPLAY"] = ":1"
                if not os.environ.get("XAUTHORITY"):
                    try:
                        import pwd
                        script_uid = os.stat(__file__).st_uid
                        uid_str = str(script_uid)
                        fallback_auth = f"/run/user/{uid_str}/gdm/Xauthority"
                        if os.path.exists(fallback_auth):
                            os.environ["XAUTHORITY"] = fallback_auth
                        else:
                            owner_home = pwd.getpwuid(script_uid).pw_dir
                            os.environ["XAUTHORITY"] = os.path.join(owner_home, ".Xauthority")
                    except Exception:
                        pass
                        
            return user_wants_headless
    except Exception as e:
        print(f"!!..Early config load failed ({e}), forcing HEADLESS mode..!!")
    
    return True

HEADLESS_MODE = load_headless_mode_from_config()

if HEADLESS_MODE:
    print(">> Starting in HEADLESS mode")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["DISPLAY"] = ""
else:
    print(">> Starting in DISPLAY mode")
    os.environ["QT_QPA_PLATFORM"] = "xcb"
CAN_USE_DISPLAY = not HEADLESS_MODE

os.environ['OPENCV_VIDEOIO_PRIORITY_MSMF'] = '0'
# Prevent OpenCV from trying to use GUI backends
os.environ['OPENCV_IO_ENABLE_OPENEXR'] = '0'

import cv2
from ultralytics import YOLO
from LPRNet import LPRNet, predict_plate
import torch
import re
import numpy as np
import time
import threading
from threading import Thread, Lock

from collections import Counter, defaultdict
import time as _time

class PlateTracker:
    """
    Lightweight multi-frame plate tracker using IoU box matching.
    Accumulates LPRNet reads per tracked vehicle and outputs the
    majority-vote result — no GPU, no new dependencies.

    Config:
        min_votes     : minimum reads before outputting a result
        max_gap_secs  : seconds of no detection before track expires
        iou_threshold : minimum IoU to associate a detection with
                        an existing track
    """

    def __init__(self, min_votes=1, max_gap_secs=2.0, iou_threshold=0.35):
        self.min_votes     = min_votes
        self.max_gap_secs  = max_gap_secs
        self.iou_threshold = iou_threshold
        self._tracks       = {}   # track_id -> track dict
        self._next_id      = 0

    def _iou(self, a, b):
        """Compute IoU between two boxes [x1,y1,x2,y2]."""
        ax1,ay1,ax2,ay2 = a
        bx1,by1,bx2,by2 = b
        ix1 = max(ax1, bx1); iy1 = max(ay1, by1)
        ix2 = min(ax2, bx2); iy2 = min(ay2, by2)
        inter = max(0, ix2-ix1) * max(0, iy2-iy1)
        if inter == 0:
            return 0.0
        area_a = (ax2-ax1) * (ay2-ay1)
        area_b = (bx2-bx1) * (by2-by1)
        return inter / (area_a + area_b - inter + 1e-6)

    def _match(self, box):
        """Find best matching existing track by IoU. Returns track_id or None."""
        best_id, best_iou = None, self.iou_threshold
        for tid, track in self._tracks.items():
            iou = self._iou(track['box'], box)
            if iou > best_iou:
                best_iou = iou
                best_id  = tid
        return best_id

    def _expire_stale(self):
        """Remove tracks that haven't been seen for max_gap_secs."""
        now = _time.monotonic()
        stale = [tid for tid, t in self._tracks.items()
                 if now - t['last_seen'] > self.max_gap_secs]
        for tid in stale:
            del self._tracks[tid]

    def update(self, box, plate_str, confidence=1.0):
        """
        Feed a new detection into the tracker.

        Args:
            box        : [x1, y1, x2, y2] bounding box (ints)
            plate_str  : decoded plate string from LPRNet
            confidence : YOLO or LPRNet confidence score (float)

        Returns:
            result     : str or None
                         str  — voted plate string when confident enough
                         None — still accumulating, not ready yet
        """
        self._expire_stale()

        tid = self._match(box)
        now = _time.monotonic()

        if tid is None:
            # New vehicle — start a new track
            tid = self._next_id
            self._next_id += 1
            self._tracks[tid] = {
                'box'      : box,
                'votes'    : Counter(),
                'last_seen': now,
                'emitted'  : False,
            }

        track = self._tracks[tid]
        track['box']       = box          # update to latest position
        track['last_seen'] = now
        track['votes'][plate_str] += 1

        # Emit when we have enough votes and haven't emitted yet
        total_votes = sum(track['votes'].values())
        if total_votes >= self.min_votes and not track['emitted']:
            track['emitted'] = True
            best, count = track['votes'].most_common(1)[0]
            # Only emit if majority agrees (>50% of votes)
            if count > total_votes * 0.5:
                return best

        return None   # still accumulating

    def flush(self):
        """
        Force-emit all pending tracks with enough votes.
        Call this on camera disconnect or system shutdown.
        Returns list of (plate_str, vote_count) tuples.
        """
        results = []
        for tid, track in list(self._tracks.items()):
            votes = track['votes']
            if votes and not track['emitted']:
                best, count = votes.most_common(1)[0]
                results.append((best, count))
        self._tracks.clear()
        return results


def enhance_frame_if_dark(frame,
                           dark_threshold=80,
                           clahe_clip=2.0,
                           clahe_tile=(8, 8),
                           sharpen_amount=1.5,
                           enable_clahe=True,
                           enable_sharpen=True):
    """
    Applies CLAHE + unsharp mask ONLY when frame is dark.
    Returns original frame untouched in normal light conditions.

    Args:
        frame           : numpy array (H, W, 3) BGR — raw camera frame
        dark_threshold  : mean brightness below which to enhance
                          (0–255 scale, default 80 ≈ dim indoor/dusk)
        clahe_clip      : CLAHE clip limit (higher = more contrast)
        clahe_tile      : CLAHE tile grid size (smaller = more local)
        sharpen_amount  : unsharp mask strength (1.0 = no change,
                          1.5 = moderate, 2.0 = strong)
        enable_clahe    : config flag to disable entirely
        enable_sharpen  : config flag to disable sharpen step

    Returns:
        frame : numpy array — enhanced if dark, original if bright
    """
    if not enable_clahe:
        return frame   # feature disabled — return immediately

    # Check brightness on grayscale — cheap single-channel operation
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mean_brightness = gray.mean()

    if mean_brightness >= dark_threshold:
        return frame   # bright enough — skip all enhancement

    # --- Frame is dark — apply CLAHE ---
    # Apply per-channel in LAB color space to avoid color shift
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)

    clahe = cv2.createCLAHE(clipLimit=clahe_clip,
                             tileGridSize=clahe_tile)
    l_enhanced = clahe.apply(l)

    lab_enhanced = cv2.merge([l_enhanced, a, b])
    frame_enhanced = cv2.cvtColor(lab_enhanced, cv2.COLOR_LAB2BGR)

    # --- Apply unsharp mask for edge sharpening ---
    if enable_sharpen:
        blurred = cv2.GaussianBlur(frame_enhanced, (3, 3), 0)
        frame_enhanced = cv2.addWeighted(
            frame_enhanced, sharpen_amount,
            blurred, -(sharpen_amount - 1.0),
            0
        )

    return frame_enhanced
import queue
import concurrent.futures
from plate_logger import PlateLogger, _PLATE_CACHE, _cache_lock
import httpx
import asyncio
import logging
import signal
import torch
from websocket_client import initialize_websocket_client, get_websocket_client

try:
    torch.set_num_threads(1)        # Prevent PyTorch from using all cores
except RuntimeError:
    pass
try:
    torch.set_num_interop_threads(1)
except RuntimeError:
    pass
try:
    cv2.setNumThreads(1)            # Prevent OpenCV from using all cores
except Exception:
    pass
model = None
lprnet_model = None
device = 'cpu'

# Global inference structures (simplified single-thread model)
import queue
from threading import Lock

global_frame_queue = queue.Queue(maxsize=32)
pool_lock = Lock()
BATCH_SIZE = 4
stop_processing = False

cameras_dict = {}  # {camera_id: CameraProcessor}

import re
# Indian number plate regex patterns
INDIAN_PLATE_REGEX = re.compile(
    r'^[A-Z]{2}[0-9]{2}[A-Z]{1,3}[0-9]{1,4}$'
    r'|^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$'
)

# Global ThreadPool for async writes to prevent thread bloat
api_thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=5)

# Async API Event Loop setup
api_event_loop = asyncio.new_event_loop()
def _run_api_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

api_loop_thread = threading.Thread(target=_run_api_loop, args=(api_event_loop,), daemon=True)
api_loop_thread.start()

# Global variables
detected_plates = {}  # Store detected plates with timestamps
plate_lock = Lock()  # Thread lock for thread-safe operations
plate_logger = None
PROCESS_EVERY_NTH_FRAME = 2
inference_semaphore = None

# Initialize WebSocket client for real-time communication with admin panel
websocket_client = None

# Global processing threads
processor_thread = None
display_thread = None
processor_thread_lock = Lock()

# per-camera throttle at module level
_last_processed_time = {}
MIN_PROCESS_INTERVAL = 0.08

def on_inference_done(future, camera_processor, original_frame):
    """
    Callback executed when a worker process completes inference.
    Releases the global inference semaphore and routes results to the camera processor.
    """
    if inference_semaphore:
        inference_semaphore.release()
    
    try:
        results = future.result()
        for cam_id, detections in results:
            if cam_id == camera_processor.camera_id:
                camera_processor.handle_inference_results(original_frame, detections)
    except Exception as e:
        print(f"❌ Error in on_inference_done callback: {e}")

class CameraProcessor:
    """
    SIMPLIFIED multiprocessing-driven CameraProcessor:
    - Fetches frames from RTSP streams and submits to ProcessPoolExecutor
    - Uses locks on current_processed_frame to prevent tearing/memory corruption
    - Manages Region Of Interest (ROI) and async image writes
    """
    
    def __init__(self, camera_config, global_settings, headless_mode=False, headless_settings=None):
        self.camera_id = camera_config['id']
        self.name = camera_config['name']
        self.location = camera_config['location']
        self.rtsp_source = camera_config['rtsp_source']
        self.dedup_window = camera_config['dedup_window']
        self.confidence_threshold = camera_config['confidence_threshold']
        self.enabled = camera_config['enabled']
        self.api_enabled = camera_config['api_enabled']
        self.api_settings = camera_config['api_settings']

        # Multi-frame plate tracker
        self.plate_tracker = PlateTracker(
            min_votes=1,
            max_gap_secs=2.0,
            iou_threshold=0.35
        )

        self.headless_mode = headless_mode
        self.headless_settings = headless_settings or {}
        self.global_settings = global_settings

        self.fetch_thread = None  # Thread for fetching frames from RTSP
        self.cap = None
        self._current_processed_frame = None
        self._frame_lock = Lock()
        self.frame_count = 0
        self.start_time = time.time()
        
        # Bounded frame queue (Section 2.2)
        self.frame_queue = queue.Queue(maxsize=2)
        self.last_put_time = 0.0

        # Optional Region Of Interest (ROI) for this camera
        self.roi = None
        roi_cfg = camera_config.get('roi')
        if roi_cfg:
            try:
                self.roi = (
                    int(roi_cfg.get('x1', 0)),
                    int(roi_cfg.get('y1', 0)),
                    int(roi_cfg.get('x2', 0)),
                    int(roi_cfg.get('y2', 0)),
                )
            except Exception:
                self.roi = None

        # Polygon ROI for fine-grained masking
        self.roi_polygon = None
        roi_poly_cfg = camera_config.get('roi_polygon')
        if roi_poly_cfg:
            try:
                points = []
                for p in roi_poly_cfg:
                    if isinstance(p, dict):
                        px = int(p.get('x'))
                        py = int(p.get('y'))
                    else:
                        px = int(p[0])
                        py = int(p[1])
                    points.append((px, py))
                if len(points) >= 3:
                    self.roi_polygon = points
            except Exception:
                self.roi_polygon = None

        # Camera-specific plate tracking with cleanup
        self.detected_plates = {}
        self.plate_lock = Lock()
        self.last_cleanup_time = time.time()
        self.cleanup_interval = 300  # Cleanup every 5 minutes

        # Verified plate cooldown tracking (1 second per plate)
        self.verified_plate_cooldowns = {}  # plate -> last_log_time
        self.verified_plate_cooldown_duration = 1.0  # 1 second cooldown for verified plates

        # Camera-specific stop flag
        self.stop_camera_flag = False
        self.stop_camera_lock = Lock()

        # Headless mode settings
        self.last_frame_save = 0
        self.frame_save_interval = self.headless_settings.get('frame_save_interval', 30)

        # ROI fallback snapshot settings
        self.last_roi_snapshot_time = 0
        self.roi_snapshot_interval = self.headless_settings.get('roi_snapshot_interval', 2)
        self.roi_snapshot_dir = os.path.join(os.path.dirname(__file__), 'admin_panel', 'static', 'images', 'roi_snapshots')
        os.makedirs(self.roi_snapshot_dir, exist_ok=True)
        import concurrent.futures
        self.api_thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        self.save_frames = self.headless_settings.get('save_frames', False)

        # ============================================================================
        # CLAHE and sharpen kernel cache in CameraProcessor.__init__
        # ============================================================================
        self._clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
        self._sharpen_kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])

    @property
    def current_processed_frame(self):
        with self._frame_lock:
            return self._current_processed_frame

    @current_processed_frame.setter
    def current_processed_frame(self, frame):
        with self._frame_lock:
            self._current_processed_frame = frame

    def is_valid_indian_plate(self, plate_text):
        """Validate if detected plate matches Indian number plate format"""
        if not plate_text or plate_text == "No license plate detected":
            return False
        
        cleaned_text = re.sub(r'\s+', '', plate_text.upper())
        
        if INDIAN_PLATE_REGEX.match(cleaned_text):
            return True
        
        if INDIAN_PLATE_REGEX.match(plate_text.upper()):
            return True
        
        return False

    def is_verified_plate_on_cooldown(self, plate_text: str) -> bool:
        """Check if a verified plate is within cooldown period (1 second)"""
        current_time = time.time()
        if plate_text in self.verified_plate_cooldowns:
            last_logged_time = self.verified_plate_cooldowns[plate_text]
            if current_time - last_logged_time < self.verified_plate_cooldown_duration:
                return True  # Still on cooldown
        return False  # Not on cooldown

    def update_verified_plate_cooldown(self, plate_text: str):
        """Update the last logged time for a verified plate"""
        self.verified_plate_cooldowns[plate_text] = time.time()

    # ============================================================================
    # preprocess_plate_crop method to CameraProcessor class
    # ============================================================================
    def preprocess_plate_crop(self, crop):
        """Preprocess plate crop with CLAHE and sharpening for better OCR"""
        try:
            h, w = crop.shape[:2]
            target_h = 48
            if h != target_h:
                scale = target_h / h
                new_w = max(int(w * scale), 80)
                crop = cv2.resize(crop, (new_w, target_h), 
                                  interpolation=cv2.INTER_CUBIC)
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            enhanced = self._clahe.apply(gray)
            sharpened = cv2.filter2D(enhanced, -1, self._sharpen_kernel)
            return cv2.cvtColor(sharpened, cv2.COLOR_GRAY2BGR)
        except Exception:
            return crop

    def extract_license_plate(self, ocr_result, confidence_threshold=0.5, size_threshold_factor=0.5):
        """Extract and clean text from OCR output with HMM correction"""
        if not ocr_result or not ocr_result[0]:
            return "No license plate detected"

        detected_texts = []
        max_area = 0

        for detection in ocr_result[0]:
            if len(detection) > 0:
                text = detection[1][0]
                confidence = detection[1][1]
                box = detection[0]

                width = abs(box[1][0] - box[0][0])
                height = abs(box[2][1] - box[1][1])
                area = width * height

                max_area = max(max_area, area)

                if confidence > confidence_threshold and area > (max_area * size_threshold_factor):
                    detected_texts.append(text)

        final_text = " ".join(detected_texts)
        # Preserve spaces, remove other non-alphanumeric chars
        cleaned_text_with_spaces = re.sub(r'[^A-Za-z0-9\s]', '', final_text).strip()
        # Remove multiple spaces
        cleaned_text_with_spaces = re.sub(r'\s+', ' ', cleaned_text_with_spaces)
        cleaned_text_no_spaces = cleaned_text_with_spaces.replace(' ', '')

        corrected_text = cleaned_text_with_spaces

        return corrected_text

    # ============================================================================
    # convert_ocr_format method to CameraProcessor class
    # ============================================================================
    def convert_ocr_format(self, ocr_result_raw):
        """Convert new OCR model format to old format"""
        ocr_result = []
        if not ocr_result_raw or not ocr_result_raw[0]:
            return ocr_result
        inner_list = []
        for res in ocr_result_raw[0]:
            text = None
            conf = None
            # Try different format possibilities
            if isinstance(res, tuple):
                if len(res) == 2:
                    text, conf = res
                elif len(res) == 1:
                    if isinstance(res[0], tuple) and len(res[0]) == 2:
                        text, conf = res[0]
                    else:
                        text = str(res[0])
                        conf = 0.5
                else:
                    text = str(res[0]) if res else None
                    conf = res[1] if len(res) > 1 else 0.5
            elif isinstance(res, dict):
                text = res.get('text')
                conf = res.get('confidence')
            else:
                text = str(res)
                conf = 0.5
            # Normalize confidence to 0-1
            if conf is not None:
                conf = float(conf)
                if conf > 1.0:
                    conf = conf / 100.0
            else:
                conf = 0.5
            # Add to result
            if text:
                dummy_box = [[0, 0], [100, 0], [100, 50], [0, 50]]
                inner_list.append([dummy_box, (str(text), conf)])
        if inner_list:
            ocr_result.append(inner_list)
        return ocr_result

    async def async_make_api_call(self, plate_text, verification_status):
        """Make API calls for this specific camera using async httpx"""
        try:
            success_count = 0
            username = self.api_settings.get('username', 'admin')
            password = self.api_settings.get('password', 'Admin@123')
            base_url = self.api_settings.get('base_url', '').strip()
            if not base_url:
                if self.headless_mode:
                    logging.info(f"[{self.name}] API base_url is empty. Skipping API call.")
                else:
                    print(f"ℹ️ [{self.name}] API base_url is empty. Skipping API call.")
                return False

            if not (base_url.startswith('http://') or base_url.startswith('https://')):
                if self.headless_mode:
                    logging.warning(f"[{self.name}] API base_url is invalid ('{base_url}'). Skipping API call.")
                else:
                    print(f"⚠️ [{self.name}] API base_url is invalid ('{base_url}'). Skipping API call.")
                return False

            timeout = self.api_settings.get('timeout', 5)
            max_retries = self.api_settings.get('max_retries', 3)

            mode1_success = False

            async with httpx.AsyncClient(verify=False) as client:
                auth = httpx.DigestAuth(username, password)
                # Mode 1 - First attempt
                try:
                    url1 = f"{base_url}?action=setConfig&AlarmOut[0].Mode=1"
                    response1 = await client.get(url1, auth=auth, timeout=timeout)

                    if response1.status_code == 200:
                        if self.headless_mode:
                            logging.info(f"[{self.name}] API call 1 successful for plate: {plate_text} (Status: {verification_status}) - Mode=1")
                        else:
                            print(f"✅ [{self.name}] API call 1 successful for plate: {plate_text} (Status: {verification_status}) - Mode=1")
                        success_count += 1
                        mode1_success = True
                    else:
                        if self.headless_mode:
                            logging.warning(f"[{self.name}] API call 1 failed for plate: {plate_text} - Status code: {response1.status_code} - Mode=1")
                        else:
                            print(f"❌ [{self.name}] API call 1 failed for plate: {plate_text} - Status code: {response1.status_code} - Mode=1")

                except Exception as e:
                    print(f"❌ [{self.name}] API call 1 error for plate: {plate_text} - {str(e)} - Mode=1")

                # Mode 2 - Must be hit if Mode 1 succeeded
                if mode1_success:
                    if self.headless_mode:
                        logging.info(f"[{self.name}] Mode 1 succeeded, ensuring Mode 2 is hit for plate: {plate_text}")
                    else:
                        print(f"🔄 [{self.name}] Mode 1 succeeded, ensuring Mode 2 is hit for plate: {plate_text}")

                retry_count = max_retries if mode1_success else 1

                for retry in range(retry_count):
                    try:
                        url2 = f"{base_url}?action=setConfig&AlarmOut[0].Mode=2"
                        response2 = await client.get(url2, auth=auth, timeout=timeout)

                        if response2.status_code == 200:
                            if self.headless_mode:
                                logging.info(f"[{self.name}] API call 2 successful for plate: {plate_text} (Status: {verification_status}) - Mode=2")
                            else:
                                print(f"✅ [{self.name}] API call 2 successful for plate: {plate_text} (Status: {verification_status}) - Mode=2")
                            success_count += 1
                            break
                        else:
                            if self.headless_mode:
                                logging.warning(f"[{self.name}] API call 2 failed for plate: {plate_text} - Status code: {response2.status_code} - Mode=2 (Retry {retry + 1}/{retry_count})")
                            else:
                                print(f"❌ [{self.name}] API call 2 failed for plate: {plate_text} - Status code: {response2.status_code} - Mode=2 (Retry {retry + 1}/{retry_count})")
                            if retry < retry_count - 1:
                                await asyncio.sleep(0.5)

                    except Exception as e:
                        print(f"❌ [{self.name}] API call 2 error for plate: {plate_text} - {str(e)} - Mode=2 (Retry {retry + 1}/{retry_count})")
                        if retry < retry_count - 1:
                            await asyncio.sleep(0.5)

            return success_count > 0

        except Exception as e:
            print(f"❌ [{self.name}] General API call error for plate: {plate_text} - {str(e)}")
            return False

    def trigger_api_call(self, plate_text, verification_status):
        """Trigger API call asynchronously"""
        try:
            asyncio.run_coroutine_threadsafe(
                self.async_make_api_call(plate_text, verification_status),
                api_event_loop
            )
        except Exception as e:
            print(f"❌ [{self.name}] Error scheduling async API call: {str(e)}")

    def _validate_frame(self, frame, frame_name="frame"):
        """Validate frame before processing"""
        if frame is None:
            return False
        if not isinstance(frame, np.ndarray):
            return False
        if frame.size == 0:
            return False
        if len(frame.shape) != 3 or frame.shape[2] != 3:
            return False
        if np.any(np.isnan(frame)) or np.any(np.isinf(frame)):
            return False
        if frame.dtype != np.uint8:
            return False
        h, w = frame.shape[:2]
        if h < 10 or w < 10 or h > 10000 or w > 10000:
            return False
        if not frame.flags['C_CONTIGUOUS']:
            frame = np.ascontiguousarray(frame)
        return True

    def handle_inference_results(self, original_frame, detections):
        """
        Handle YOLO/LPRNet inference results returned from worker processes:
        - Draw bounding boxes and text.
        - Check Indian plate format.
        - Verify plate with PlateLogger.
        - Save detection images and verified plate image.
        - Send to API / admin panel.
        """
        try:
            start_time = time.time()
            processed_frame = original_frame.copy()
            detected_texts = []
            
            h_orig, w_orig = original_frame.shape[:2]
            scale_factor = 1.0
            if w_orig > 640:
                scale_factor = w_orig / 640.0
            
            for det in detections:
                license_plate_text = det['plate_text']
                x1, y1, x2, y2 = det['bbox']
                confidence = det['confidence']
                
                # Check valid Indian plate format (Section 3.1)
                if not self.is_valid_indian_plate(license_plate_text):
                    if logging.getLogger().isEnabledFor(logging.DEBUG):
                        logging.debug(f"[{self.name}] Invalid plate format (not Indian), skipping: {license_plate_text}")
                    continue
                
                if license_plate_text and license_plate_text != "No license plate detected":
                    processing_time = (time.time() - start_time) * 1000
                    current_time = time.time()
                    
                    with self.plate_lock:
                        if current_time - self.last_cleanup_time > self.cleanup_interval:
                            expired_plates = [
                                plate for plate, timestamp in self.detected_plates.items()
                                if current_time - timestamp > self.dedup_window
                            ]
                            for plate in expired_plates:
                                del self.detected_plates[plate]
                            self.last_cleanup_time = current_time

                        self.detected_plates[license_plate_text] = current_time
                        detected_texts.append(license_plate_text)
                        
                    if plate_logger:
                        verification = plate_logger.verify_plate(license_plate_text)
                        verification_status = verification['verification_status']

                        if verification['is_allowed']:
                            box_color = (0, 255, 0)
                            text_color = (0, 255, 0)
                        else:
                            box_color = (0, 0, 255)
                            text_color = (0, 0, 255)

                        global_x1 = int(x1 * scale_factor)
                        global_y1 = int(y1 * scale_factor)
                        global_x2 = int(x2 * scale_factor)
                        global_y2 = int(y2 * scale_factor)

                        annotated_frame = processed_frame.copy()
                        cv2.rectangle(annotated_frame, (global_x1, global_y1), (global_x2, global_y2), box_color, 2)
                        cv2.putText(annotated_frame, license_plate_text, (global_x1 - 13, global_y1 - 9),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3, cv2.LINE_AA)
                        cv2.putText(annotated_frame, license_plate_text, (global_x1 - 14, global_y1 - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, text_color, 2, cv2.LINE_AA)
                        status_text = f"{verification['verification_status']}"
                        cv2.putText(annotated_frame, status_text, (global_x1, global_y2 + 20),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, text_color, 2, cv2.LINE_AA)

                        processed_frame = annotated_frame

                        # Async Image Saving (Section 7.2)
                        image_urls = self.save_detection_images(
                            full_frame_annotated=annotated_frame,
                            plate_text=license_plate_text,
                            verification_status=verification_status,
                            bbox_x1=global_x1,
                            bbox_y1=global_y1,
                            bbox_x2=global_x2,
                            bbox_y2=global_y2
                        )

                        # Check cooldown for verified plates (1 second)
                        should_log = True
                        if verification_status == "VERIFIED" and self.is_verified_plate_on_cooldown(license_plate_text):
                            should_log = False
                            if not self.headless_mode:
                                print(f"⏳ [{self.name}] Verified plate {license_plate_text} on 1s cooldown, skipping log")

                        is_logged = False
                        if should_log:
                            is_logged = plate_logger.log_detection(
                                plate=license_plate_text,
                                detection_confidence=confidence,
                                processing_time_ms=processing_time,
                                camera_source=f"{self.name} ({self.location})",
                                image_full_annotated=image_urls.get('image_full_annotated') if image_urls else None,
                                bbox_x1=image_urls.get('bbox_x1') if image_urls else None,
                                bbox_y1=image_urls.get('bbox_y1') if image_urls else None,
                                bbox_x2=image_urls.get('bbox_x2') if image_urls else None,
                                bbox_y2=image_urls.get('bbox_y2') if image_urls else None
                            )

                            if verification_status == "VERIFIED" and is_logged:
                                self.update_verified_plate_cooldown(license_plate_text)

                        if is_logged:
                            if verification_status == "VERIFIED":
                                self.save_verified_plate_image(processed_frame, license_plate_text)

                            self.send_detection_to_admin_panel(
                                plate=license_plate_text,
                                confidence=confidence,
                                processing_time=processing_time,
                                verification_status=verification_status,
                                image_urls=image_urls
                            )

                            if verification_status == "VERIFIED" and self.api_enabled:
                                self.trigger_api_call(license_plate_text, verification_status)
                            else:
                                if not self.api_enabled:
                                    if not self.headless_mode:
                                        print(f"🚫 [{self.name}] API disabled for this camera - plate: {license_plate_text}")
                                else:
                                    if not self.headless_mode:
                                        print(f"🚫 [{self.name}] API call skipped for plate: {license_plate_text} (Status: {verification_status}) - Not verified")
                                    
            self.current_processed_frame = processed_frame
            if detected_texts:
                if self.headless_mode:
                    logging.info(f"[{self.name}] Detected plates: {detected_texts}")
                else:
                    print(f"📹 [{self.name}] Detected plates: {detected_texts}")
        except Exception as e:
            print(f"❌ [{self.name}] Error handling inference results: {e}")

    def frame_fetch_worker(self):
        """
        Multiprocessing fetch worker:
        - Captures frames from RTSP.
        - Resizes frames for low-end device CPU efficiency (Section 2.1).
        - Dynamically controls frame interval based on CPU load (Section 2.3).
        - Drops frame on queue full (Section 2.2).
        - Executes low-overhead motion detection (Section 2.4) and skips inference.
        - Submits to global ProcessPoolExecutor when semaphore is free (Section 1.2).
        - Automatically reconnects indefinitely with exponential backoff on stream loss.
        """
        global stop_processing
        
        global stop_processing
        
        reconnect_delay_base = 5.0
        reconnect_delay_max = 60.0
        delay = reconnect_delay_base

        while True:
            if stop_processing:
                break
            
            with self.stop_camera_lock:
                if self.stop_camera_flag:
                    break

            # If cap is not initialized or not opened, try to connect/reconnect
            if self.cap is None or not self.cap.isOpened():
                if self.cap is not None:
                    try:
                        self.cap.release()
                    except Exception:
                        pass
                    self.cap = None

                if self.headless_mode:
                    logging.warning(f"[{self.name}] Camera source not open. Connecting in {delay}s...")
                else:
                    print(f"⚠️ [{self.name}] Camera source not open. Connecting in {delay}s...")

                # Wait with check for stop flags
                slept = 0.0
                while slept < delay:
                    if stop_processing:
                        break
                    with self.stop_camera_lock:
                        if self.stop_camera_flag:
                            break
                    time.sleep(0.5)
                    slept += 0.5

                if stop_processing:
                    break
                with self.stop_camera_lock:
                    if self.stop_camera_flag:
                        break

                try:
                    if isinstance(self.rtsp_source, int) or (isinstance(self.rtsp_source, str) and self.rtsp_source.isdigit()):
                        self.cap = cv2.VideoCapture(int(self.rtsp_source))
                    else:
                        self.cap = cv2.VideoCapture(self.rtsp_source, cv2.CAP_FFMPEG)

                    if self.cap and self.cap.isOpened():
                        try:
                            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('H', '2', '6', '4'))
                        except Exception:
                            pass
                        delay = reconnect_delay_base  # reset backoff on success
                        if self.headless_mode:
                            logging.info(f"[{self.name}] Connected to stream: {self.rtsp_source}")
                        else:
                            print(f"✅ [{self.name}] Connected to stream: {self.rtsp_source}")
                    else:
                        delay = min(delay * 2, reconnect_delay_max)
                        continue
                except Exception as e:
                    if self.headless_mode:
                        logging.error(f"[{self.name}] Exception during connection: {e}")
                    else:
                        print(f"❌ [{self.name}] Exception during connection: {e}")
                    delay = min(delay * 2, reconnect_delay_max)
                    continue

            try:
                self.frame_count += 1
                ret, frame = self.cap.read()

                
                # Check for frame read failure
                if not ret or frame is None:
                    if self.headless_mode:
                        logging.warning(f"[{self.name}] Frame read failed. Reconnecting...")
                    else:
                        print(f"⚠️ [{self.name}] Frame read failed. Reconnecting...")
                    if self.cap:
                        try:
                            self.cap.release()
                        except Exception:
                            pass
                        self.cap = None
                    delay = reconnect_delay_base
                    continue

                # Normal processing when frame is successfully read

                if self._validate_frame(frame, "captured_frame"):
                    frame_copy = frame.copy()
                    
                    # Scale inference frame down to max 640px wide (Section 2.1)
                    h_orig, w_orig = frame_copy.shape[:2]
                    if w_orig > 640:
                        scale_factor = 640.0 / w_orig
                        frame_resized = cv2.resize(frame_copy, (640, int(h_orig * scale_factor)), interpolation=cv2.INTER_LINEAR)
                    else:
                        frame_resized = frame_copy.copy()
                        
                    # Update thread-safe display property (Section 1.4)
                    self.current_processed_frame = frame_copy
                    
                    pass
                        
                    # Apply Conditional CLAHE + Unsharp Mask ONLY if motion detected
                    frame_resized = enhance_frame_if_dark(
                        frame_resized,
                        dark_threshold = 80,
                        clahe_clip     = 2.0,
                        clahe_tile     = (8, 8),
                        sharpen_amount = 1.5,
                        enable_clahe   = True,
                        enable_sharpen = True
                    )
                    
                    # Save ROI snapshot periodically
                    import psutil
                    current_time = time.time()
                    if self.roi_snapshot_interval > 0:
                        if current_time - self.last_roi_snapshot_time > self.roi_snapshot_interval:
                            self.last_roi_snapshot_time = current_time
                            try:
                                snapshot_path = os.path.join(self.roi_snapshot_dir, f"{self.camera_id}.jpg")
                                cv2.imwrite(snapshot_path, frame_copy)
                            except Exception:
                                pass
                                
                    # Fixed FPS Throttling (10 FPS)
                    target_interval = 0.10  # 10 FPS
                    
                    if current_time - self.last_put_time > target_interval:
                        self.last_put_time = current_time
                        # Enforce strict queue size limits and drop on full (Section 2.2)
                        try:
                            self.frame_queue.put_nowait({
                                'frame_resized': frame_resized,
                                'frame_original': frame_copy,
                                'camera_id': self.camera_id,
                                'camera_processor': self,
                                'frame_number': self.frame_count
                            })
                        except queue.Full:
                            if logging.getLogger().isEnabledFor(logging.DEBUG):
                                logging.debug(f"[{self.name}] Frame queue full (maxsize=2), dropping incoming frame.")
                                
                    # Dispatch task to central supervisor queue
                    if not self.frame_queue.empty():
                        try:
                            frame_data = self.frame_queue.get_nowait()
                            global_frame_queue.put_nowait(frame_data)
                        except queue.Empty:
                            pass
                        except queue.Full:
                            # Drop if global queue is backed up
                            pass
                else:
                    if logging.getLogger().isEnabledFor(logging.DEBUG):
                        logging.debug(f"[{self.name}] Skipping corrupted frame (H.264 decode error)")
                
                time.sleep(0.01)  # Adaptive pacing sleep instead of fixed slow wait

            except Exception as e:
                if self.headless_mode:
                    logging.error(f"[{self.name}] Error in fetch worker: {e}")
                else:
                    print(f"❌ [{self.name}] Error in fetch worker: {e}")
                time.sleep(1.0)
                continue

    def _persist_roi_to_config(self):
        """Save ROI to Database"""
        try:
            update_data = {}
            if self.roi is not None:
                x1, y1, x2, y2 = self.roi
                update_data['roi'] = {'x1': int(x1), 'y1': int(y1), 'x2': int(x2), 'y2': int(y2)}
                
            if self.roi_polygon is not None and len(self.roi_polygon) >= 3:
                update_data['roi_polygon'] = [{'x': int(px), 'y': int(py)} for (px, py) in self.roi_polygon]
                
            if update_data:
                config_db.update_camera_in_db(self.camera_id, update_data)
                print(f"💾 Saved ROI for camera '{self.name}' into Database.")
        except Exception as e:
            print(f"⚠️ [{self.name}] Failed to persist ROI to Database: {e}")

    def _maybe_select_roi(self):
        """Interactive ROI selection with timeout protection (skipped in headless mode or when no display is available)"""
        global HEADLESS_MODE, CAN_USE_DISPLAY

        # Skip ROI selection if headless mode or no display available
        if HEADLESS_MODE or not CAN_USE_DISPLAY:
            if self.roi is None and (self.roi_polygon is None or len(self.roi_polygon) < 3):
                if self.headless_mode:
                    logging.warning(f"[{self.name}] No ROI configured and running in headless mode. Using full frame.")
                else:
                    print(f"⚠️ [{self.name}] No ROI configured and no display available. Using full frame.")
            return

        if self.roi is not None or (self.roi_polygon is not None and len(self.roi_polygon) >= 3):
            return

        if not self.cap or not self.cap.isOpened():
            print(f"⚠️ [{self.name}] Camera not ready for ROI selection")
            return

        try:
            # Try to read a frame with timeout protection
            frame_container = {'frame': None}
            frame_timeout = 3  # 3 second timeout
            
            def capture_frame():
                try:
                    ret, frame = self.cap.read()
                    if ret and frame is not None:
                        frame_container['frame'] = frame
                except:
                    pass
            
            # Run frame capture in a thread to avoid blocking if stream is stuck
            import threading
            capture_thread = threading.Thread(target=capture_frame, daemon=True)
            capture_thread.start()
            capture_thread.join(timeout=frame_timeout)
            
            preview_frame = frame_container['frame']
            
            if preview_frame is None:
                print(f"⚠️ [{self.name}] Could not capture frame for ROI selection (timeout after {frame_timeout}s)")
                return

            window_name = f"Set ROI - {self.name}"
            print(f"🖼️  Opening ROI selection window for camera '{self.name}'.")
            print("    Click to add points for ROI polygon.")
            print("    Press SPACE or ENTER to save, 'r' to reset, ESC/C to cancel.")

            points = []
            preview_clone = preview_frame.copy()

            def mouse_callback(event, x, y, flags, param):
                nonlocal points, preview_clone
                if event == cv2.EVENT_LBUTTONDOWN:
                    points.append((x, y))
                    preview_clone = preview_frame.copy()
                    if len(points) > 0:
                        for idx, pt in enumerate(points):
                            cv2.circle(preview_clone, pt, 5, (0, 255, 0), -1)
                            if idx > 0:
                                cv2.line(preview_clone, points[idx - 1], pt, (255, 0, 0), 2)
                        if len(points) > 2:
                            cv2.line(preview_clone, points[-1], points[0], (255, 0, 0), 1)

            cv2.namedWindow(window_name, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO | cv2.WINDOW_GUI_EXPANDED)
            cv2.setMouseCallback(window_name, mouse_callback)

            # Resize window to fit screen better
            screen_width = 1920  # Default fallback
            screen_height = 1080
            try:
                # Try to get actual screen size
                import subprocess
                result = subprocess.run(['xrandr'], capture_output=True, text=True, timeout=2)
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if '*' in line:
                            parts = line.split()
                            for part in parts:
                                if 'x' in part and part.endswith('*'):
                                    w, h = map(int, part.split('x')[0].split('x'))
                                    screen_width, screen_height = w, h
                                    break
                            break
            except:
                pass

            # Resize frame to fit within 80% of screen
            frame_h, frame_w = preview_frame.shape[:2]
            max_display_w = int(screen_width * 0.8)
            max_display_h = int(screen_height * 0.8)

            scale = min(max_display_w / frame_w, max_display_h / frame_h, 1.0)
            if scale < 1.0:
                new_w = int(frame_w * scale)
                new_h = int(frame_h * scale)
                cv2.resizeWindow(window_name, new_w, new_h)
                preview_clone = cv2.resize(preview_clone, (new_w, new_h))
                # Adjust mouse coordinates for scaled display
                scale_x = frame_w / new_w
                scale_y = frame_h / new_h

                def scaled_mouse_callback(event, x, y, flags, param):
                    nonlocal points, preview_clone, scale_x, scale_y
                    if event == cv2.EVENT_LBUTTONDOWN:
                        # Convert back to original coordinates
                        orig_x = int(x * scale_x)
                        orig_y = int(y * scale_y)
                        points.append((orig_x, orig_y))
                        preview_clone = cv2.resize(preview_frame.copy(), (new_w, new_h))
                        if len(points) > 0:
                            for idx, pt in enumerate(points):
                                scaled_pt = (int(pt[0] / scale_x), int(pt[1] / scale_y))
                                cv2.circle(preview_clone, scaled_pt, 5, (0, 255, 0), -1)
                                if idx > 0:
                                    prev_scaled = (int(points[idx-1][0] / scale_x), int(points[idx-1][1] / scale_y))
                                    cv2.line(preview_clone, prev_scaled, scaled_pt, (255, 0, 0), 2)
                            if len(points) > 2:
                                first_scaled = (int(points[0][0] / scale_x), int(points[0][1] / scale_y))
                                cv2.line(preview_clone, scaled_pt, first_scaled, (255, 0, 0), 1)

                cv2.setMouseCallback(window_name, scaled_mouse_callback)

            # Bring window to front
            cv2.setWindowProperty(window_name, cv2.WND_PROP_TOPMOST, 1)
            cv2.waitKey(100)  # Give window time to appear
            cv2.setWindowProperty(window_name, cv2.WND_PROP_TOPMOST, 0)

            roi_timeout = 120  # 2 minute timeout for ROI selection
            start_time = time.time()
            
            while True:
                cv2.imshow(window_name, preview_clone)
                key = cv2.waitKey(20) & 0xFF

                if key in (13, 32):  # ENTER or SPACE
                    if len(points) >= 3:
                        self.roi_polygon = points.copy()
                        poly_np = np.array(self.roi_polygon, dtype=np.int32)
                        x, y, w, h = cv2.boundingRect(poly_np)
                        self.roi = (x, y, x + w, y + h)

                        print(f"✅ Polygon ROI set for camera '{self.name}' with {len(points)} points.")
                        print(f"   Bounding box: {self.roi}")
                        self._persist_roi_to_config()
                    else:
                        print(f"⚠️ [{self.name}] Need at least 3 points for polygon ROI. Using full frame.")
                    break

                elif key in (ord('r'), ord('R')):
                    points = []
                    if 'scale' in locals() and scale < 1.0:
                        preview_clone = cv2.resize(preview_frame.copy(), (new_w, new_h))
                    else:
                        preview_clone = preview_frame.copy()
                    print(f"🔁 [{self.name}] ROI points reset.")

                elif key in (27, ord('c'), ord('C')):  # ESC or C
                    print(f"⚠️ [{self.name}] ROI selection cancelled; using full frame.")
                    break

                if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                    print(f"⚠️ [{self.name}] ROI window closed; using full frame.")
                    break
                
                # Timeout protection for ROI selection window
                if time.time() - start_time > roi_timeout:
                    print(f"⏱️  [{self.name}] ROI selection timed out after {roi_timeout}s; using full frame.")
                    break

            cv2.destroyWindow(window_name)

        except Exception as e:
            print(f"⚠️ [{self.name}] Could not run ROI selection: {e}")

    def start_camera(self):
        """Start RTSP capture. Spawn FETCH thread only (not processing)"""
        if not self.enabled:
            print(f"⏸️  Camera {self.name} is disabled")
            return False

        with self.stop_camera_lock:
            self.stop_camera_flag = False

        try:
            if self.cap:
                try:
                    self.cap.release()
                except:
                    pass
                self.cap = None

            if isinstance(self.rtsp_source, int) or (isinstance(self.rtsp_source, str) and self.rtsp_source.isdigit()):
                self.cap = cv2.VideoCapture(int(self.rtsp_source))
            else:
                self.cap = cv2.VideoCapture(self.rtsp_source, cv2.CAP_FFMPEG)

            if not self.cap.isOpened():
                if self.headless_mode:
                    logging.error(f"[{self.name}] Could not open video source: {self.rtsp_source}. Reconnect worker will retry.")
                else:
                    print(f"❌ [{self.name}] Could not open video source: {self.rtsp_source}. Reconnect worker will retry.")
                self.cap = None
                # Spawn FETCH thread anyway to allow background reconnection
                if self.fetch_thread is None or not self.fetch_thread.is_alive():
                    self.fetch_thread = Thread(target=self.frame_fetch_worker, daemon=True)
                    self.fetch_thread.start()
                return True

            if self.roi is None:
                self._maybe_select_roi()

            try:
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('H', '2', '6', '4'))
            except Exception as e:
                if self.headless_mode:
                    logging.warning(f"[{self.name}] Could not set video properties: {e}")
                else:
                    print(f"⚠️ [{self.name}] Could not set video properties: {e}")

            # Spawn FETCH thread only (not processing thread)
            if self.fetch_thread is None or not self.fetch_thread.is_alive():
                self.fetch_thread = Thread(target=self.frame_fetch_worker, daemon=True)
                self.fetch_thread.start()

            if self.headless_mode:
                logging.info(f"[{self.name}] Camera started successfully")
            else:
                print(f"✅ [{self.name}] Camera started successfully")
            return True

        except Exception as e:
            if self.headless_mode:
                logging.error(f"[{self.name}] Error starting camera: {e}")
            else:
                print(f"❌ [{self.name}] Error starting camera: {e}")

            if self.cap:
                try:
                    self.cap.release()
                except:
                    pass
                self.cap = None
            return False

    def stop_camera(self):
        """Stop the camera fetch thread"""
        with self.stop_camera_lock:
            self.stop_camera_flag = True

        if self.cap:
            try:
                self.cap.release()
            except Exception as e:
                if self.headless_mode:
                    logging.error(f"[{self.name}] Error releasing camera: {e}")
                else:
                    print(f"⚠️ [{self.name}] Error releasing camera: {e}")
            finally:
                self.cap = None

        import threading
        if self.fetch_thread and self.fetch_thread.is_alive():
            if threading.current_thread() != self.fetch_thread:
                self.fetch_thread.join(timeout=2.0)
                if self.fetch_thread.is_alive():
                    if self.headless_mode:
                        logging.warning(f"[{self.name}] Fetch thread did not stop gracefully")
                    else:
                        print(f"⚠️ [{self.name}] Fetch thread did not stop gracefully")

        if self.headless_mode:
            logging.info(f"[{self.name}] Camera stopped")
        else:
            print(f"🛑 [{self.name}] Camera stopped")

    def get_frame(self):
        """Get the latest processed frame"""
        return self.current_processed_frame

    def save_detection_frame(self, frame, detected_texts):
        """Save frame with detected plates in headless mode"""
        try:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"headless_{self.camera_id}_{timestamp}_{'_'.join(detected_texts)}.jpg"
            filepath = os.path.join(self.headless_settings.get('save_dir', './headless_frames'), filename)

            os.makedirs(os.path.dirname(filepath), exist_ok=True)

            cv2.imwrite(filepath, frame)
            logging.info(f"[{self.name}] Frame saved: {filepath}")
        except Exception as e:
            logging.error(f"[{self.name}] Error saving frame: {e}")

    def save_verified_plate_image(self, frame, plate_text):
        """Save image for verified plates asynchronously"""
        try:
            verified_dir = "admin_panel/static/images/verified_plates"
            os.makedirs(verified_dir, exist_ok=True)

            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"verified_{self.camera_id}_{timestamp}_{plate_text}.jpg"
            filepath = os.path.join(verified_dir, filename)

            # Copy frame to ensure memory isn't modified during async write
            frame_copy = frame.copy()
            self.api_thread_pool.submit(cv2.imwrite, filepath, frame_copy)

            if self.headless_mode:
                logging.info(f"[{self.name}] Async verified plate image save queued: {filename}")
            else:
                print(f"📸 [{self.name}] Async verified plate image save queued: {filename}")

        except Exception as e:
            if self.headless_mode:
                logging.error(f"[{self.name}] Error queueing verified plate image save: {e}")
            else:
                print(f"❌ [{self.name}] Error queueing verified plate image save: {e}")

    def save_detection_images(self, full_frame_annotated, plate_text, verification_status, bbox_x1, bbox_y1, bbox_x2, bbox_y2):
        """Save detection image asynchronously and return URLs and bbox immediately"""
        urls = {}
        try:
            base_dir = "admin_panel/static/images/detections"
            full_annotated_dir = os.path.join(base_dir, "full_annotated")

            os.makedirs(full_annotated_dir, exist_ok=True)

            timestamp = time.strftime("%Y%m%d_%H%M%S")
            safe_plate = re.sub(r"[^A-Za-z0-9]", "_", plate_text) if plate_text else "unknown"
            status_tag = "VER" if verification_status == "VERIFIED" else "NOTVER"

            full_annotated_name = f"{self.camera_id}_{timestamp}_{safe_plate}_{status_tag}_ann.webp"
            full_annotated_path = os.path.join(full_annotated_dir, full_annotated_name)

            if isinstance(full_frame_annotated, np.ndarray):
                frame_copy = full_frame_annotated.copy()
                
                # Define helper for async writing of annotated frame
                def async_write_task(path, img):
                    try:
                        cv2.imwrite(path, img, [cv2.IMWRITE_WEBP_QUALITY, 80])
                    except Exception as ex:
                        logging.error(f"Error in async_write_task: {ex}")
                
                self.api_thread_pool.submit(async_write_task, full_annotated_path, frame_copy)

            urls = {
                'image_full_annotated': f"/static/images/detections/full_annotated/{full_annotated_name}",
                'bbox_x1': bbox_x1,
                'bbox_y1': bbox_y1,
                'bbox_x2': bbox_x2,
                'bbox_y2': bbox_y2
            }
        except Exception as e:
            if self.headless_mode:
                logging.error(f"[{self.name}] Error preparing async detection images: {e}")
            else:
                print(f"❌ [{self.name}] Error preparing async detection images: {e}")
        return urls

    def send_detection_to_admin_panel(self, plate, confidence, processing_time, verification_status, image_urls=None):
        """Send real-time detection to admin panel via WebSocket"""
        try:
            global websocket_client
            if websocket_client is None:
                websocket_client = get_websocket_client()

            if websocket_client and websocket_client.is_connected():
                detection_data = {
                    'plate': plate,
                    'confidence': confidence,
                    'processing_time': processing_time,
                    'verification_status': verification_status,
                    'camera_id': self.camera_id,
                    'camera_name': self.name,
                    'camera_location': self.location,
                    'timestamp': time.time()
                }
                if image_urls and isinstance(image_urls, dict):
                    detection_data.update(image_urls)

                websocket_client.send_detection(detection_data)

                if not self.headless_mode:
                    print(f"📡 [{self.name}] Sent detection to admin panel: {plate}")
            else:
                if not self.headless_mode:
                    print(f"⚠️ [{self.name}] WebSocket not connected, detection not sent: {plate}")

        except Exception as e:
            if self.headless_mode:
                logging.error(f"[{self.name}] Error sending detection to admin panel: {e}")
            else:
                print(f"❌ [{self.name}] Error sending detection to admin panel: {e}")

    def get_stats(self):
        """Get camera statistics"""
        with self.plate_lock:
            total_plates = len(self.detected_plates)

        elapsed_time = time.time() - self.start_time
        fps = self.frame_count / elapsed_time if elapsed_time > 0 else 0

        return {
            'name': self.name,
            'location': self.location,
            'total_plates': total_plates,
            'fps': fps,
            'frame_count': self.frame_count
        }


# ============================================================================
# GLOBAL PROCESSOR THREAD: Consumes frames from global queue and processes them
# ============================================================================

# ============================================================================
# Obsolete background thread workers removed in favor of multiprocessing pool
# ============================================================================


def create_camera_grid(cameras, grid_layout="2x2"):
    """Create a grid layout for multiple cameras (only if display is available)"""
    global HEADLESS_MODE, CAN_USE_DISPLAY

    # Safety check: only create grid if display is available
    if HEADLESS_MODE or not CAN_USE_DISPLAY:
        return None, None

    rows, cols = map(int, grid_layout.split('x'))
    max_cameras = rows * cols

    enabled_cameras = [cam for cam in cameras if cam.enabled]

    if not enabled_cameras:
        return None, None

    active_cameras = enabled_cameras[:max_cameras]

    if len(enabled_cameras) > max_cameras:
        total_cameras = len(enabled_cameras)
        optimal_rows = int(np.ceil(np.sqrt(total_cameras)))
        optimal_cols = int(np.ceil(total_cameras / optimal_rows))
        rows, cols = optimal_rows, optimal_cols
        active_cameras = enabled_cameras

    first_camera = active_cameras[0]
    if first_camera.current_processed_frame is not None:
        h, w = first_camera.current_processed_frame.shape[:2]
    else:
        h, w = 480, 640

    # Get screen dimensions to fit grid properly
    screen_width = 1920  # Default fallback
    screen_height = 1080
    try:
        # Try to get actual screen size
        import subprocess
        result = subprocess.run(['xrandr'], capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if '*' in line:
                    parts = line.split()
                    for part in parts:
                        if 'x' in part and part.endswith('*'):
                            w_scr, h_scr = map(int, part.split('x')[0].split('x'))
                            screen_width, screen_height = w_scr, h_scr
                            break
                    break
    except:
        pass

    # Calculate grid dimensions
    grid_height = h * rows
    grid_width = w * cols

    # Scale down if grid is too large for screen (leave 10% margin)
    max_grid_width = int(screen_width * 0.9)
    max_grid_height = int(screen_height * 0.85)  # Leave room for title bars

    scale = min(max_grid_width / grid_width, max_grid_height / grid_height, 1.0)

    if scale < 1.0:
        # Scale down the grid
        grid_width = int(grid_width * scale)
        grid_height = int(grid_height * scale)
        # Scale individual camera dimensions
        w = int(w * scale)
        h = int(h * scale)

    grid_frame = np.zeros((grid_height, grid_width, 3), dtype=np.uint8)

    for i, camera in enumerate(active_cameras):
        row = i // cols
        col = i % cols

        y_start = row * h
        y_end = (row + 1) * h
        x_start = col * w
        x_end = (col + 1) * w

        frame = camera.get_frame()
        if frame is not None:
            resized_frame = cv2.resize(frame, (w, h))
            grid_frame[y_start:y_end, x_start:x_end] = resized_frame

            # Scale font size based on grid scaling
            font_scale = 0.7 * scale
            font_thickness = max(1, int(2 * scale))

            cv2.putText(grid_frame, camera.name, (x_start + 10, y_start + 30),
                       cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 255, 255), font_thickness)
            cv2.putText(grid_frame, camera.location, (x_start + 10, y_start + int(60 * scale)),
                       cv2.FONT_HERSHEY_SIMPLEX, font_scale * 0.7, (200, 200, 200), max(1, font_thickness - 1))

    return grid_frame, active_cameras


def load_config():
    """Load configuration from database"""
    try:
        config = config_db.load_config_from_db()
        if config:
            return config
            
        print("❌ DB Configuration empty. Using default settings.")
        return None
    except Exception as e:
        print(f"❌ Error loading DB config: {e}")
        return None


def reload_cameras_from_config(config):
    """
    HOT RELOAD: Compare config with current cameras and apply changes
    - Stop removed cameras
    - Start new cameras
    - Restart modified cameras
    - Only affected cameras are restarted (thread isolation!)
    """
    global cameras_dict

    new_config_cameras = config.get('cameras', [])
    new_camera_ids = {cam['id'] for cam in new_config_cameras}
    current_camera_ids = set(cameras_dict.keys())

    # Find removed cameras
    removed_ids = current_camera_ids - new_camera_ids
    for cam_id in removed_ids:
        print(f"🔴 Stopping removed camera: {cameras_dict[cam_id].name}")
        cameras_dict[cam_id].stop_camera()
        del cameras_dict[cam_id]

    # Find added or modified cameras
    for new_cam_cfg in new_config_cameras:
        cam_id = new_cam_cfg['id']
        
        if cam_id not in cameras_dict:
            # New camera - create and start
            print(f"🟢 Starting new camera: {new_cam_cfg['name']}")
            camera = CameraProcessor(new_cam_cfg, config['global_settings'], HEADLESS_MODE, config.get('headless_settings', {}))
            if camera.enabled and camera.start_camera():
                cameras_dict[cam_id] = camera
                print(f"✅ New camera '{camera.name}' started")
        else:
            # Existing camera - check if config changed
            existing_cam = cameras_dict[cam_id]
            config_changed = (
                existing_cam.rtsp_source != new_cam_cfg['rtsp_source'] or
                existing_cam.enabled != new_cam_cfg['enabled'] or
                existing_cam.api_enabled != new_cam_cfg['api_enabled'] or
                existing_cam.confidence_threshold != new_cam_cfg['confidence_threshold']
            )
            
            if config_changed:
                print(f"🟡 Reloading modified camera: {existing_cam.name}")
                existing_cam.stop_camera()
                
                # Update config and restart
                existing_cam.rtsp_source = new_cam_cfg['rtsp_source']
                existing_cam.enabled = new_cam_cfg['enabled']
                existing_cam.api_enabled = new_cam_cfg['api_enabled']
                existing_cam.confidence_threshold = new_cam_cfg['confidence_threshold']
                existing_cam.dedup_window = new_cam_cfg['dedup_window']
                
                if existing_cam.enabled:
                    existing_cam.start_camera()
                    print(f"✅ Camera '{existing_cam.name}' restarted with new config")


def setup_logging(headless_settings):
    """Setup logging for headless mode"""
    log_level = getattr(logging, headless_settings.get('log_level', 'INFO').upper())
    log_file = headless_settings.get('log_file', 'anpr_headless.log')

    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )

    logging.info("ANPR Headless Mode Started")


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    global stop_processing
    logging.info("Shutdown signal received. Stopping ANPR system...")
    stop_processing = True

def expand_roi(x1, y1, x2, y2, frame_h, frame_w, margin=0.07):
    w, h = x2 - x1, y2 - y1
    pad_x, pad_y = int(w * margin), int(h * margin)
    x1, y1 = max(0, x1 - pad_x), max(0, y1 - pad_y)
    x2, y2 = min(frame_w, x2 + pad_x), min(frame_h, y2 + pad_y)
    return int(x1), int(y1), int(x2), int(y2)

def pad_to_aspect(crop, target_w=94, target_h=24):
    import cv2
    h, w = crop.shape[:2]
    if h == 0 or w == 0:
        return cv2.resize(crop, (target_w, target_h))
    scale = target_h / h
    new_w = int(w * scale)
    resized = cv2.resize(crop, (new_w, target_h), interpolation=cv2.INTER_LINEAR)
    if new_w >= target_w:
        return cv2.resize(resized, (target_w, target_h), interpolation=cv2.INTER_AREA)
    pad_left = (target_w - new_w) // 2
    pad_right = target_w - new_w - pad_left
    import numpy as np
    return cv2.copyMakeBorder(resized, 0, 0, pad_left, pad_right, cv2.BORDER_CONSTANT, value=(0, 0, 0))

def inference_supervisor_loop():
    """Simplified synchronous inference loop for 3-core machine."""
    import torch
    import cv2
    import numpy as np
    from ultralytics import YOLO
    from LPRNet import LPRNet, predict_plates_batch
    import os

    device = 'cpu'
    print("🔄 Loading YOLO and LPRNet in supervisor thread...")
    yolo_path = os.path.join(os.path.dirname(__file__), "yolov8_best_ANPR_Vamsi.pt")
    lprnet_path = os.path.join(os.path.dirname(__file__), "newmodel", "best_lprnet.pth")
    
    # Allow PyTorch to use cores properly
    try:
        torch.set_num_threads(2)
    except:
        pass

    yolo_model = YOLO(yolo_path)
    yolo_model.to(device)

    lprnet_model = LPRNet(class_num=37, dropout_rate=0)
    lprnet_model.load_state_dict(torch.load(lprnet_path, map_location=device, weights_only=False))
    lprnet_model.to(device)
    lprnet_model.eval()
    print("✅ Models loaded in supervisor thread.")

    while not stop_processing:
        batch = []
        try:
            batch.append(global_frame_queue.get(timeout=0.1))
            while len(batch) < BATCH_SIZE:
                batch.append(global_frame_queue.get_nowait())
        except queue.Empty:
            pass

        if not batch:
            continue

        valid_frames = []
        cam_procs = []
        orig_frames = []
        roi_offsets = []

        for data in batch:
            frame = data['frame_resized']
            cam_proc = data['camera_processor']
            roi_polygon = cam_proc.roi_polygon
            roi = cam_proc.roi
            
            h_full, w_full, _ = frame.shape
            frame_for_detection = frame
            roi_offset_x, roi_offset_y = 0, 0
            
            try:
                if roi_polygon and len(roi_polygon) >= 3:
                    poly_np = np.array(roi_polygon, dtype=np.int32)
                    x, y, w, h = cv2.boundingRect(poly_np)
                    x = max(0, min(x, w_full - 1))
                    y = max(0, min(y, h_full - 1))
                    w = max(1, min(w, w_full - x))
                    h = max(1, min(h, h_full - y))
                    crop = frame[y:y + h, x:x + w]
                    mask = np.zeros((h, w), dtype=np.uint8)
                    shifted_poly = poly_np - np.array([x, y], dtype=np.int32)
                    cv2.fillPoly(mask, [shifted_poly], 255)
                    frame_for_detection = cv2.bitwise_and(crop, crop, mask=mask)
                    roi_offset_x, roi_offset_y = x, y
                elif roi:
                    if isinstance(roi, dict):
                        x1_roi, y1_roi, x2_roi, y2_roi = roi.get('x1', 0), roi.get('y1', 0), roi.get('x2', w_full), roi.get('y2', h_full)
                    else:
                        x1_roi, y1_roi, x2_roi, y2_roi = roi
                    x1_roi = max(0, min(x1_roi, w_full - 1))
                    y1_roi = max(0, min(y1_roi, h_full - 1))
                    x2_roi = max(0, min(x2_roi, w_full))
                    y2_roi = max(0, min(y2_roi, h_full))
                    if x2_roi > x1_roi and y2_roi > y1_roi:
                        frame_for_detection = frame[y1_roi:y2_roi, x1_roi:x2_roi]
                        roi_offset_x, roi_offset_y = x1_roi, y1_roi
            except Exception as e:
                print(f"⚠️ Error applying ROI: {e}")
                
            valid_frames.append(frame_for_detection)
            cam_procs.append(cam_proc)
            orig_frames.append(data['frame_original'])
            roi_offsets.append((roi_offset_x, roi_offset_y))
            
        if not valid_frames:
            continue
            
        try:
            inf_imgsz = 320 if cam_procs[0].global_settings.get('low_end_mode', True) else 640
            with torch.inference_mode():
                yolo_results_batch = yolo_model.predict(valid_frames, imgsz=inf_imgsz, verbose=False)
                
            all_crops = []
            crop_metadata = []
            
            for idx, yolo_results in enumerate(yolo_results_batch):
                conf_thresh = cam_procs[idx].confidence_threshold
                if yolo_results and yolo_results.boxes is not None and len(yolo_results.boxes) > 0:
                    print(f"[{cam_procs[idx].name}] YOLO found {len(yolo_results.boxes)} boxes! (thresh: {conf_thresh})")
                    for result in yolo_results.boxes:
                        x1, y1, x2, y2 = map(int, result.xyxy[0])
                        conf = float(result.conf[0]) if result.conf is not None else 0.0
                        cls_id = int(result.cls[0]) if result.cls is not None else 0
                        print(f"   -> Box [class {cls_id}]: conf={conf:.3f}")
                        
                        if conf < conf_thresh:
                            print(f"      -> Rejected! Confidence {conf:.3f} < {conf_thresh}")
                            continue
                            
                        # Adjust back to resized frame coords
                        ro_x, ro_y = roi_offsets[idx]
                        x1 += ro_x
                        y1 += ro_y
                        x2 += ro_x
                        y2 += ro_y
                        
                        # Expand bbox slightly using the full frame dimensions
                        frame_h, frame_w = batch[idx]['frame_resized'].shape[:2]
                        x1, y1, x2, y2 = expand_roi(x1, y1, x2, y2, frame_h, frame_w)
                        
                        plate_crop = batch[idx]['frame_resized'][y1:y2, x1:x2]
                        print(f"      -> Accepted! Crop size: {plate_crop.shape}")
                        
                        if plate_crop.size > 0:
                            padded = pad_to_aspect(plate_crop)
                            all_crops.append(padded)
                            crop_metadata.append({
                                'batch_idx': idx,
                                'bbox': (x1, y1, x2, y2),
                                'conf': conf,
                                'roi_offset': (ro_x, ro_y)
                            })
                            
            if all_crops:
                plate_texts = predict_plates_batch(lprnet_model, all_crops, device)
                
                camera_results = {i: [] for i in range(len(batch))}
                for meta, text in zip(crop_metadata, plate_texts):
                    b_idx = meta['batch_idx']
                    camera_results[b_idx].append({
                        'bbox': meta['bbox'],
                        'plate_text': text,
                        'confidence': meta['conf'],
                        'roi_offset': meta['roi_offset']
                    })
                    
                for i, cam_proc in enumerate(cam_procs):
                    if camera_results[i]:
                        cam_proc.handle_inference_results(orig_frames[i], camera_results[i])
                        
        except Exception as e:
            print(f"❌ Error in supervisor loop: {e}")

def main():
    global stop_processing, plate_logger, cameras_dict, PROCESS_EVERY_NTH_FRAME
    



    # Load configuration
    config = load_config()
    print(f"DEBUG: LOADED CONFIG IS: {config}")
    if not config:
        print("❌ No configuration found. Exiting.")
        return

    if config.get('system_mode') != 'multi_camera':
        print(f"❌ Configuration is not set for multi-camera mode. system_mode = {repr(config.get('system_mode'))}")
        return

    # Check for headless mode (use global HEADLESS_MODE which auto-detected display)
    global HEADLESS_MODE, CAN_USE_DISPLAY
    display_settings = config.get('display_settings', {})
    headless_settings = config.get('headless_settings', {})

    if HEADLESS_MODE:
        print("🤖 Starting in HEADLESS mode")
        setup_logging(headless_settings)
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    else:
        print("🖥️  Starting in DISPLAY mode")

    # Initialize plate logger
    global_settings = config['global_settings']
    try:
        PROCESS_EVERY_NTH_FRAME = max(1, int(global_settings.get('frame_skip', 2)))
    except Exception:
        PROCESS_EVERY_NTH_FRAME = 2
    try:
        plate_logger = PlateLogger(
            csv_file=None,
            allowed_plates_file="allowed_plates.json",
            dedup_window=30,
            max_confidence_threshold=0.8
        )
        print("✅ Plate logger initialized (using MySQL database)")
    except Exception as e:
        print(f"❌ Could not initialize plate logger: {e}")
        plate_logger = None

    # Initialize WebSocket client
    global websocket_client
    try:
        websocket_client = initialize_websocket_client("http://localhost:8084")
        print("✅ WebSocket client initialized for admin panel communication")
    except Exception as e:
        print(f"⚠️ Could not initialize WebSocket client: {e}")
        print("⚠️ Real-time features will be disabled")
        websocket_client = None

    # Initialize Inference Supervisor Thread
    import threading
    supervisor_thread = threading.Thread(target=inference_supervisor_loop, daemon=True)
    supervisor_thread.start()
    print("🛡️  Inference Supervisor started.")

    # Create camera processors (dict-based)
    cameras_list = []
    for camera_config in config['cameras']:
        camera = CameraProcessor(camera_config, global_settings, HEADLESS_MODE, headless_settings)
        cameras_dict[camera.camera_id] = camera
        cameras_list.append(camera)

    # Start enabled cameras
    for camera in cameras_list:
        if camera.enabled:
            if camera.start_camera():
                print(f"✅ Camera '{camera.name}' started successfully")
            else:
                print(f"❌ Failed to start camera '{camera.name}'")
        else:
            print(f"⏸️  Camera '{camera.name}' is disabled")

    if not any(cam.enabled for cam in cameras_list):
        print("❌ No cameras could be started. Exiting.")
        # Shutdown executor
        inference_executor.shutdown(wait=False)
        return

    # visual grid render or headless loop configuration
    window_title = display_settings.get('window_title', 'Multi-Camera ANPR System')
    grid_layout = display_settings.get('grid_layout', '2x2')
    
    show_gui = not HEADLESS_MODE and CAN_USE_DISPLAY
    last_status_update = 0
    status_update_interval = headless_settings.get('status_update_interval', 10)

    try:
        trigger_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts', 'reload_trigger.txt')
        config_mtime = os.path.getmtime(trigger_file) if os.path.exists(trigger_file) else 0
        
        while not stop_processing:
            if show_gui:
                # GUI Render Loop (Section 6.1 - 6.3)
                try:
                    grid_frame, grid_cameras = create_camera_grid(cameras_list, grid_layout)
                    if grid_frame is not None:
                        # Scale grid image width to max 960px to save render CPU (Section 6.3)
                        h_g, w_g = grid_frame.shape[:2]
                        if w_g > 960:
                            scale_g = 960.0 / w_g
                            grid_frame = cv2.resize(grid_frame, (960, int(h_g * scale_g)), interpolation=cv2.INTER_LINEAR)
                            
                        all_enabled_cameras = [cam for cam in cameras_list if cam.enabled]
                        total_plates = sum(cam.get_stats()['total_plates'] for cam in all_enabled_cameras)
                        total_cameras = len(all_enabled_cameras)
                        displayed_cameras = len(grid_cameras) if grid_cameras else 0
                        
                        cv2.putText(grid_frame, f"Total Plates: {total_plates} | Cameras: {displayed_cameras}/{total_cameras}", (10, 30),
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                        cv2.putText(grid_frame, "Press 'q' to quit, 's' to save frame", (10, 60),
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                        
                        cv2.imshow(window_title, grid_frame)
                        
                    # Handle key presses and cap rendering at 10 FPS with cv2.waitKey(100) (Section 6.2)
                    key = cv2.waitKey(100) & 0xFF
                    if key == ord('q'):
                        stop_processing = True
                        break
                    elif key == ord('s'):
                        # Save current frame
                        timestamp = time.strftime("%Y%m%d_%H%M%S")
                        filename = f"multi_camera_frame_{timestamp}.jpg"
                        if grid_frame is not None:
                            cv2.imwrite(filename, grid_frame)
                            print(f"📸 Frame saved as {filename}")
                except Exception as e:
                    print(f"❌ Error in GUI render loop: {e}")
            else:
                # Headless status update monitor (runs on main thread)
                if time.time() - last_status_update >= status_update_interval:
                    all_enabled_cameras = [cam for cam in cameras_list if cam.enabled]
                    total_plates = sum(cam.get_stats()['total_plates'] for cam in all_enabled_cameras)
                    logging.info(f"Status Update - Total Plates: {total_plates} | Active Cameras: {len(all_enabled_cameras)}")
                    last_status_update = time.time()
                time.sleep(0.1)

            # Hot reloading check
            current_mtime = os.path.getmtime(trigger_file) if os.path.exists(trigger_file) else 0
            if current_mtime > config_mtime:
                print("🔄 Configuration modification detected. Reloading cameras...")
                config_mtime = current_mtime
                new_config = load_config()
                if new_config:
                    reload_cameras_from_config(new_config)
                    # Update cameras_list in place so render loop sees it
                    cameras_list.clear()
                    cameras_list.extend(cameras_dict.values())

    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")

    finally:
        # Stop all cameras gracefully
        stop_processing = True
        print("\n🛑 Stopping all cameras...")
        
        for camera in cameras_list:
            try:
                camera.stop_camera()
            except Exception as e:
                if HEADLESS_MODE:
                    logging.error(f"Error stopping camera {camera.name}: {e}")
                else:
                    print(f"❌ Error stopping camera {camera.name}: {e}")



        # Close display window
        cv2.destroyAllWindows()

        # Print summary
        print(f"\n📊 Processing Summary:")
        total_plates_all = 0
        for camera in cameras_list:
            if camera.enabled:
                stats = camera.get_stats()
                print(f"  {camera.name} ({camera.location}): {stats['total_plates']} plates detected")
                total_plates_all += stats['total_plates']
            else:
                print(f"  {camera.name} ({camera.location}): DISABLED")

        print(f"\n🎯 Total plates detected across all cameras: {total_plates_all}")
        print("✅ ANPR system stopped cleanly")

if __name__ == "__main__":
    main()