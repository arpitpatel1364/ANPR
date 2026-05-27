import numpy as np
import time
from plate_logger import PlateLogger

pl = PlateLogger()

# Mimic yolo box output
box = np.array([10.5, 20.2, 30.8, 40.1], dtype=np.float32)
score = np.float32(0.85)

x1, y1, x2, y2 = map(int, box)
confidence = float(score)
processing_time = (time.time() - time.time() + 0.1) * 1000

print(f"Types: x1={type(x1)}, conf={type(confidence)}, ptime={type(processing_time)}")

pl.log_detection(
    plate="Mimic123",
    detection_confidence=confidence,
    processing_time_ms=processing_time,
    camera_source="mimic",
    frame_number=2,
    image_full_annotated="/path/mimic.webp",
    bbox_x1=x1, bbox_y1=y1, bbox_x2=x2, bbox_y2=y2
)
