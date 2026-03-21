"""
mavlink_diagnostics.py
----------------------
Run this in a second terminal alongside main.py to see every
MAVLink message the Pixhawk sends in real time.

Usage:
    python mavlink_diagnostics.py

Output is printed to terminal AND saved to logs/mavlink_diagnostics.log
Press Ctrl+C to stop.
"""

from pymavlink import mavutil
import datetime
import os
import time

# -------------------------------------------------------
# CONFIG — reads from config.py automatically
# -------------------------------------------------------
try:
    from config import MAVLINK_CONNECTION as CONNECTION
except Exception:
    CONNECTION = "udp:0.0.0.0:14551"

LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "mavlink_diagnostics.log")

# Messages to watch — add any others you want to monitor
WATCH = {
    "CAMERA_FEEDBACK",  # primary capture trigger (distance mode)
    "COMMAND_LONG",  # direct commands inc. DO_DIGICAM_CONTROL
    "COMMAND_INT",  # same but integer variant
    "HEARTBEAT",  # flight mode changes
    "MISSION_ITEM_REACHED",  # waypoint reached events
    "STATUSTEXT",  # autopilot text messages
    "MOUNT_STATUS",  # camera mount pointing angles
    "GPS_RAW_INT",  # GPS fix quality
    "GLOBAL_POSITION_INT",  # position
}

# MAVLink command names for readable output
COMMAND_NAMES = {
    0: "NAV_WAYPOINT",
    16: "NAV_WAYPOINT",
    17: "NAV_LOITER_UNLIM",
    20: "NAV_RETURN_TO_LAUNCH",
    21: "NAV_LAND",
    22: "NAV_TAKEOFF",
    176: "DO_SET_MODE",
    177: "DO_JUMP",
    190: "DO_REPOSITION",
    200: "DO_SET_SERVO",
    201: "DO_REPEAT_SERVO",
    203: "DO_DIGICAM_CONTROL *** CAPTURE TRIGGER ***",
    206: "DO_SET_CAM_TRIGG_DIST (sets interval)",
    211: "DO_SET_CAM_TRIGG_INTERVAL",
    400: "COMPONENT_ARM_DISARM",
}

# ArduPilot flight mode numbers
FLIGHT_MODES = {
    0: "STABILIZE",
    2: "ALT_HOLD",
    3: "AUTO",
    4: "GUIDED",
    5: "LOITER",
    6: "RTL",
    7: "CIRCLE",
    9: "LAND",
    11: "DRIFT",
    13: "SPORT",
    16: "POSHOLD",
    17: "BRAKE",
    18: "THROW",
    20: "GUIDED_NOGPS",
    21: "SMART_RTL",
}

# -------------------------------------------------------
# SETUP
# -------------------------------------------------------
os.makedirs(LOG_DIR, exist_ok=True)


def ts():
    return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]


def log(line, file_handle):
    print(line)
    file_handle.write(line + "\n")
    file_handle.flush()


