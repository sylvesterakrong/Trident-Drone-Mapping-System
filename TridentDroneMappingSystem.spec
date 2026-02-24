# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['app_gui.py'],
    pathex=[],
    binaries=[],
    datas=[('icon.ico', '.'), ('config.py', '.'), ('mavlink_reader.py', '.'), ('camera_capture.py', '.'), ('geotag.py', '.'), ('tcp_listener.py', '.')],
    hiddenimports=['pymavlink', 'pymavlink.dialects.v20.ardupilotmega', 'cv2', 'piexif', 'PIL', 'PIL.Image', 'requests', 'numpy', 'mavlink_reader', 'camera_capture', 'geotag', 'tcp_listener', 'config'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='TridentDroneMappingSystem',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
)
