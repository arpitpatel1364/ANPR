# Set headless environment variables BEFORE importing OpenCV/PaddleOCR
# This prevents Qt GUI initialization errors in headless mode
import os
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|max_delay;500000|stimeout;5000000"
import json
import sys
import config_db

def can_use_display():
    """
    Check if a display is actually available and accessible.
    Returns True if X11/Wayland display is available, False otherwise.
    """
    # Check DISPLAY or WAYLAND_DISPLAY environment variable
    display = os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")
    if not display:
        return False
    
    # For Wayland, just check if the variable is set
    if os.environ.get("WAYLAND_DISPLAY"):
        return True
    
    # For X11, try to connect to display
    if os.environ.get("DISPLAY"):
        try:
            import subprocess
            # Try xset first, but fall back to just checking if DISPLAY is set
            result = subprocess.run(["xset", "q"], capture_output=True, timeout=2)
            if result.returncode == 0:
                return True
            else:
                # xset failed, but DISPLAY is set - assume display is available
                print(f"⚠️  xset command failed, but DISPLAY={display} is set. Assuming display available.")
                return True
        except Exception as e:
            # xset not available or failed, but DISPLAY is set - assume display is available
            print(f"⚠️  xset command not available or failed ({e}), but DISPLAY={display} is set. Assuming display available.")
            return True
    
    return False

def load_headless_mode_from_config(config_path=None):
    """
    Load headless_mode flag EARLY (before importing cv2).
    Safe defaults:
      - If config missing → headless
      - If key missing   → headless
    """
    if config_path is None:
        # Use path relative to this script's location
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
    
    try:
        with open(config_path, "r") as f:
            cfg = json.load(f)

        display_cfg = cfg.get("display_settings", {})
        return bool(display_cfg.get("headless_mode", True))

    except Exception as e:
        print(f"!!..Early config load failed ({e}), forcing HEADLESS mode..!!")
        return True


# Decide mode BEFORE OpenCV / Qt loads
REQUESTED_HEADLESS_MODE = load_headless_mode_from_config()
CAN_USE_DISPLAY = can_use_display() if not REQUESTED_HEADLESS_MODE else False
HEADLESS_MODE = not CAN_USE_DISPLAY  # True if we can't use display

if REQUESTED_HEADLESS_MODE and not CAN_USE_DISPLAY:
    print(">> Starting in HEADLESS mode (from config.json)")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["DISPLAY"] = ""
elif REQUESTED_HEADLESS_MODE and CAN_USE_DISPLAY:
    print("⚠️  Config says headless_mode=true, but display is available")
    print(">> Starting in HEADLESS mode (respecting config.json)")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["DISPLAY"] = ""
elif not REQUESTED_HEADLESS_MODE and CAN_USE_DISPLAY:
    print(">> Starting in DISPLAY mode (from config.json and display detected)")
    os.environ["QT_QPA_PLATFORM"] = "xcb"
elif not REQUESTED_HEADLESS_MODE and not CAN_USE_DISPLAY:
    print("⚠️  Config says headless_mode=false, but no display detected")
    print(">> Falling back to HEADLESS mode (no X11 display available)")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["DISPLAY"] = ""
    HEADLESS_MODE = True

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
from threading import Thread, Lock
import queue
import concurrent.futures
from plate_logger import PlateLogger, _PLATE_CACHE, _cache_lock, global_matcher
import requests
from requests.auth import HTTPDigestAuth
import logging
import signal
import torch
from websocket_client import initialize_websocket_client, get_websocket_client

# Load YOLO model with GPU support
model_path = os.path.join(os.path.dirname(__file__), "yolov8_best_ANPR_Vamsi.pt")
model = YOLO(model_path)
# Force CPU to avoid CUDA kernel compatibility issues
model.to('cpu')
print("✅ YOLO model loaded on CPU (GPU compatibility issue detected)")

# ============================================================================
#  PaddleOCR initialization block
#  LPRNet initialization block
# ============================================================================
# Initialize LPRNet
print("🔄 Initializing LPRNet model...")
device = 'cuda' if torch.cuda.is_available() else 'cpu'
lprnet_model = LPRNet(class_num=37, dropout_rate=0)
lprnet_model.load_state_dict(torch.load('newmodel/best_lprnet.pth', map_location=device, weights_only=False))
lprnet_model.to(device)
lprnet_model.eval()
print(f"✅ LPRNet initialized on {device}")

# Define confusion mapping for common OCR errors
# digits that look like letters (and vice versa)
digit_to_letter = {'0': 'O', '1': 'I', '2': 'Z',
    '5': 'S', '6': 'G', '8': 'B', '9': 'P'}
letter_to_digit = {v: k for k, v in digit_to_letter.items()}

