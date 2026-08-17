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

# Self-healing thresholds. On some hardware, cv2.VideoCapture intermittently
# (and unpredictably — extensively investigated without finding a fully
# deterministic trigger) delivers "successful" reads that are actually
# near-blank corrupted buffers: mean brightness ~0 despite a handful of
# stray max-255 pixels, distinct from genuine low light. If that persists,
# the capture device is closed and reopened rather than leaving the booth
# permanently unable to see faces until someone notices and restarts it.
_CORRUPTION_MEAN_THRESHOLD = 2.0
_CORRUPTION_DURATION = 2.0
_REOPEN_COOLDOWN = 3.0


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
        self._last_frame_stats = None
        self._corruption_since = None
        self._last_reopen = 0.0
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self._available = False
        self._open_event = threading.Event()

    def start(self):
        print(f"[VisionService] AXON_VISION_DEBUG env var = {os.environ.get('AXON_VISION_DEBUG')!r} "
              f"-> debug snapshots {'ON' if _VISION_DEBUG else 'OFF'} ({_DEBUG_SNAPSHOT_PATH})")
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        # Block briefly so callers checking `.face_present()`/`._available`
        # right after start() see the real result, not a false "not
        # available" from before the background thread has opened it.
        self._open_event.wait(timeout=5.0)
        if not self._available:
            print("[VisionService] No webcam detected — face detection disabled, "
                  "use SPACE to advance manually.")

    def _open_capture(self):
        self._cap = cv2.VideoCapture(self._camera_index, cv2.CAP_DSHOW)
        self._available = self._cap is not None and self._cap.isOpened()

    def _reopen(self):
        try:
            if self._cap:
                self._cap.release()
        except Exception:
            pass
        time.sleep(0.3)
        self._open_capture()
        print(f"[VisionService] reopened camera, isOpened={self._available}", flush=True)

    def _loop(self):
        # The VideoCapture object (DirectShow, which is COM-based) is
        # created AND read entirely on this one thread with an explicit
        # COM apartment initialized — previously it was constructed on the
        # main thread in start() but read from here, an unmarshaled
        # cross-thread/cross-apartment COM object use that's a known class
        # of source for exactly the kind of silent frame corruption seen
        # here (reads "succeed" but return near-blank buffers).
        try:
            import pythoncom
            pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
            com_initialized = True
        except Exception as e:
            print(f"[VisionService] COM init failed (continuing without it): {e}")
            com_initialized = False

        try:
            self._open_capture()
        finally:
            self._open_event.set()

        if not self._available:
            if com_initialized:
                pythoncom.CoUninitialize()
            return

        while self._running:
            try:
                self._tick()
            except Exception as e:
                print(f"[VisionService] _loop error (thread would otherwise die silently): {e}")
                time.sleep(0.5)

        try:
            if self._cap:
                self._cap.release()
        except Exception:
            pass
        if com_initialized:
            pythoncom.CoUninitialize()

    def _tick(self):
        ok, frame = self._cap.read()
        if not ok:
            time.sleep(0.1)
            return
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self._face_cascade.detectMultiScale(
            gray, scaleFactor=1.2, minNeighbors=5, minSize=(80, 80)
        )
        now = time.time()
        mean = float(frame.mean())
        with self._lock:
            if len(faces) > 0:
                self._last_face_seen = now
            self._face_present = (now - self._last_face_seen) < FACE_PRESENCE_GRACE
            self._last_frame_stats = (now, mean, int(frame.min()), int(frame.max()))

        if mean < _CORRUPTION_MEAN_THRESHOLD:
            if self._corruption_since is None:
                self._corruption_since = now
            elif (now - self._corruption_since > _CORRUPTION_DURATION
                    and now - self._last_reopen > _REOPEN_COOLDOWN):
                print(f"[VisionService] sustained corrupted frames (mean<{_CORRUPTION_MEAN_THRESHOLD} "
                      f"for {now - self._corruption_since:.1f}s) — reopening camera", flush=True)
                self._reopen()
                self._corruption_since = None
                self._last_reopen = now
        else:
            self._corruption_since = None

        if _VISION_DEBUG and (now - self._last_snapshot) > 1.0:
            self._last_snapshot = now
            debug_frame = frame.copy()
            for (x, y, w, h) in faces:
                cv2.rectangle(debug_frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(debug_frame, f"faces={len(faces)}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            os.makedirs(config.TEMP_DIR, exist_ok=True)
            wrote = cv2.imwrite(_DEBUG_SNAPSHOT_PATH, debug_frame)
            print(f"[VisionService] snapshot={wrote} brightness_mean={frame.mean():.1f} "
                  f"min={frame.min()} max={frame.max()}", flush=True)

        time.sleep(0.05)

    def face_present(self):
        if not self._available:
            return False
        with self._lock:
            return self._face_present

    def get_last_frame_stats(self):
        """Diagnostic: (timestamp, mean, min, max) of the most recent frame
        the background thread actually captured, without racing it for a
        second concurrent read on the same VideoCapture object."""
        with self._lock:
            return self._last_frame_stats


    def stop(self):
        # release() now happens inside _loop() itself, on the same thread
        # that opened the capture — join() waits for that cleanup to finish.
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
