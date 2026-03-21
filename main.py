import os
import cv2
import math
import datetime
import logging
import time
from config import SAVE_DIR, MAVLINK_CONNECTION, TCP_HOST, TCP_PORT
from mavlink_reader import MAVLinkReader
from camera_capture import CameraCapture
from geotag import embed_gps
from tcp_listener import TCPListener


def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)


def setup_logger():
    ensure_dir("logs")
    log_file = os.path.join("logs", "capture_log.txt")
    logging.basicConfig(
        filename=log_file,
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return logging.getLogger()


def capture_image(mav_reader, cam, logger, trigger_source="UNKNOWN"):
    try:
        frame_data = cam.get_frame()
        if frame_data is None:
            print("No frame available")
            logger.warning(f"[{trigger_source}] Capture skipped: no frame")
            return

        telemetry = mav_reader.get_telemetry()

        if telemetry["fix_type"] < 3 or telemetry["lat"] is None:
            print(
                f"No GPS fix (fix_type={telemetry['fix_type']}, "
                f"satellites={telemetry['satellites']})"
            )
            logger.warning(
                f"[{trigger_source}] Capture skipped: "
                f"no GPS fix (fix_type={telemetry['fix_type']})"
            )
            return

        frame = frame_data["image"]
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y%m%d_%H%M%S"
        )
        file_path = os.path.join(SAVE_DIR, f"image_{timestamp}.jpg")

        cv2.imwrite(file_path, frame)
        embed_gps(file_path, telemetry, frame_data)

        # Logging — use actual camera pan if available, fall back to yaw
        camera_pan = telemetry.get("camera_pan")
        yaw_rad = telemetry.get("yaw")

        if camera_pan is not None:
            direction_str = (
                f"CamPan: {round(camera_pan % 360, 1)}° | "
                f"CamTilt: {round(telemetry.get('camera_tilt', 0), 1)}°"
            )
        elif yaw_rad is not None:
            direction_str = f"Yaw (fallback): {round(math.degrees(yaw_rad) % 360, 1)}°"
        else:
            direction_str = "Direction: unavailable"

        print(
            f"[{trigger_source}] Saved: {os.path.basename(file_path)} | "
            f"GPS: ({telemetry['lat']:.6f}, {telemetry['lon']:.6f}, "
            f"{telemetry['alt']:.1f}m) | "
            f"Sats: {telemetry['satellites']} | {direction_str}"
        )

        logger.info(
            f"[{trigger_source}] Captured: {file_path} | "
            f"GPS: ({telemetry['lat']}, {telemetry['lon']}, {telemetry['alt']}m) | "
            f"RelAlt: {telemetry['relative_alt']}m | "
            f"Sats: {telemetry['satellites']} | FixType: {telemetry['fix_type']} | "
            f"CamPan: {camera_pan} | "
            f"CamTilt: {telemetry.get('camera_tilt')} | "
            f"Sim: {frame_data.get('simulation_mode')}"
        )

    except Exception as e:
        print(f"Error during capture: {e}")
        logger.error(f"[{trigger_source}] Capture error: {e}")


def main():
    ensure_dir(SAVE_DIR)
    logger = setup_logger()
    cam = CameraCapture()

    # --------------------------------------------------
    # MAVLink trigger callback — fired by Pixhawk during
    # QGC Survey mission via DO_DIGICAM_CONTROL or
    # DO_SET_CAM_TRIGG_DIST. Camera is locked to nadir
    # automatically on connection via Telem 2.
    # --------------------------------------------------
    def on_mavlink_trigger():
        count = mav_reader.get_trigger_count()
        logger.info(f"MAVLink trigger #{count} received from Pixhawk")
        capture_image(mav_reader, cam, logger, trigger_source=f"MAVLINK_{count}")

    def on_mission_complete():
        print("")
        print("=" * 55)
        print("  ✓  MAPPING MISSION COMPLETE")
        print(f"     Total images captured: {mav_reader.get_trigger_count()}")
        print(f"     Images saved to: {SAVE_DIR}/")
        print("     Stopping capture loop.")
        print("=" * 55)
        print("")
        logger.info(
            f"Mission complete | "
            f"Total captures: {mav_reader.get_trigger_count()} | "
            f"Saved to: {SAVE_DIR}/"
        )

    mav_reader = MAVLinkReader(
        connection_string=MAVLINK_CONNECTION,
        on_camera_trigger=on_mavlink_trigger,
        on_mission_complete=on_mission_complete,
    )

    # --------------------------------------------------
    # TCP listener — manual trigger for testing
    # Usage: echo "CAPTURE" | nc 127.0.0.1 5555
    # --------------------------------------------------
    def on_tcp_command():
        print("Manual TCP capture triggered")
        logger.info("TCP CAPTURE command received")
        capture_image(mav_reader, cam, logger, trigger_source="TCP_MANUAL")

    tcp_listener = TCPListener(host=TCP_HOST, port=TCP_PORT, callback=on_tcp_command)
    tcp_listener.start()

    print("=" * 55)
    print("  Trident Drone Mapping System 🔱 — Ready")
    print(f"  MAVLink : {MAVLINK_CONNECTION}")
    print("  Camera  : nadir lock sent via Telem 2")
    print(f"  Manual  : echo CAPTURE | nc 127.0.0.1 {TCP_PORT}")
    print("=" * 55)
    logger.info("System started | Nadir lock sent | Awaiting triggers")

    try:
        while True:
            cv2.waitKey(100)
    except KeyboardInterrupt:
        print("\nShutting down...")
        logger.info("Shutdown by KeyboardInterrupt")
        mav_reader.stop()
        cam.stop()


if __name__ == "__main__":
    main()