# some letters are frequently confused with each other by OCR, especially
# D ↔ O (rounded shapes). This dictionary lets the HMM give a boost when an
# observed letter is a common mis-read of the candidate.
LETTER_CONFUSIONS = {
    'D': ['O'],
    'O': ['D'],
    # add more pairs here if other confusions are noticed
}

# Indian number plate regex patterns (supports old, new, and brand new formats)
# Old format: XX##XX#### (e.g., MH12AB1234) - 2 letters, 2 digits, 2 letters, 4 digits
# New format: XX##XXX#### (e.g., MH12ABC1234) - 2 letters, 2 digits, 3 letters, 4 digits
# Brand new format: ##XX #### XX (e.g., 24BH 1234 AB) - 2 digits, 2 letters, 4 digits, 2 letters (with/without spaces)
INDIAN_PLATE_REGEX = re.compile(
    r'^('
    r'[A-Z]{2}[0-9]{2}[A-Z]{2}[0-9]{4}|'  # Old: MH12AB1234
    r'[A-Z]{2}[0-9]{2}[A-Z]{3}[0-9]{4}|'  # New: MH12ABC1234
    r'[0-9]{2}[A-Z]{2}[0-9]{4}[A-Z]{2}|'  # Brand new (no spaces): 24BH1234AB
    r'[0-9]{2}[A-Z]{2}\s+[0-9]{4}\s+[A-Z]{2}'  # Brand new (with spaces): 24BH 1234 AB
    r')$'
)

# ============================================================================
# REFACTORED THREADING MODEL (N+2 threads):
#  - N per-camera fetch threads (simple frame capture)
#  - 1 global frame processor thread (YOLO + OCR)
#  - 1 optional global display thread (grid visualization)
# ============================================================================

# Removed global_frame_queue in favor of per-camera queues

# Global ThreadPool for API calls to prevent thread bloat
api_thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=5)

# Global processing threads
processor_thread = None
display_thread = None
processor_thread_lock = Lock()

# Global variables
detected_plates = {}  # Store detected plates with timestamps
plate_lock = Lock()  # Thread lock for thread-safe operations
stop_processing = False
plate_logger = None
PROCESS_EVERY_NTH_FRAME = 2

# Initialize WebSocket client for real-time communication with admin panel
websocket_client = None

# Dictionary-based cameras for O(1) lookup and easy hot reload
cameras_dict = {}  # {camera_id: CameraProcessor}

# ============================================================================
# per-camera throttle at module level
# ============================================================================
_last_processed_time = {}
MIN_PROCESS_INTERVAL = 0.08


