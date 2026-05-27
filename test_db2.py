import time
from plate_logger import PlateLogger

pl = PlateLogger()
timestamp = time.time()
processing_time = (time.time() - timestamp) * 1000

# Try logging exactly as app_multi_camera does
print("Attempting to log...")
pl.log_detection(
    plate="MH12AB1234",
    detection_confidence=0.85,
    processing_time_ms=processing_time,
    camera_source="test",
    frame_number=1,
    image_full_annotated="/some/path.jpg",
    bbox_x1=10, bbox_y1=20, bbox_x2=30, bbox_y2=40
)
print("Done.")
