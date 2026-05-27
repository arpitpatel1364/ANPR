import cv2

def check_cameras():
    # Try indices from 0 to 9
    for i in range(10):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            print(f"Camera found at index: {i}")
            cap.release()
        else:
            print(f"No camera at index: {i}")

check_cameras()