class CameraProcessor:
    """
    SIMPLIFIED for N+2 threading model:
    - Only handles frame FETCHING (RTSP capture)
    - Frame PROCESSING moved to global processor thread
    - ROI selection, image saving remain here
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

        self.headless_mode = headless_mode
        self.headless_settings = headless_settings or {}

        self.fetch_thread = None  # Thread for fetching frames from RTSP
        self.cap = None
        self.current_processed_frame = None
        self.frame_count = 0
        self.start_time = time.time()
        
        # Optimization 2: Per-camera queue (size 1)
        self.frame_queue = queue.Queue(maxsize=1)
        # Optimization 1: Throttle frame ingestion
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
        self.save_frames = self.headless_settings.get('save_frames', False)

        # ============================================================================
        # CLAHE and sharpen kernel cache in CameraProcessor.__init__
        # ============================================================================
        self._clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
        self._sharpen_kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])

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

        if len(cleaned_text_no_spaces) in [10, 11]:
            corrected_text_no_spaces = self.hmm_correct_plate(cleaned_text_no_spaces)
            # Reconstruct with spaces
            corrected_text = ""
            idx = 0
            for char in cleaned_text_with_spaces:
                if char.isspace():
                    corrected_text += char
                else:
                    if idx < len(corrected_text_no_spaces):
                        corrected_text += corrected_text_no_spaces[idx]
                        idx += 1
            # In case the lengths don't exactly match due to some reason
            if idx < len(corrected_text_no_spaces):
                corrected_text += corrected_text_no_spaces[idx:]
        else:
            corrected_text = cleaned_text_with_spaces

        return corrected_text

    def hmm_correct_plate(self, obs_text):
        """HMM correction for multiple license plate formats (10 and 11 chars)"""
        n = len(obs_text)
        if n not in [10, 11]:
            return obs_text

        templates_10 = [
            ['letter', 'letter', 'digit', 'digit', 'letter', 'letter', 'digit', 'digit', 'digit', 'digit'], # AAXXAAXXXX
            ['digit', 'digit', 'letter', 'letter', 'digit', 'digit', 'digit', 'digit', 'letter', 'letter'], # YYBH####XX
            ['letter', 'letter', 'digit', 'digit', 'digit', 'letter', 'digit', 'digit', 'digit', 'digit'] # AAXX XA XXXX
        ]
        templates_11 = [
            ['letter', 'letter', 'digit', 'digit', 'letter', 'letter', 'letter', 'digit', 'digit', 'digit', 'digit'], # AAXXAAAXXXX
            ['digit', 'digit', 'letter', 'letter', 'digit', 'digit', 'digit', 'digit', 'letter', 'letter', 'letter'] # YYBH####XXX
        ]

        templates = templates_10 if n == 10 else templates_11

        letter_candidates = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        digit_candidates = list("0123456789")

        def emission_prob(expected_type, candidate, observed):
            candidate = candidate.upper() if expected_type == 'letter' else candidate
            observed = observed.upper() if expected_type == 'letter' else observed
            if expected_type == 'letter':
                if observed.isalpha():
                    if candidate == observed:
                        return 0.9
                    # treat common letter-letter confusions with moderate weight
                    elif observed in LETTER_CONFUSIONS.get(candidate, []):
                        return 0.5
                    else:
                        return 0.1 / (len(letter_candidates) - 1)
                elif observed.isdigit():
                    if digit_to_letter.get(observed, None) == candidate:
                        return 0.5
                    else:
                        return 0.01
                else:
                    return 0.01
            else:  # expected digit
                if observed.isdigit():
                    return 0.9 if candidate == observed else 0.1 / (len(digit_candidates) - 1)
                elif observed.isalpha():
                    if letter_to_digit.get(observed, None) == candidate:
                        return 0.5
                    else:
                        return 0.01
                else:
                    return 0.01

        best_overall_sequence = obs_text
        best_overall_prob = -1

        for expected_types in templates:
            dp = []
            backpointer = []

            # Initialization
            current_candidates = letter_candidates if expected_types[0] == 'letter' else digit_candidates
            dp0 = {}
            bp0 = {}
            for c in current_candidates:
                dp0[c] = emission_prob(expected_types[0], c, obs_text[0])
                bp0[c] = None
            dp.append(dp0)
            backpointer.append(bp0)

            # Recursion
            for i in range(1, n):
                current_candidates = letter_candidates if expected_types[i] == 'letter' else digit_candidates
                dp_curr = {}
                bp_curr = {}
                for curr in current_candidates:
                    max_prob = -1
                    best_prev = None
                    for prev, prev_prob in dp[i - 1].items():
                        prob = prev_prob * emission_prob(expected_types[i], curr, obs_text[i])
                        if prob > max_prob:
                            max_prob = prob
                            best_prev = prev
                    dp_curr[curr] = max_prob
                    bp_curr[curr] = best_prev
                dp.append(dp_curr)
                backpointer.append(bp_curr)

            # Termination and backtrace
            last_candidates = dp[-1]
            best_last = max(last_candidates, key=last_candidates.get)
            max_template_prob = last_candidates[best_last]

            if max_template_prob > best_overall_prob:
                best_overall_prob = max_template_prob
                best_sequence = [best_last]
                for i in range(n - 1, 0, -1):
                    best_sequence.insert(0, backpointer[i][best_sequence[0]])
                best_overall_sequence = "".join(best_sequence)

        return best_overall_sequence

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

    def make_api_call(self, plate_text, verification_status):
        """Make API calls for this specific camera"""
        try:
            success_count = 0
            username = self.api_settings.get('username', 'admin')
            password = self.api_settings.get('password', 'Admin@123')
            base_url = self.api_settings.get('base_url', 'http://192.168.1.124/cpapi/configManager.cgi')
            timeout = self.api_settings.get('timeout', 5)
            max_retries = self.api_settings.get('max_retries', 3)

            mode1_success = False

            # Mode 1 - First attempt
            try:
                url1 = f"{base_url}?action=setConfig&AlarmOut[0].Mode=1"
                response1 = requests.get(url1, auth=HTTPDigestAuth(username, password), timeout=timeout)

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
                    response2 = requests.get(url2, auth=HTTPDigestAuth(username, password), timeout=timeout)

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
                            time.sleep(0.5)

                except Exception as e:
                    print(f"❌ [{self.name}] API call 2 error for plate: {plate_text} - {str(e)} - Mode=2 (Retry {retry + 1}/{retry_count})")
                    if retry < retry_count - 1:
                        time.sleep(0.5)

            return success_count > 0

        except Exception as e:
            print(f"❌ [{self.name}] General API call error for plate: {plate_text} - {str(e)}")
            return False

    def trigger_api_call(self, plate_text, verification_status):
        """Trigger API call in a separate thread"""
        try:
            self.make_api_call(plate_text, verification_status)
        except Exception as e:
            print(f"❌ [{self.name}] Error triggering API call: {str(e)}")

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

    def process_frame(self, frame, frame_number=0):
        """
        INDEPENDENT PROCESSING LOGIC (moved from fetch thread)
        Used by global processor thread to process frames from queue
        """
        try:
            start_time = time.time()

            if not self._validate_frame(frame, "input_frame"):
                if self.headless_mode:
                    logging.warning(f"[{self.name}] Invalid frame received, skipping (frame {frame_number})")
                else:
                    print(f"⚠️ [{self.name}] Invalid frame received, skipping (frame {frame_number})")
                return frame, []

            original_frame = frame.copy()
            frame_for_detection = frame
            roi_offset_x, roi_offset_y = 0, 0

            try:
                h_full, w_full, _ = frame.shape

                if self.roi_polygon and len(self.roi_polygon) >= 3:
                    poly_np = np.array(self.roi_polygon, dtype=np.int32)
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

                elif self.roi:
                    x1_roi, y1_roi, x2_roi, y2_roi = self.roi

                    x1_roi = max(0, min(x1_roi, w_full - 1))
                    y1_roi = max(0, min(y1_roi, h_full - 1))
                    x2_roi = max(0, min(x2_roi, w_full))
                    y2_roi = max(0, min(y2_roi, h_full))

                    if x2_roi > x1_roi and y2_roi > y1_roi:
                        frame_for_detection = frame[y1_roi:y2_roi, x1_roi:x2_roi]
                        roi_offset_x, roi_offset_y = x1_roi, y1_roi
                    else:
                        frame_for_detection = frame
                else:
                    frame_for_detection = frame
            except Exception as e:
                print(f"⚠️ [{self.name}] Error applying ROI, falling back to full frame: {e}")
                frame_for_detection = frame
                roi_offset_x, roi_offset_y = 0, 0

            if not self._validate_frame(frame_for_detection, "detection_frame"):
                if self.headless_mode:
                    logging.warning(f"[{self.name}] Invalid ROI frame, skipping detection (frame {frame_number})")
                else:
                    print(f"⚠️ [{self.name}] Invalid ROI frame, skipping detection (frame {frame_number})")
                return original_frame, []

            # YOLO detection (synchronized globally via processor thread)
            try:
                results = model.predict(frame_for_detection, imgsz=640, verbose=False)
            except Exception as e:
                if self.headless_mode:
                    logging.error(f"[{self.name}] YOLO prediction error: {e}")
                else:
                    print(f"❌ [{self.name}] YOLO prediction error: {e}")
                return original_frame, []

            processed_frame = original_frame.copy()
            detected_texts = []

            if results and len(results) > 0 and results[0].boxes is not None:
                for result in results[0].boxes:
                    x1, y1, x2, y2 = map(int, result.xyxy[0])
                    confidence = float(result.conf[0]) if result.conf is not None else 0.0

                    h, w, _ = frame_for_detection.shape
                    x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)

                    if x2 <= x1 or y2 <= y1:
                        continue

                    cropped_plate = frame_for_detection[y1:y2, x1:x2]

                    if cropped_plate.size == 0 or cropped_plate.shape[0] < 10 or cropped_plate.shape[1] < 10:
                        continue

                    if not self._validate_frame(cropped_plate, "cropped_plate"):
                        if self.headless_mode:
                            logging.warning(f"[{self.name}] Invalid cropped plate, skipping OCR (frame {frame_number})")
                        continue

                    if not cropped_plate.flags['C_CONTIGUOUS']:
                        cropped_plate = np.ascontiguousarray(cropped_plate)
                    if cropped_plate.dtype != np.uint8:
                        cropped_plate = cropped_plate.astype(np.uint8)

                    ocr_result = None
                    try:
                        # ============================================================================
                        # the OCR call inside process_frame method
                        # ============================================================================
                        license_plate_text = predict_plate(lprnet_model, cropped_plate, device)
                        ocr_result = self.convert_ocr_format([[(license_plate_text, 1.0)]])
                    except Exception as ocr_error:
                        error_msg = str(ocr_error)
                        if "Tensor holds no memory" in error_msg or "PreconditionNotMetError" in error_msg:
                            if self.headless_mode:
                                logging.warning(f"[{self.name}] PaddleOCR tensor error (likely corrupted frame), skipping: {error_msg[:100]}")
                            else:
                                print(f"⚠️ [{self.name}] PaddleOCR tensor error (likely corrupted frame), skipping: {error_msg[:100]}")
                        else:
                            if self.headless_mode:
                                logging.error(f"[{self.name}] OCR error: {error_msg[:200]}")
                            else:
                                print(f"❌ [{self.name}] OCR error: {error_msg[:200]}")
                        continue

                    license_plate_text = self.extract_license_plate(ocr_result)
                    
                    # === RAPIDFUZZ FUZZY MATCHING LOGIC ===
                    # Attempt to correct slight OCR mistakes using high-performance rapidfuzz
                    if license_plate_text:
                        with _cache_lock:
                            matcher = global_matcher
                        
                        match, status = matcher.match_plate(license_plate_text, 1.0)
                        if status.startswith("FUZZY"):
                            if not self.headless_mode:
                                print(f"✨ [{self.name}] RapidFuzz Corrected: {license_plate_text} -> {match} ({status})")
                            license_plate_text = match
                    # ======================================
                    
                    if not self.is_valid_indian_plate(license_plate_text):
                        if self.headless_mode:
                            logging.debug(f"[{self.name}] Invalid plate format (not Indian), skipping: {license_plate_text}")
                        else:
                            print(f"🚫 [{self.name}] Invalid plate format (not Indian), skipping: {license_plate_text}")
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

                            global_x1 = x1 + roi_offset_x
                            global_y1 = y1 + roi_offset_y
                            global_x2 = x2 + roi_offset_x
                            global_y2 = y2 + roi_offset_y

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

                            image_urls = self.save_detection_images(
                                full_frame_annotated=annotated_frame,
                                plate_text=license_plate_text,
                                frame_number=frame_number,
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

                            if should_log:
                                plate_logger.log_detection(
                                    plate=license_plate_text,
                                    detection_confidence=confidence,
                                    processing_time_ms=processing_time,
                                    camera_source=f"{self.name} ({self.location})",
                                    frame_number=frame_number,
                                    image_full_annotated=image_urls.get('image_full_annotated') if image_urls else None,
                                    bbox_x1=image_urls.get('bbox_x1') if image_urls else None,
                                    bbox_y1=image_urls.get('bbox_y1') if image_urls else None,
                                    bbox_x2=image_urls.get('bbox_x2') if image_urls else None,
                                    bbox_y2=image_urls.get('bbox_y2') if image_urls else None
                                )

                                # Update cooldown for verified plates after logging
                                if verification_status == "VERIFIED":
                                    self.update_verified_plate_cooldown(license_plate_text)

                            if verification_status == "VERIFIED":
                                self.save_verified_plate_image(processed_frame, license_plate_text, frame_number)

                            self.send_detection_to_admin_panel(
                                plate=license_plate_text,
                                confidence=confidence,
                                processing_time=processing_time,
                                verification_status=verification_status,
                                frame_number=frame_number,
                                image_urls=image_urls
                            )

                            if verification_status == "VERIFIED" and self.api_enabled:
                                api_thread_pool.submit(self.trigger_api_call, license_plate_text, verification_status)
                            else:
                                if not self.api_enabled:
                                    print(f"🚫 [{self.name}] API disabled for this camera - plate: {license_plate_text}")
                                else:
                                    print(f"🚫 [{self.name}] API call skipped for plate: {license_plate_text} (Status: {verification_status}) - Not verified")

            return processed_frame, detected_texts

        except Exception as e:
            print(f"❌ [{self.name}] Error processing frame: {e}")
            return frame, []

    def frame_fetch_worker(self):
        """
        SIMPLIFIED for N+2 model:
        - Only FETCH frames from RTSP and queue them
        - NO processing (processing done by global processor thread)
        """
        global stop_processing

        while True:
            if stop_processing:
                break
            
            with self.stop_camera_lock:
                if self.stop_camera_flag:
                    break

            try:
                if self.cap and self.cap.isOpened():
                    ret, frame = self.cap.read()
                    
                    # Add retry logic for failed reads
                    if not ret or frame is None:
                        retry_count = 0
                        while retry_count < 5:
                            time.sleep(0.2)
                            ret, frame = self.cap.read()
                            if ret and frame is not None:
                                break
                            retry_count += 1

                        if not ret:
                            if self.headless_mode:
                                logging.warning(f"[{self.name}] Stream lost after retries, exiting thread...")
                            else:
                                print(f"⚠️ [{self.name}] Stream lost after retries, exiting thread...")
                            return
                    
                    if ret and frame is not None:
                        if self._validate_frame(frame, "captured_frame"):
                            self.frame_count += 1
                            frame_copy = frame.copy()
                            
                            # Optimization 1: Throttle frame ingestion (2 FPS = 0.5s per frame)
                            current_time = time.time()
                            if current_time - self.last_put_time > 0.5:
                                self.last_put_time = current_time
                                
                                # Optimization 2: Put frame on per-camera queue
                                try:
                                    self.frame_queue.put_nowait({
                                        'frame': frame_copy,
                                        'camera_id': self.camera_id,
                                        'camera_processor': self,
                                        'frame_number': self.frame_count
                                    })
                                except queue.Full:
                                    # Queue full, drop oldest frame
                                    try:
                                        self.frame_queue.get_nowait()
                                        self.frame_queue.put_nowait({
                                            'frame': frame_copy,
                                            'camera_id': self.camera_id,
                                            'camera_processor': self,
                                            'frame_number': self.frame_count
                                        })
                                    except queue.Empty:
                                        pass

                            # Save periodic ROI fallback snapshot for admin panel ROI editor fallback
                            try:
                                current_time = time.time()
                                if current_time - self.last_roi_snapshot_time >= self.roi_snapshot_interval:
                                    os.makedirs(self.roi_snapshot_dir, exist_ok=True)
                                    snapshot_path = os.path.join(self.roi_snapshot_dir, f"{self.camera_id}.jpg")
                                    cv2.imwrite(snapshot_path, frame_copy)
                                    self.last_roi_snapshot_time = current_time
                            except Exception as e:
                                if self.headless_mode:
                                    logging.warning(f"[{self.name}] Failed to save ROI snapshot: {e}")
                                else:
                                    print(f"⚠️ [{self.name}] Failed to save ROI snapshot: {e}")
                        else:
                            if self.headless_mode:
                                logging.debug(f"[{self.name}] Skipping corrupted frame (H.264 decode error)")
                    else:
                        if self.headless_mode:
                            logging.warning(f"[{self.name}] Stream lost after retries, exiting thread...")
                        else:
                            print(f"⚠️ [{self.name}] Stream lost after retries, exiting thread...")
                        return
                
                time.sleep(0.001)  # Small sleep to prevent busy-waiting

            except Exception as e:
                if self.headless_mode:
                    logging.error(f"[{self.name}] Error in fetch worker: {e}")
                else:
                    print(f"❌ [{self.name}] Error in fetch worker: {e}")
                continue

    def _persist_roi_to_config(self):
        """Save ROI to config.json"""
        try:
            with open('config.json', 'r') as f:
                config_data = json.load(f)

            cameras_cfg = config_data.get('cameras', [])
            updated = False
            for cam_cfg in cameras_cfg:
                if cam_cfg.get('id') == self.camera_id:
                    if self.roi is not None:
                        x1, y1, x2, y2 = self.roi
                        cam_cfg['roi'] = {'x1': int(x1), 'y1': int(y1), 'x2': int(x2), 'y2': int(y2)}

                    if self.roi_polygon is not None and len(self.roi_polygon) >= 3:
                        cam_cfg['roi_polygon'] = [{'x': int(px), 'y': int(py)} for (px, py) in self.roi_polygon]

                    updated = True
                    break

            if updated:
                config_data['cameras'] = cameras_cfg
                with open('config.json', 'w') as f:
                    json.dump(config_data, f, indent=2)
                print(f"💾 Saved ROI for camera '{self.name}' into config.json: {self.roi}")
        except Exception as e:
            print(f"⚠️ [{self.name}] Failed to persist ROI to config.json: {e}")

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
                    logging.error(f"[{self.name}] Could not open video source: {self.rtsp_source}")
                else:
                    print(f"❌ [{self.name}] Could not open video source: {self.rtsp_source}")
                self.cap = None
                return False

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

    def save_verified_plate_image(self, frame, plate_text, frame_number):
        """Save image for verified plates"""
        try:
            verified_dir = "admin_panel/static/images/verified_plates"
            os.makedirs(verified_dir, exist_ok=True)

            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"verified_{self.camera_id}_{timestamp}_{plate_text}_frame{frame_number}.jpg"
            filepath = os.path.join(verified_dir, filename)

            cv2.imwrite(filepath, frame)

            if self.headless_mode:
                logging.info(f"[{self.name}] Verified plate image saved: {filename}")
            else:
                print(f"📸 [{self.name}] Verified plate image saved: {filename}")

        except Exception as e:
            if self.headless_mode:
                logging.error(f"[{self.name}] Error saving verified plate image: {e}")
            else:
                print(f"❌ [{self.name}] Error saving verified plate image: {e}")

    def save_detection_images(self, full_frame_annotated, plate_text, frame_number, verification_status, bbox_x1, bbox_y1, bbox_x2, bbox_y2):
        """Save detection image and return URLs and bbox"""
        urls = {}
        try:
            base_dir = "admin_panel/static/images/detections"
            full_annotated_dir = os.path.join(base_dir, "full_annotated")

            os.makedirs(full_annotated_dir, exist_ok=True)

            timestamp = time.strftime("%Y%m%d_%H%M%S")
            safe_plate = re.sub(r"[^A-Za-z0-9]", "_", plate_text) if plate_text else "unknown"
            status_tag = "VER" if verification_status == "VERIFIED" else "NOTVER"

            full_annotated_name = f"{self.camera_id}_{timestamp}_{safe_plate}_{status_tag}_f{frame_number}_ann.webp"

            full_annotated_path = os.path.join(full_annotated_dir, full_annotated_name)

            if isinstance(full_frame_annotated, np.ndarray):
                cv2.imwrite(full_annotated_path, full_frame_annotated, [cv2.IMWRITE_WEBP_QUALITY, 80])
                # Generate thumbnail
                thumb_path = full_annotated_path.replace('_ann.webp', '_ann_thumb.webp')
                thumb = cv2.resize(full_frame_annotated, (140, 80))
                cv2.imwrite(thumb_path, thumb, [cv2.IMWRITE_WEBP_QUALITY, 70])

            urls = {
                'image_full_annotated': f"/static/images/detections/full_annotated/{full_annotated_name}",
                'bbox_x1': bbox_x1,
                'bbox_y1': bbox_y1,
                'bbox_x2': bbox_x2,
                'bbox_y2': bbox_y2
            }
        except Exception as e:
            if self.headless_mode:
                logging.error(f"[{self.name}] Error saving detection images: {e}")
            else:
                print(f"❌ [{self.name}] Error saving detection images: {e}")
        return urls

    def send_detection_to_admin_panel(self, plate, confidence, processing_time, verification_status, frame_number, image_urls=None):
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
                    'frame_number': frame_number,
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

def process_frame_task(frame_data):
    """
    Task to process a single frame using the camera processor
    """
    try:
        frame = frame_data['frame']
        camera_id = frame_data['camera_id']
        camera_processor = frame_data['camera_processor']
        frame_number = frame_data['frame_number']

        # per-camera throttle
        now = time.time()
        last_t = _last_processed_time.get(camera_id, 0)
        if now - last_t < MIN_PROCESS_INTERVAL:
            camera_processor.current_processed_frame = frame
            return
        _last_processed_time[camera_id] = now

        # Process every Nth frame to limit FPS
        if PROCESS_EVERY_NTH_FRAME > 1 and frame_number % PROCESS_EVERY_NTH_FRAME != 0:
            camera_processor.current_processed_frame = frame
            return

        # Process the frame
        processed_frame, detected_texts = camera_processor.process_frame(frame, frame_number)
        
        # Store processed frame back in camera processor for display
        camera_processor.current_processed_frame = processed_frame

        if detected_texts:
            if camera_processor.headless_mode:
                logging.info(f"[{camera_processor.name}] Detected plates: {detected_texts}")
            else:
                print(f"📹 [{camera_processor.name}] Detected plates: {detected_texts}")

            # Save frame in headless mode if enabled
            if camera_processor.headless_mode and camera_processor.save_frames and detected_texts:
                current_time = time.time()
                if current_time - camera_processor.last_frame_save >= camera_processor.frame_save_interval:
                    camera_processor.save_detection_frame(processed_frame, detected_texts)
                    camera_processor.last_frame_save = current_time
    except Exception as e:
        print(f"❌ Error in process_frame_task: {e}")

# Global ThreadPool for frame processing
# Optimization 3: Set max_workers = 3 to reduce context switching
processor_pool = concurrent.futures.ThreadPoolExecutor(max_workers=3)

def global_frame_processor():
    """
    THE GLOBAL PROCESSOR THREAD (1 thread to dispatch to ThreadPool)
    - Consumes frames from per-camera queues via round-robin
    - Submits frames to the ThreadPoolExecutor for parallel processing
    """
    global stop_processing, cameras_dict

    while not stop_processing:
        if not cameras_dict:
            time.sleep(0.1)
            continue
            
        processed_any = False
        
        # Optimization 2: Round-robin scheduler
        for cam_id, camera_processor in list(cameras_dict.items()):
            if stop_processing:
                break
                
            if not camera_processor.enabled:
                continue
                
            try:
                # Non-blocking get from this camera's queue
                frame_data = camera_processor.frame_queue.get_nowait()
                processor_pool.submit(process_frame_task, frame_data)
                processed_any = True
            except queue.Empty:
                pass
            except Exception as e:
                print(f"❌ Error in global frame processor dispatcher for camera {cam_id}: {e}")
                
        # If no frames were processed across all cameras, sleep briefly
        if not processed_any:
            time.sleep(0.01)


# ============================================================================
# OPTIONAL DISPLAY THREAD: Creates camera grid and handles display
# ============================================================================

def display_thread_worker(cameras_list, window_title, grid_layout, headless_settings):
    """
    OPTIONAL DISPLAY THREAD (1 thread for display)
    - Creates camera grid from latest processed frames
    - Handles key input and window management
    - Headless mode skips this entirely
    - Display unavailable → gracefully exits
    """
    global stop_processing, HEADLESS_MODE, CAN_USE_DISPLAY

    # Safety check: if display isn't actually available, exit gracefully
    if HEADLESS_MODE or not CAN_USE_DISPLAY:
        print("📊 Display not available: skipping display thread")
        return

    last_status_update = 0
    status_update_interval = headless_settings.get('status_update_interval', 10)

    while not stop_processing:
        try:
            # Display mode - show camera grid
            grid_frame, grid_cameras = create_camera_grid(cameras_list, grid_layout)

            if grid_frame is not None:
                all_enabled_cameras = [cam for cam in cameras_list if cam.enabled]
                total_plates = sum(cam.get_stats()['total_plates'] for cam in all_enabled_cameras)
                total_cameras = len(all_enabled_cameras)
                displayed_cameras = len(grid_cameras) if grid_cameras else 0

                cv2.putText(grid_frame, f"Total Plates: {total_plates} | Cameras: {displayed_cameras}/{total_cameras}", (10, 30),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                cv2.putText(grid_frame, "Press 'q' to quit, 's' to save frame", (10, 60),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

                cv2.imshow(window_title, grid_frame)

            # Handle key presses
            key = cv2.waitKey(1) & 0xFF
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

            time.sleep(0.01)

        except Exception as e:
            print(f"❌ Error in display thread: {e}")
            continue


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
    """Load configuration from database with fallback to config.json"""
    try:
        config = config_db.load_config_from_db()
        if config:
            return config
            
        with open('config.json', 'r') as f:
            config = json.load(f)
        print("✅ Configuration loaded from config.json (fallback)")
        return config
    except FileNotFoundError:
        print("❌ config.json not found. Using default settings.")
        return None
    except json.JSONDecodeError as e:
        print(f"❌ Error parsing config.json: {e}. Using default settings.")
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


def main():
    global stop_processing, plate_logger, processor_thread, display_thread, cameras_dict, PROCESS_EVERY_NTH_FRAME

    # Load configuration
    config = load_config()
    if not config:
        print("❌ No configuration found. Exiting.")
        return

    if config.get('system_mode') != 'multi_camera':
        print("❌ Configuration is not set for multi-camera mode. Please update config.json")
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
    # Use config frame_skip in processor loop; enforce safe minimum.
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
        return

    # ========================================================================
    # SPAWN N+2 GLOBAL THREADS
    # ========================================================================

    # 1. Start global processor thread
    print("🚀 Starting global frame processor thread...")
    processor_thread = Thread(target=global_frame_processor, daemon=True)
    processor_thread.start()

    # 2. Start display thread (if not headless and display available)
    window_title = display_settings.get('window_title', 'Multi-Camera ANPR System')
    grid_layout = display_settings.get('grid_layout', '2x2')

    if not HEADLESS_MODE and CAN_USE_DISPLAY:
        print("🚀 Starting display thread...")
        display_thread = Thread(target=display_thread_worker, 
                              args=(cameras_list, window_title, grid_layout, headless_settings),
                              daemon=True)
        display_thread.start()
    else:
        if HEADLESS_MODE:
            print("📊 Headless mode: skipping display thread")
        else:
            print("📊 Display not available: skipping display thread (running in headless fallback)")
        # Status update loop for headless mode
        last_status_update = 0
        status_update_interval = headless_settings.get('status_update_interval', 10)

    try:
        trigger_file = 'reload_trigger.txt'
        config_mtime = os.path.getmtime(trigger_file) if os.path.exists(trigger_file) else 0
        
        # Main loop (minimal work - just monitoring)
        while not stop_processing:
            if HEADLESS_MODE:
                # Headless status update
                if time.time() - last_status_update >= status_update_interval:
                    all_enabled_cameras = [cam for cam in cameras_list if cam.enabled]
                    total_plates = sum(cam.get_stats()['total_plates'] for cam in all_enabled_cameras)
                    logging.info(f"Status Update - Total Plates: {total_plates} | Active Cameras: {len(all_enabled_cameras)}")
                    last_status_update = time.time()

            # Hot reloading check
            current_mtime = os.path.getmtime(trigger_file) if os.path.exists(trigger_file) else 0
            if current_mtime > config_mtime:
                print("🔄 Configuration modification detected. Reloading cameras...")
                config_mtime = current_mtime
                new_config = load_config()
                if new_config:
                    reload_cameras_from_config(new_config)
                    # Update cameras_list in place so display thread sees it
                    cameras_list.clear()
                    cameras_list.extend(cameras_dict.values())

            time.sleep(0.1)

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

        # Wait for processor thread to finish
        if processor_thread and processor_thread.is_alive():
            processor_thread.join(timeout=3.0)

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