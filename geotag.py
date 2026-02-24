import piexif
import math
import json
import datetime
from PIL import Image


def decimal_to_dms(decimal):
    """Convert decimal degrees to (deg, min, sec) tuples for EXIF."""
    degrees = int(decimal)
    minutes_float = (decimal - degrees) * 60
    minutes = int(minutes_float)
    seconds = int((minutes_float - minutes) * 60 * 100)
    return ((degrees, 1), (minutes, 1), (seconds, 100))


def rad_to_deg(radians):
    if radians is None:
        return None
    return math.degrees(radians)


def embed_gps(image_path, telemetry, frame_data=None):
    """
    Embed full surveillance + mapping telemetry into image EXIF.

    Standard GPS EXIF:
        GPSLatitude/Ref, GPSLongitude/Ref
        GPSAltitude/Ref
        GPSImgDirection/Ref  ← uses ACTUAL camera pan from MOUNT_STATUS
                            falls back to aircraft yaw if unavailable
        GPSSatellites, GPSMeasureMode
        GPSDateStamp, GPSTimeStamp
        GPSSpeed, GPSSpeedRef

    UserComment JSON (non-standard fields):
        Aircraft: pitch, roll, yaw (degrees)
        Camera mount: camera_pan, camera_tilt, camera_roll (degrees)
        Flight: relative_alt, vx, vy, vz
        GPS: fix_type, satellites
        Frame: frame_id, timestamp, simulation_mode
    """
    img = Image.open(image_path)

    exif_bytes = img.info.get("exif")
    if exif_bytes:
        exif_dict = piexif.load(exif_bytes)
    else:
        exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

    lat      = telemetry.get("lat")
    lon      = telemetry.get("lon")
    alt      = telemetry.get("alt", 0) or 0
    fix_type = telemetry.get("fix_type", 0)
    sats     = telemetry.get("satellites", 0)
    vx       = telemetry.get("vx", 0) or 0
    vy       = telemetry.get("vy", 0) or 0

    # Camera mount angles (from MOUNT_STATUS via Telem 2)
    camera_pan  = telemetry.get("camera_pan")
    camera_tilt = telemetry.get("camera_tilt")
    camera_roll = telemetry.get("camera_roll")

    # Aircraft attitude (radians → degrees)
    yaw_rad   = telemetry.get("yaw")
    yaw_deg   = rad_to_deg(yaw_rad)
    pitch_deg = rad_to_deg(telemetry.get("pitch"))
    roll_deg  = rad_to_deg(telemetry.get("roll"))

    now_utc = datetime.datetime.now(datetime.timezone.utc)

    # Ground speed m/s → km/h
    ground_speed_kmh = math.sqrt(vx**2 + vy**2) * 3.6

    gps_ifd = {
        piexif.GPSIFD.GPSLatitudeRef:  b'N' if lat >= 0 else b'S',
        piexif.GPSIFD.GPSLatitude:     decimal_to_dms(abs(lat)),
        piexif.GPSIFD.GPSLongitudeRef: b'E' if lon >= 0 else b'W',
        piexif.GPSIFD.GPSLongitude:    decimal_to_dms(abs(lon)),
        piexif.GPSIFD.GPSAltitudeRef:  b'\x00' if alt >= 0 else b'\x01',
        piexif.GPSIFD.GPSAltitude:     (int(abs(alt) * 100), 100),
        piexif.GPSIFD.GPSTimeStamp:    (
            (now_utc.hour,   1),
            (now_utc.minute, 1),
            (now_utc.second, 1)
        ),
        piexif.GPSIFD.GPSDateStamp:    now_utc.strftime("%Y:%m:%d").encode(),
        piexif.GPSIFD.GPSSatellites:   str(sats).encode(),
        piexif.GPSIFD.GPSMeasureMode:  b'3' if fix_type >= 3 else b'2',
        piexif.GPSIFD.GPSSpeedRef:     b'K',
        piexif.GPSIFD.GPSSpeed:        (int(ground_speed_kmh * 100), 100),
    }

    # GPSImgDirection — prefer actual camera pan from MOUNT_STATUS
    # Fall back to aircraft yaw if mount data not yet available
    if camera_pan is not None:
        img_direction = camera_pan % 360
        source = "camera_mount"
    elif yaw_deg is not None:
        img_direction = yaw_deg % 360
        source = "aircraft_yaw_fallback"
    else:
        img_direction = None
        source = "unavailable"

    if img_direction is not None:
        gps_ifd[piexif.GPSIFD.GPSImgDirectionRef] = b'T'
        gps_ifd[piexif.GPSIFD.GPSImgDirection] = (int(img_direction * 100), 100)

    exif_dict["GPS"] = gps_ifd

    # --- UserComment: full telemetry snapshot as JSON ---
    user_comment_data = {
        # Aircraft attitude
        "aircraft_yaw_deg":   round(yaw_deg % 360,   4) if yaw_deg   is not None else None,
        "aircraft_pitch_deg": round(pitch_deg,        4) if pitch_deg is not None else None,
        "aircraft_roll_deg":  round(roll_deg,         4) if roll_deg  is not None else None,
        # Camera mount — actual pointing from Telem 2 MOUNT_STATUS
        "camera_pan_deg":     round(camera_pan,  4) if camera_pan  is not None else None,
        "camera_tilt_deg":    round(camera_tilt, 4) if camera_tilt is not None else None,
        "camera_roll_deg":    round(camera_roll, 4) if camera_roll is not None else None,
        "img_direction_source": source,
        # Flight data
        "relative_alt_m": telemetry.get("relative_alt"),
        "vx_ms":          telemetry.get("vx"),
        "vy_ms":          telemetry.get("vy"),
        "vz_ms":          telemetry.get("vz"),
        # GPS quality
        "fix_type":   fix_type,
        "satellites": sats,
        "gps_boot_ms": telemetry.get("gps_timestamp"),
    }

    if frame_data:
        user_comment_data["frame_id"]            = frame_data.get("frame_id")
        user_comment_data["frame_timestamp_utc"] = frame_data.get("timestamp_utc")
        user_comment_data["simulation_mode"]     = frame_data.get("simulation_mode")

    comment_json = json.dumps(user_comment_data)
    # UserComment EXIF requires 8-byte charset prefix
    exif_dict["Exif"][piexif.ExifIFD.UserComment] = (
        b"ASCII\x00\x00\x00" + comment_json.encode("ascii")
    )

    exif_bytes = piexif.dump(exif_dict)
    img.save(image_path, "jpeg", exif=exif_bytes)