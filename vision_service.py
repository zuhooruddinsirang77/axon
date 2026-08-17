"""
Webcam face-presence detection for State 1 (IDLE_VISION).

Runs OpenCV Haar-cascade face detection on a background thread so the
Pygame render loop never blocks on camera I/O. If no webcam is available
(e.g. running on a dev machine without one), the service degrades to a
no-op that always reports "no face" — the booth still runs, it just won't
auto-advance out of IDLE without the SPACE key override.
"""
import threading
import time

import cv2


class VisionService:
    def __init__(self, camera_index=0):
        self._camera_index = camera_index
        self._cap = None
        self._face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        self._face_present = False
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
            with self._lock:
                self._face_present = len(faces) > 0
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
