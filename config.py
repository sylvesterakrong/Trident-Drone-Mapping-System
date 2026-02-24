# Configuration file

# PX4 MAVLink connection
MAVLINK_CONN = "udp:127.0.0.1:14550"  # Change to real COM/UDP for PX4

# PTZ feed
# PTZ_FEED = "rtsp://192.168.144.1"  # Or use camera window coordinates for screen capture

# Save geotagged images here
SAVE_DIR = "C:\\DeltaQuad\\drone_geotag\\geotagged_images"

# Simulate PTZ feed with dummy video or webcam
PTZ_FEED = 0  # or "0" for webcam
# PTZ_FEED = "rtsp://192.168.144.119/live" 

# Capture method: "feed" for RTSP/USB, "screen" for screen capture
CAPTURE_METHOD = "feed"

# Screen capture region (if CAPTURE_METHOD = "screen")
SCREEN_REGION = {"top": 100, "left": 100, "width": 1280, "height": 720}