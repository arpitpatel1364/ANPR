"""
rtsp_capture.py — Low-latency RTSP capture layer using OpenCV FFmpeg.

Public API (mirrors cv2.VideoCapture)
--------------------------------------
  cap = RTSPCapture(source)   # replaces cv2.VideoCapture(source, cv2.CAP_FFMPEG)
  cap.isOpened()  -> bool
  cap.read()      -> (bool, numpy.ndarray | None)   # BGR uint8
  cap.grab()      -> bool                           # advance internal buffer
  cap.release()   # free all resources

FFmpeg options passed via environment variable before each VideoCapture open:
  - rtsp_transport=tcp        : use TCP (more reliable than UDP for RTSP)
  - stimeout=10000000         : socket timeout 10 s (µs unit)
  - reconnect=1               : auto-reconnect on disconnect
  - reconnect_streamed=1      : reconnect even on streamed sources
  - reconnect_delay_max=5     : max delay between reconnects (seconds)
  - fflags=nobuffer           : disable buffering for minimum latency
  - flags=low_delay           : reduce decoding delay
  - max_delay=500000          : max mux delay 0.5 s
"""

from __future__ import annotations

import logging
import os
from typing import Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# FFmpeg options injected via environment variable (OpenCV ≥ 4.2 picks these up
# automatically when using cv2.CAP_FFMPEG on RTSP/network URLs).
_FFMPEG_RTSP_OPTIONS = (
    "rtsp_transport;tcp"
    "|stimeout;10000000"
    "|reconnect;1"
    "|reconnect_streamed;1"
    "|reconnect_delay_max;5"
    "|fflags;nobuffer"
    "|flags;low_delay"
    "|max_delay;500000"
)


class RTSPCapture:
    """
    Public capture interface — drop-in replacement for cv2.VideoCapture for
    RTSP/network sources using OpenCV with FFmpeg backend.

    For local integer camera indices the FFmpeg options are NOT injected so
    that v4l2 enumeration continues to work normally.
    """

    def __init__(self, source) -> None:
        self._source = source
        self._backend: str = "ffmpeg"
        self._cap: Optional[cv2.VideoCapture] = None

        is_local = isinstance(source, int) or (
            isinstance(source, str) and str(source).isdigit()
        )

        if is_local:
            # Local webcam — no FFmpeg option injection needed
            self._cap = cv2.VideoCapture(int(source))
            self._backend = "v4l2"
        else:
            # Network stream — inject FFmpeg RTSP options then open
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = _FFMPEG_RTSP_OPTIONS
            try:
                self._cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
            finally:
                # Remove the env var so it doesn't bleed into other opens
                os.environ.pop("OPENCV_FFMPEG_CAPTURE_OPTIONS", None)

        if self._cap is not None and self._cap.isOpened():
            try:
                # Keep internal decode buffer at 1 frame for minimum latency
                self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass
            logger.debug(
                "[RTSPCapture] Opened via %s backend: %s", self._backend, source
            )
        else:
            logger.warning(
                "[RTSPCapture] Could not open source '%s' with %s backend.",
                source,
                self._backend,
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def backend(self) -> str:
        """Returns the active backend name ('ffmpeg' or 'v4l2')."""
        return self._backend

    def isOpened(self) -> bool:
        return bool(self._cap and self._cap.isOpened())

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        if not self._cap:
            return False, None
        return self._cap.read()

    def grab(self) -> bool:
        if not self._cap:
            return False
        return self._cap.grab()

    def release(self) -> None:
        if self._cap:
            self._cap.release()
            self._cap = None

    def set(self, prop_id: int, value) -> bool:
        if self._cap:
            return self._cap.set(prop_id, value)
        return False

    def get(self, prop_id: int) -> float:
        if self._cap:
            return self._cap.get(prop_id)
        return 0.0
