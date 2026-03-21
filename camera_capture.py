# import cv2
# import numpy as np
# import mss
# import threading
# import time
# import datetime
# from config import CAPTURE_METHOD, PTZ_FEED, PTZ_CONTROL_IP, PTZ_CONTROL_PORT, SCREEN_REGION


# class CameraCapture:
#     """
#     Robust surveillance-grade camera capture module.
#     Supports:
#         - RTSP / USB feed
#         - Screen capture
#     Features:
#         - Background frame acquisition
#         - Frame timestamping (UTC)
#         - Auto reconnect
#         - Low latency buffering
#         - Thread safety
#         - Frame ID tracking
#     """

#     def __init__(self, target_fps=30):
#         self.target_fps = target_fps
#         self.frame_data = None
#         self.lock = threading.Lock()
#         self.running = True
#         self.frame_id = 0

#         if CAPTURE_METHOD == "feed":
#             self.cap = None
#             self._connect_feed()
#             self._start_feed_thread()

#         elif CAPTURE_METHOD == "screen":
#             self.sct = mss.mss()
#             self._start_screen_thread()

#         else:
#             raise ValueError("Invalid CAPTURE_METHOD in config")

#     # --------------------------------------------------
#     # FEED MODE (RTSP / USB)
#     # --------------------------------------------------

#     def _connect_feed(self):
#         while self.running:
#             try:
#                 print("Connecting to camera feed...")
#                 self.cap = cv2.VideoCapture(PTZ_FEED, cv2.CAP_FFMPEG)

#                 # Reduce latency
#                 self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

#                 if self.cap.isOpened():
#                     print("Camera connected successfully.")
#                     return
#             except Exception as e:
#                 print("Camera connection error:", e)

#             print("Retrying camera connection in 2 seconds...")
#             time.sleep(2)

#     def _feed_loop(self):
#         frame_interval = 1.0 / self.target_fps

#         while self.running:
#             start_time = time.time()

#             if not self.cap or not self.cap.isOpened():
#                 self._connect_feed()
#                 continue

#             ret, frame = self.cap.read()

#             if not ret:
#                 print("Frame read failed. Reconnecting...")
#                 self.cap.release()
#                 self._connect_feed()
#                 continue

#             timestamp = time.time()

#             with self.lock:
#                 self.frame_id += 1
#                 self.frame_data = {
#                     "image": frame,
#                     "timestamp_unix": timestamp,
#                     "timestamp_utc": datetime.datetime.utcnow().isoformat(),
#                     "frame_id": self.frame_id
#                 }

#             # FPS throttle
#             elapsed = time.time() - start_time
#             sleep_time = frame_interval - elapsed
#             if sleep_time > 0:
#                 time.sleep(sleep_time)

#     def _start_feed_thread(self):
#         thread = threading.Thread(target=self._feed_loop, daemon=True)
#         thread.start()

#     # --------------------------------------------------
#     # SCREEN MODE
#     # --------------------------------------------------

#     def _screen_loop(self):
#         frame_interval = 1.0 / self.target_fps

#         while self.running:
#             start_time = time.time()

#             sct_img = self.sct.grab(SCREEN_REGION)
#             frame = np.array(sct_img)
#             frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

#             timestamp = time.time()

#             with self.lock:
#                 self.frame_id += 1
#                 self.frame_data = {
#                     "image": frame,
#                     "timestamp_unix": timestamp,
#                     "timestamp_utc": datetime.datetime.utcnow().isoformat(),
#                     "frame_id": self.frame_id
#                 }

#             elapsed = time.time() - start_time
#             sleep_time = frame_interval - elapsed
#             if sleep_time > 0:
#                 time.sleep(sleep_time)

#     def _start_screen_thread(self):
#         thread = threading.Thread(target=self._screen_loop, daemon=True)
#         thread.start()

#     # --------------------------------------------------
#     # PUBLIC API
#     # --------------------------------------------------

#     def get_frame(self):
#         """
#         Returns latest frame and metadata.
#         Non-blocking.
#         """
#         with self.lock:
#             if self.frame_data is None:
#                 return None

#             # Return copy to prevent race conditions
#             return {
#                 "image": self.frame_data["image"].copy(),
#                 "timestamp_unix": self.frame_data["timestamp_unix"],
#                 "timestamp_utc": self.frame_data["timestamp_utc"],
#                 "frame_id": self.frame_data["frame_id"]
#             }

