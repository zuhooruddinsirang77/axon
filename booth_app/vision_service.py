"""
Webcam face-presence detection for State 1 (IDLE_VISION).

Runs OpenCV Haar-cascade face detection on a background thread so the
Pygame render loop never blocks on camera I/O. If no webcam is available
(e.g. running on a dev machine without one), the service degrades to a
no-op that always reports "no face" — the booth still runs, it just won't
auto-advance out of IDLE without the SPACE key override.
"""
import os
import threading
import time

import cv2

import config

# Haar cascade detection flickers frame-to-frame even for a stationary,
# clearly-visible face (empirically ~30% single-frame miss rate) — without
# this grace window, main.py's continuous face-hold timer would get reset
# on nearly every miss and could go a very long time without ever
# accumulating FACE_DETECT_HOLD_TIME of uninterrupted "present" frames.
FACE_PRESENCE_GRACE = 0.6

# When set (AXON_VISION_DEBUG=1), periodically dumps the raw camera frame
# (with any detected face boxes drawn on it) to temp/vision_debug.jpg, so
# what the camera actually sees can be inspected directly instead of
# guessing from the face_present() boolean alone.
_VISION_DEBUG = os.environ.get("AXON_VISION_DEBUG") == "1"
_DEBUG_SNAPSHOT_PATH = os.path.join(config.TEMP_DIR, "vision_debug.jpg")


class VisionService:
    def __init__(self, camera_index=0):
        self._camera_index = camera_index
        self._cap = None
        self._face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        self._face_present = False
        self._last_face_seen = 0.0
        self._last_snapshot = 0.0
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self._available = False

    def start(self):
        self._cap = cv2.VideoCapture(self._camera_index, cv2.CAP_DSHOW)
        self._available = self._cap is not None and self._cap.isOpened()
        if not self._available:
            print("[VisionService] No webcam detected — face detection disabled, "
                  "use SPACE to advance manually.")
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while self._running:
            ok, frame = self._cap.read()
            if not ok:
                time.sleep(0.1)
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self._face_cascade.detectMultiScale(
                gray, scaleFactor=1.2, minNeighbors=5, minSize=(80, 80)
            )
            now = time.time()
            with self._lock:
                if len(faces) > 0:
                    self._last_face_seen = now
                self._face_present = (now - self._last_face_seen) < FACE_PRESENCE_GRACE

            if _VISION_DEBUG and (now - self._last_snapshot) > 1.0:
                self._last_snapshot = now
                debug_frame = frame.copy()
                for (x, y, w, h) in faces:
                    cv2.rectangle(debug_frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                cv2.putText(debug_frame, f"faces={len(faces)}", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                os.makedirs(config.TEMP_DIR, exist_ok=True)
                cv2.imwrite(_DEBUG_SNAPSHOT_PATH, debug_frame)

            time.sleep(0.05)

    def face_present(self):
        if not self._available:
            return False
        with self._lock:
            return self._face_present

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        if self._cap:
            self._cap.release()
