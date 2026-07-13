"""
rtsp_capture.py — GStreamer-based low-latency RTSP capture layer.

Architecture
------------
* Primary backend  : GStreamer via PyGObject (gi.repository.Gst).
  Pipeline: rtspsrc → decodebin → videoconvert → appsink
  appsink is configured with drop=true, max-buffers=1, sync=false so only the
  latest decoded frame is ever held, eliminating buffer-lag entirely.

* Fallback backend : OpenCV cv2.VideoCapture(source, cv2.CAP_FFMPEG) — identical
  to the behaviour that existed before this module was introduced.

Public API (mirrors cv2.VideoCapture)
--------------------------------------
  cap = RTSPCapture(source)   # replaces cv2.VideoCapture(source, cv2.CAP_FFMPEG)
  cap.isOpened()  -> bool
  cap.read()      -> (bool, numpy.ndarray | None)   # BGR uint8
  cap.grab()      -> bool                           # advance internal buffer
  cap.release()   # free all resources

Frame format guarantee
-----------------------
Both backends always return BGR uint8 numpy arrays — identical to what the
upstream pipeline expected from cv2.VideoCapture.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from typing import Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GStreamer availability probe
# ---------------------------------------------------------------------------
_GST_AVAILABLE: bool = False

def _probe_gstreamer() -> bool:
    """Return True if GStreamer + PyGObject bindings are importable and init OK."""
    try:
        # python3-gi lives outside the venv on typical Ubuntu installs.
        if "/usr/lib/python3/dist-packages" not in sys.path:
            sys.path.insert(0, "/usr/lib/python3/dist-packages")

        import gi  # type: ignore
        gi.require_version("Gst", "1.0")
        gi.require_version("GstApp", "1.0")
        from gi.repository import Gst, GstApp  # noqa: F401  # type: ignore

        if not Gst.is_initialized():
            ok, _ = Gst.init_check(None)
            if not ok:
                return False

        logger.info("GStreamer %s detected — using low-latency pipeline.", Gst.version_string())
        return True
    except Exception as exc:  # pragma: no cover
        logger.debug("GStreamer probe failed: %s", exc)
        return False


_GST_AVAILABLE = _probe_gstreamer()


# ---------------------------------------------------------------------------
# GStreamer capture backend
# ---------------------------------------------------------------------------

class _GStreamerCapture:
    """
    Low-latency RTSP capture via GStreamer appsink.

    The pipeline drains the network jitter buffer aggressively:
      rtspsrc latency=0 drop-on-latency=true
        → decodebin
        → videoconvert
        → appsink drop=true max-buffers=1 sync=false

    Only the most recent decoded frame is ever retained; stale frames are
    automatically discarded by appsink before we even call pull_sample().
    """

    _PIPELINE_TMPL = (
        "rtspsrc location={url} latency=0 drop-on-latency=true protocols=tcp "
        "! decodebin "
        "! videoconvert "
        "! video/x-raw,format=BGR "
        "! appsink name=sink drop=true max-buffers=1 sync=false"
    )

    def __init__(self, source: str) -> None:
        self._source = source
        self._pipeline: Optional[object] = None  # Gst.Pipeline
        self._appsink: Optional[object] = None   # GstApp.AppSink
        self._opened: bool = False
        self._lock = threading.Lock()

        self._open()

    # ------------------------------------------------------------------
    def _open(self) -> None:
        try:
            if "/usr/lib/python3/dist-packages" not in sys.path:
                sys.path.insert(0, "/usr/lib/python3/dist-packages")

            import gi  # type: ignore
            gi.require_version("Gst", "1.0")
            from gi.repository import Gst  # type: ignore

            if not Gst.is_initialized():
                Gst.init(None)

            pipeline_str = self._PIPELINE_TMPL.format(url=self._source)
            self._pipeline = Gst.parse_launch(pipeline_str)
            self._appsink = self._pipeline.get_by_name("sink")

            if self._appsink is None:
                raise RuntimeError("Could not find appsink element in GStreamer pipeline.")

            # Set PLAYING and wait up to 20 s for RTSP negotiation
            self._pipeline.set_state(Gst.State.PLAYING)
            state_change, _state, _pending = self._pipeline.get_state(20 * Gst.SECOND)

            if state_change == Gst.StateChangeReturn.FAILURE:
                raise RuntimeError("GStreamer pipeline failed to reach PLAYING state.")

            # Verify we can pull at least one sample within 10 s
            sample = self._appsink.try_pull_sample(10 * Gst.SECOND)
            if sample is None:
                raise RuntimeError("GStreamer pipeline opened but produced no frames within 10 s.")

            # Cache the sample so the first read() call returns it immediately
            self._pending_sample = sample
            self._opened = True
            logger.info("[GStreamer] Pipeline PLAYING for source: %s", self._source)

        except Exception as exc:
            logger.warning("[GStreamer] Failed to open '%s': %s — will fall back to FFmpeg.", self._source, exc)
            self._cleanup_pipeline()
            self._opened = False

    # ------------------------------------------------------------------
    def _cleanup_pipeline(self) -> None:
        try:
            if self._pipeline is not None:
                if "/usr/lib/python3/dist-packages" not in sys.path:
                    sys.path.insert(0, "/usr/lib/python3/dist-packages")
                import gi  # type: ignore
                gi.require_version("Gst", "1.0")
                from gi.repository import Gst  # type: ignore
                self._pipeline.set_state(Gst.State.NULL)
        except Exception:
            pass
        self._pipeline = None
        self._appsink = None

    # ------------------------------------------------------------------
    def isOpened(self) -> bool:
        return self._opened

    # ------------------------------------------------------------------
    def _sample_to_frame(self, sample) -> Optional[np.ndarray]:
        """Convert a Gst.Sample to a BGR uint8 numpy array."""
        try:
            buf = sample.get_buffer()
            caps = sample.get_caps()
            structure = caps.get_structure(0)
            width = structure.get_int("width").value
            height = structure.get_int("height").value

            success, map_info = buf.map(0)  # GST_MAP_READ = 0
            if not success:
                return None

            try:
                # Buffer is BGR (requested via video/x-raw,format=BGR)
                arr = np.frombuffer(map_info.data, dtype=np.uint8)
                frame = arr.reshape((height, width, 3)).copy()  # copy before unmap
            finally:
                buf.unmap(map_info)

            return frame
        except Exception as exc:
            logger.debug("[GStreamer] sample_to_frame error: %s", exc)
            return None

    # ------------------------------------------------------------------
    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        """
        Return (True, frame_BGR) for the latest available frame, or
        (False, None) on pipeline error / no frame within 2 s.
        """
        if not self._opened:
            return False, None

        with self._lock:
            try:
                if "/usr/lib/python3/dist-packages" not in sys.path:
                    sys.path.insert(0, "/usr/lib/python3/dist-packages")
                import gi  # type: ignore
                gi.require_version("Gst", "1.0")
                from gi.repository import Gst  # type: ignore

                # Return the cached first-frame sample if present
                if hasattr(self, "_pending_sample") and self._pending_sample is not None:
                    sample = self._pending_sample
                    self._pending_sample = None
                else:
                    # Wait up to 2 s for the next decoded frame.
                    # Because appsink has drop=true / max-buffers=1 the returned
                    # sample is always the most recent one decoded.
                    sample = self._appsink.try_pull_sample(2 * Gst.SECOND)

                if sample is None:
                    return False, None

                frame = self._sample_to_frame(sample)
                if frame is None:
                    return False, None

                return True, frame

            except Exception as exc:
                logger.error("[GStreamer] read() error: %s", exc)
                return False, None

    # ------------------------------------------------------------------
    def grab(self) -> bool:
        """
        Advance the internal buffer (drop the current queued sample).
        Since appsink already operates with max-buffers=1 / drop=true the
        next read() will always fetch the latest decoded frame regardless;
        this method is a no-op kept for API compatibility.
        """
        return self._opened

    # ------------------------------------------------------------------
    def release(self) -> None:
        with self._lock:
            self._cleanup_pipeline()
            self._opened = False
        logger.info("[GStreamer] Pipeline released for source: %s", self._source)

    # ------------------------------------------------------------------
    def set(self, prop_id: int, value) -> bool:  # noqa: D401
        """Stub — GStreamer pipeline properties are baked into the pipeline string."""
        return False

    def get(self, prop_id: int):  # noqa: D401
        """Stub."""
        return 0.0


# ---------------------------------------------------------------------------
# FFmpeg / OpenCV fallback backend  (thin wrapper, identical to existing code)
# ---------------------------------------------------------------------------

class _FFmpegCapture:
    """
    Thin wrapper around cv2.VideoCapture that mirrors the RTSPCapture API.
    Used when GStreamer is unavailable or fails to open the stream.
    """

    def __init__(self, source) -> None:
        self._source = source
        if isinstance(source, int) or (isinstance(source, str) and str(source).isdigit()):
            self._cap = cv2.VideoCapture(int(source))
        else:
            self._cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)

        if self._cap.isOpened():
            try:
                self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass

    def isOpened(self) -> bool:
        return self._cap.isOpened() if self._cap else False

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

    def set(self, prop_id: int, value) -> bool:
        if self._cap:
            return self._cap.set(prop_id, value)
        return False

    def get(self, prop_id: int):
        if self._cap:
            return self._cap.get(prop_id)
        return 0.0


# ---------------------------------------------------------------------------
# Public factory — RTSPCapture
# ---------------------------------------------------------------------------

class RTSPCapture:
    """
    Public capture interface — drop-in replacement for cv2.VideoCapture for
    RTSP sources.

    Selection logic
    ---------------
    1. If GStreamer bindings are available *and* the source is a string URL
       (not a webcam index), attempt to open a GStreamer appsink pipeline.
    2. If step 1 fails or GStreamer is unavailable, fall back to FFmpeg.

    The caller never needs to know which backend is active; the returned
    (ret, frame) tuples are always BGR uint8 numpy arrays.
    """

    def __init__(self, source) -> None:
        self._source = source
        self._backend: str = "ffmpeg"
        self._cap: _GStreamerCapture | _FFmpegCapture

        is_local_device = isinstance(source, int) or (
            isinstance(source, str) and source.isdigit()
        )

        gst_tried = False
        if _GST_AVAILABLE and not is_local_device:
            gst_tried = True
            gst_cap = _GStreamerCapture(source)
            if gst_cap.isOpened():
                self._cap = gst_cap
                self._backend = "gstreamer"
                logger.info("[RTSPCapture] Using GStreamer backend for: %s", source)
                return
            else:
                logger.warning(
                    "[RTSPCapture] GStreamer backend failed for '%s'. "
                    "Falling back to FFmpeg.",
                    source,
                )

        # FFmpeg fallback
        self._cap = _FFmpegCapture(source)
        if gst_tried:
            logger.info("[RTSPCapture] FFmpeg fallback active for: %s", source)
        else:
            logger.debug("[RTSPCapture] Using FFmpeg backend for: %s", source)

    # ------------------------------------------------------------------
    @property
    def backend(self) -> str:
        """Returns 'gstreamer' or 'ffmpeg' — which backend is active."""
        return self._backend

    def isOpened(self) -> bool:
        return self._cap.isOpened()

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        return self._cap.read()

    def grab(self) -> bool:
        return self._cap.grab()

    def release(self) -> None:
        self._cap.release()

    def set(self, prop_id: int, value) -> bool:
        return self._cap.set(prop_id, value)

    def get(self, prop_id: int):
        return self._cap.get(prop_id)
