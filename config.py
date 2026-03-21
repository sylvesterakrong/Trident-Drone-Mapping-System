
# ============================================================
# Trident Mapping System — Central Configuration
# Edit this file to match your hardware setup.
# No other files need to be changed.
# ============================================================

# --- Camera ---
CAPTURE_METHOD = "feed"
PTZ_FEED = "rtsp://192.168.144.119/554"  # RC10 ground unit RTSP restream7
PTZ_FEED = 0  # or "0" for webcam


# --- PTZ Control (serial/TCP command channel via RC10) ---
PTZ_CONTROL_IP = "192.168.144.119"
PTZ_CONTROL_PORT = 2000

# --- MAVLink ---
# 0.0.0.0 listens on ALL network interfaces including RJ45.
# If running Mission Planner on the same laptop, use udp:127.0.0.1:14551 instead.
MAVLINK_CONNECTION = "udp:127.0.0.1:14551"

# --- Camera Mount Mode ---
# "nadir"  — locks camera to -90° (straight down) for mapping missions
# "free"   — no lock, camera moves freely (use for surveillance/monitoring)
CAMERA_MODE = "free"

# --- Storage ---
SAVE_DIR = "captures"

# --- TCP Listener (manual capture trigger for testing) ---
TCP_HOST = "0.0.0.0"
TCP_PORT = 5555
