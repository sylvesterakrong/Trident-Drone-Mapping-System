from pymavlink import mavutil
import threading
import time


class MAVLinkReader:
    # ArduPilot custom flight modes
    _MODE_AUTO  = 3
    _MODE_RTL   = 11
    _MODE_LAND  = 9

    def __init__(self, connection_string,
                 on_camera_trigger=None,
                 on_mission_complete=None):
        self.connection_string    = connection_string
        self.on_camera_trigger    = on_camera_trigger
        self.on_mission_complete  = on_mission_complete

        # Single connection — no double-init
        self.mav = mavutil.mavlink_connection(connection_string)
        self.mav.wait_heartbeat()
        print(f"Heartbeat received. Connected to system "
              f"{self.mav.target_system} component {self.mav.target_component}")

        self.telemetry = {
            "lat": None,
            "lon": None,
            "alt": None,
            "relative_alt": None,
            "vx": 0,
            "vy": 0,
            "vz": 0,
            "yaw": None,
            "pitch": None,
            "roll": None,
            "fix_type": 0,
            "satellites": 0,
            "gps_timestamp": None,
            "system_timestamp": None,
            "camera_pan": None,
            "camera_tilt": None,
            "camera_roll": None,
        }

        self.lock = threading.Lock()
        self.running = True
        self._trigger_count  = 0
        self._last_mode      = None   # track previous flight mode
        self._mission_active = False  # true once AUTO mode seen
        self._mission_ended  = False  # fire callback only once

        threading.Thread(target=self._reader_loop, daemon=True).start()

        # Respect CAMERA_MODE from config
        # "nadir" = lock to -90° for mapping
        # "free"  = no lock, camera moves freely
        try:
            from config import CAMERA_MODE
        except Exception:
            CAMERA_MODE = "free"

        if CAMERA_MODE == "nadir":
            threading.Timer(2.0, self.lock_camera_nadir).start()
            print("Camera mode: NADIR LOCK (-90°)")
        else:
            print("Camera mode: FREE — camera moves freely, no lock sent")

    # --------------------------------------------------
    # Nadir Lock
    # --------------------------------------------------
    def lock_camera_nadir(self):
        try:
            self.mav.mav.command_long_send(
                self.mav.target_system,
                self.mav.target_component,
                mavutil.mavlink.MAV_CMD_DO_MOUNT_CONTROL,
                0,
                -90,    # tilt: straight down
                0,      # roll
                0,      # pan
                0, 0, 0,
                mavutil.mavlink.MAV_MOUNT_MODE_MAVLINK_TARGETING
            )
            print("Camera locked to nadir (-90° tilt)")
        except Exception as e:
            print(f"Nadir lock failed: {e}")

    # --------------------------------------------------
    # Background Reader Thread
    # --------------------------------------------------
    def _reader_loop(self):
        while self.running:
            msg = self.mav.recv_match(blocking=True, timeout=1)
            if not msg:
                continue

            msg_type = msg.get_type()

            with self.lock:
                if msg_type == "GLOBAL_POSITION_INT":
                    self.telemetry["lat"]          = msg.lat / 1e7
                    self.telemetry["lon"]          = msg.lon / 1e7
                    self.telemetry["alt"]          = msg.alt / 1000.0
                    self.telemetry["relative_alt"] = msg.relative_alt / 1000.0
                    self.telemetry["vx"]           = msg.vx / 100.0
                    self.telemetry["vy"]           = msg.vy / 100.0
                    self.telemetry["vz"]           = msg.vz / 100.0
                    self.telemetry["gps_timestamp"]   = msg.time_boot_ms
                    self.telemetry["system_timestamp"] = time.time()

                elif msg_type == "ATTITUDE":
                    self.telemetry["yaw"]   = msg.yaw
                    self.telemetry["pitch"] = msg.pitch
                    self.telemetry["roll"]  = msg.roll

                elif msg_type == "GPS_RAW_INT":
                    self.telemetry["fix_type"]  = msg.fix_type
                    self.telemetry["satellites"] = msg.satellites_visible

                elif msg_type == "MOUNT_STATUS":
                    self.telemetry["camera_pan"]  = msg.pointing_a / 100.0
                    self.telemetry["camera_tilt"] = msg.pointing_b / 100.0
                    self.telemetry["camera_roll"] = msg.pointing_c / 100.0

            # --------------------------------------------------
            # Mission completion detection via HEARTBEAT
            # Logic: once we see AUTO mode (mission running),
            # if the mode then changes to RTL or LAND the
            # autonomous mission has finished.
            # --------------------------------------------------
            if msg_type == "HEARTBEAT" and msg.get_srcSystem() == self.mav.target_system:
                current_mode = msg.custom_mode

                if current_mode == self._MODE_AUTO:
                    self._mission_active = True

                if (self._mission_active
                        and not self._mission_ended
                        and self._last_mode == self._MODE_AUTO
                        and current_mode in (self._MODE_RTL, self._MODE_LAND)):
                    self._mission_ended = True
                    print("Mission complete detected (AUTO → RTL/LAND)")
                    if self.on_mission_complete:
                        threading.Thread(
                            target=self.on_mission_complete,
                            daemon=True
                        ).start()

                self._last_mode = current_mode

            # --------------------------------------------------
            # Camera trigger detection — outside telemetry lock
            # so a slow capture never blocks GPS updates.
            #
            # PRIMARY: CAMERA_FEEDBACK
            #   Pixhawk fires this for every actual capture event
            #   when DO_SET_CAM_TRIGG_DIST is active (QGC Survey
            #   distance mode). This is what produces the 810 events.
            #
            # SECONDARY: COMMAND_LONG cmd 203 (DO_DIGICAM_CONTROL)
            #   Direct per-waypoint shutter command. Used for manual
            #   or waypoint-level triggers only.
            #
            # NOTE: DO_SET_CAM_TRIGG_DIST (206) just sets the interval
            #   — it is NOT a capture event, only ACK it and move on.
            # --------------------------------------------------
            if msg_type == "CAMERA_FEEDBACK":
                self._trigger_count += 1
                print(f"CAMERA_FEEDBACK trigger #{self._trigger_count} "
                      f"img_idx={getattr(msg, 'img_idx', '?')}")
                if self.on_camera_trigger:
                    threading.Thread(
                        target=self.on_camera_trigger,
                        daemon=True
                    ).start()

            elif msg_type in ("COMMAND_LONG", "COMMAND_INT"):
                if msg.command == 203:   # DO_DIGICAM_CONTROL — direct shutter
                    try:
                        self.mav.mav.command_ack_send(msg.command, 0)
                    except Exception as e:
                        print(f"ACK send failed: {e}")
                    self._trigger_count += 1
                    print(f"DO_DIGICAM_CONTROL trigger #{self._trigger_count}")
                    if self.on_camera_trigger:
                        threading.Thread(
                            target=self.on_camera_trigger,
                            daemon=True
                        ).start()

                elif msg.command == 206:  # DO_SET_CAM_TRIGG_DIST — interval only
                    try:
                        self.mav.mav.command_ack_send(msg.command, 0)
                    except Exception as e:
                        print(f"ACK send failed: {e}")
                    print(f"DO_SET_CAM_TRIGG_DIST received — "
                          f"Pixhawk will fire CAMERA_FEEDBACK per capture")

    # --------------------------------------------------
    # Public Interface
    # --------------------------------------------------
    def get_gps(self):
        with self.lock:
            data = self.telemetry.copy()
        if data["fix_type"] < 3 or data["lat"] is None:
            return None, None, None
        return data["lat"], data["lon"], data["alt"]

    def get_telemetry(self):
        with self.lock:
            return self.telemetry.copy()

    def get_trigger_count(self):
        return self._trigger_count

    def reset_mission_state(self):
        """Call this before starting a new mission so completion fires again."""
        self._mission_active = False
        self._mission_ended  = False
        print("Mission state reset — ready for new mission")

    def stop(self):
        self.running = False