# -------------------------------------------------------
# MAIN
# -------------------------------------------------------
def main():
    print("=" * 60)
    print("  MAVLink Diagnostics — Connecting...")
    print(f"  Stream : {CONNECTION}")
    print(f"  Log    : {LOG_FILE}")
    print("=" * 60)

    mav = mavutil.mavlink_connection(CONNECTION)
    mav.wait_heartbeat()

    with open(LOG_FILE, "a") as f:
        header = (
            f"\n{'='*60}\n"
            f"Session started: "
            f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"{'='*60}"
        )
        log(header, f)
        log(
            f"[{ts()}] Heartbeat received — system {mav.target_system} "
            f"component {mav.target_component}",
            f,
        )
        log("Watching for messages... (Ctrl+C to stop)\n", f)

        trigger_count = 0
        last_mode = None

        while True:
            msg = mav.recv_match(blocking=True, timeout=2)
            if not msg:
                continue

            msg_type = msg.get_type()
            if msg_type not in WATCH:
                continue

            # ---- CAMERA_FEEDBACK ----
            if msg_type == "CAMERA_FEEDBACK":
                trigger_count += 1
                img_idx = getattr(msg, "img_idx", "?")
                lat = getattr(msg, "lat", 0) / 1e7
                lng = getattr(msg, "lng", 0) / 1e7
                alt_msl = getattr(msg, "alt_msl", 0)
                alt_rel = getattr(msg, "alt_rel", 0)
                roll = getattr(msg, "roll", 0)
                pitch = getattr(msg, "pitch", 0)
                yaw = getattr(msg, "yaw", 0)
                line = (
                    f"[{ts()}] *** CAMERA_FEEDBACK #{trigger_count} "
                    f"| img_idx={img_idx} "
                    f"| lat={lat:.6f} lon={lng:.6f} "
                    f"| alt_msl={alt_msl:.1f}m alt_rel={alt_rel:.1f}m "
                    f"| roll={roll:.1f} pitch={pitch:.1f} yaw={yaw:.1f}"
                )
                log(line, f)

            # ---- COMMAND_LONG / COMMAND_INT ----
            elif msg_type in ("COMMAND_LONG", "COMMAND_INT"):
                cmd_id = msg.command
                cmd_name = COMMAND_NAMES.get(cmd_id, f"CMD_{cmd_id}")
                line = (
                    f"[{ts()}] {msg_type} | cmd={cmd_id} ({cmd_name})"
                    f" | p1={msg.param1:.1f} p2={msg.param2:.1f}"
                    f" p3={msg.param3:.1f} p4={msg.param4:.1f}"
                )
                log(line, f)

            # ---- HEARTBEAT — flight mode ----
            elif msg_type == "HEARTBEAT":
                if msg.get_srcSystem() != mav.target_system:
                    continue
                mode = msg.custom_mode
                mode_str = FLIGHT_MODES.get(mode, f"MODE_{mode}")
                armed = bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                if mode != last_mode:
                    line = (
                        f"[{ts()}] FLIGHT MODE CHANGE → {mode_str} "
                        f"(mode={mode}) | armed={armed}"
                    )
                    log(line, f)
                    last_mode = mode

            # ---- MISSION_ITEM_REACHED ----
            elif msg_type == "MISSION_ITEM_REACHED":
                line = f"[{ts()}] WAYPOINT REACHED | seq={msg.seq}"
                log(line, f)

            # ---- STATUSTEXT ----
            elif msg_type == "STATUSTEXT":
                line = (
                    f"[{ts()}] AUTOPILOT MSG [{msg.severity}]: " f"{msg.text.strip()}"
                )
                log(line, f)

            # ---- MOUNT_STATUS ----
            elif msg_type == "MOUNT_STATUS":
                pan = msg.pointing_a / 100.0
                tilt = msg.pointing_b / 100.0
                roll = msg.pointing_c / 100.0
                line = (
                    f"[{ts()}] MOUNT_STATUS "
                    f"| pan={pan:.1f}° tilt={tilt:.1f}° roll={roll:.1f}°"
                )
                log(line, f)

            # ---- GPS_RAW_INT ----
            elif msg_type == "GPS_RAW_INT":
                fix = msg.fix_type
                sats = msg.satellites_visible
                line = f"[{ts()}] GPS | fix_type={fix} satellites={sats}"
                log(line, f)

            # ---- GLOBAL_POSITION_INT ----
            elif msg_type == "GLOBAL_POSITION_INT":
                lat = msg.lat / 1e7
                lon = msg.lon / 1e7
                alt = msg.alt / 1000.0
                line = (
                    f"[{ts()}] POSITION "
                    f"| lat={lat:.6f} lon={lon:.6f} alt={alt:.1f}m"
                )
                log(line, f)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nDiagnostics stopped.")
