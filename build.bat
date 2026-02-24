@echo off
echo ============================================
echo  Building Trident Drone Mapping System Executable
echo ============================================

pip install pyinstaller --quiet

pyinstaller ^
    --onefile ^
    --windowed ^
    --name "TridentDroneMappingSystem" ^
    --icon "icon.ico" ^
    --add-data "icon.ico;." ^
    --add-data "config.py;." ^
    --add-data "mavlink_reader.py;." ^
    --add-data "camera_capture.py;." ^
    --add-data "geotag.py;." ^
    --add-data "tcp_listener.py;." ^
    --hidden-import pymavlink ^
    --hidden-import pymavlink.dialects.v20.ardupilotmega ^
    --hidden-import cv2 ^
    --hidden-import piexif ^
    --hidden-import PIL ^
    --hidden-import PIL.Image ^
    --hidden-import requests ^
    --hidden-import numpy ^
    --hidden-import mavlink_reader ^
    --hidden-import camera_capture ^
    --hidden-import geotag ^
    --hidden-import tcp_listener ^
    --hidden-import config ^
    app_gui.py

echo.
echo ============================================
echo  Build complete. Executable: dist\TridentDroneMappingSystem.exe
echo.
echo  Place these files alongside the exe if
echo  you want settings to be editable without
echo  rebuilding:
echo    - config.py
echo  The captures\ folder will be created
echo  automatically on first run.
echo ============================================
pause