#     def get_frame_age(self):
#         """
#         Returns how old the latest frame is (seconds).
#         Useful for surveillance latency checks.
#         """
#         with self.lock:
#             if self.frame_data is None:
#                 return None
#             return time.time() - self.frame_data["timestamp_unix"]

#     def stop(self):
#         """
#         Clean shutdown.
#         """
#         self.running = False

#         if CAPTURE_METHOD == "feed" and self.cap:
#             self.cap.release()


import cv2
import numpy as np
import threading
import time
import datetime
import requests
from config import CAPTURE_METHOD, PTZ_FEED, PTZ_CONTROL_IP, PTZ_CONTROL_PORT


class CameraCapture:
    """
    Hybrid camera system:
    - Try real camera twice
    - Fallback to web simulation image
    - Always provides timestamped frames
    """

    def __init__(self, target_fps=15):
        self.target_fps = target_fps
        self.frame_data = None
        self.lock = threading.Lock()
        self.running = True
        self.frame_id = 0
        self.simulation_mode = False

        if CAPTURE_METHOD == "feed":
            success = self._try_connect_feed(max_attempts=2)

            if success:
                print("Using real camera feed.")
                threading.Thread(target=self._feed_loop, daemon=True).start()
            else:
                print("⚠ Camera unavailable. Switching to SIMULATION MODE.")
                self.simulation_mode = True
                threading.Thread(target=self._simulation_loop, daemon=True).start()

        else:
            print("Simulation mode enabled (no feed selected).")
            self.simulation_mode = True
            threading.Thread(target=self._simulation_loop, daemon=True).start()

    # --------------------------------------------------
    # TRY CAMERA CONNECTION
    # --------------------------------------------------

    def _try_connect_feed(self, max_attempts=2):
        for attempt in range(max_attempts):
            print(f"Connecting to camera feed... Attempt {attempt+1}")

            cap = cv2.VideoCapture(PTZ_FEED)

            if cap.isOpened():
                self.cap = cap
                return True

            cap.release()
            time.sleep(1)

        return False

    # --------------------------------------------------
    # REAL CAMERA LOOP
    # --------------------------------------------------

    def _feed_loop(self):
        while self.running:
            ret, frame = self.cap.read()

            if not ret:
                print("Camera lost. Switching to simulation.")
                self.simulation_mode = True
                threading.Thread(target=self._simulation_loop, daemon=True).start()
                return

            self._store_frame(frame)
            time.sleep(1 / self.target_fps)

    # --------------------------------------------------
    # SIMULATION LOOP (Web Image)
    # --------------------------------------------------

    def _simulation_loop(self):
        while self.running:
            try:
                # Random aerial image
                url = "https://source.unsplash.com/1280x720/?aerial,drone,landscape"
                response = requests.get(url, timeout=5)
                img_array = np.asarray(bytearray(response.content), dtype=np.uint8)
                frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

                if frame is not None:
                    self._store_frame(frame)

            except Exception as e:
                print("Simulation image fetch failed:", e)

            time.sleep(1 / self.target_fps)

    # --------------------------------------------------
    # STORE FRAME WITH TIMESTAMP
    # --------------------------------------------------

    def _store_frame(self, frame):
        timestamp_unix = time.time()
        timestamp_utc = datetime.datetime.utcnow().isoformat()

        with self.lock:
            self.frame_id += 1
            self.frame_data = {
                "image": frame,
                "timestamp_unix": timestamp_unix,
                "timestamp_utc": timestamp_utc,
                "frame_id": self.frame_id,
                "simulation_mode": self.simulation_mode,
            }

    # --------------------------------------------------
    # PUBLIC API
    # --------------------------------------------------

    def get_frame(self):
        with self.lock:
            if self.frame_data is None:
                return None
            return {
                "image": self.frame_data["image"].copy(),
                "timestamp_unix": self.frame_data["timestamp_unix"],
                "timestamp_utc": self.frame_data["timestamp_utc"],
                "frame_id": self.frame_data["frame_id"],
                "simulation_mode": self.frame_data["simulation_mode"],
            }

    def stop(self):
        self.running = False
        if hasattr(self, "cap"):
            self.cap.release()
