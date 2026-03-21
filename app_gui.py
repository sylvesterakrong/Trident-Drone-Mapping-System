import tkinter as tk
from tkinter import scrolledtext
import threading
import datetime
import math
import time
import os
import sys
import cv2

# Local modules — at top level so PyInstaller traces and bundles them.
# Do NOT move these back inside functions.
from mavlink_reader import MAVLinkReader
from camera_capture import CameraCapture
from geotag import embed_gps
from tcp_listener import TCPListener
from config import SAVE_DIR, MAVLINK_CONNECTION, TCP_HOST, TCP_PORT, CAMERA_MODE


def resource_path(relative_path):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(__file__), relative_path)


def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)


# ===================================================
# SPLASH SCREEN
# Shown on startup while system components initialise.
# Fades out automatically when ready.
# ===================================================
class SplashScreen:
    def __init__(self, root):
        self.root = root
        self.splash = tk.Toplevel(root)

        BG = "#161622"
        CARD = "#1A1A21"
        BLUE = "#8be9fd"
        GREEN = "#50fa7b"
        MUTED = "#6272a4"
        FG = "#f8f8f2"

        # Borderless, always on top, centred
        self.splash.overrideredirect(True)
        self.splash.attributes("-topmost", True)
        self.splash.configure(bg=CARD)

        W, H = 460, 300
        sw = self.splash.winfo_screenwidth()
        sh = self.splash.winfo_screenheight()
        x = (sw - W) // 2
        y = (sh - H) // 2
        self.splash.geometry(f"{W}x{H}+{x}+{y}")

        # Subtle border via outer frame
        border = tk.Frame(self.splash, bg="#44475a", padx=2, pady=2)
        border.pack(fill="both", expand=True)

        inner = tk.Frame(border, bg=CARD)
        inner.pack(fill="both", expand=True)

        # Icon placeholder — drone emoji as fallback
        tk.Label(inner, text="🔱", font=("Segoe UI", 36), bg=CARD, fg=BLUE).pack(
            pady=(30, 4)
        )

        tk.Label(
            inner,
            text="Trident Aerial System 🔱",
            font=("Segoe UI", 18, "bold"),
            bg=CARD,
            fg=BLUE,
        ).pack()

        tk.Label(
            inner,
            text="Aerial Intelligence & geotagging",
            font=("Segoe UI", 10),
            bg=CARD,
            fg=MUTED,
        ).pack(pady=(2, 20))

        # Progress bar track
        bar_track = tk.Frame(inner, bg="#13131f", height=4, width=360)
        bar_track.pack()
        bar_track.pack_propagate(False)

        self._bar = tk.Frame(bar_track, bg=GREEN, height=4, width=0)
        self._bar.place(x=0, y=0, relheight=1)

        # Status label
        self._status_var = tk.StringVar(value="Starting...")
        tk.Label(
            inner,
            textvariable=self._status_var,
            font=("Segoe UI", 9),
            bg=CARD,
            fg=MUTED,
        ).pack(pady=(8, 0))

        # Version / credit line
        tk.Label(
            inner,
            text="v1.1  ·  Powered by MAVLink & OpenCV",
            font=("Segoe UI", 8),
            bg=CARD,
            fg="#44475a",
        ).pack(side="bottom", pady=12)

        # Hide main window while splash is showing
        self.root.withdraw()
        self.splash.update()

        self._progress = 0  # 0–100
        self._target = 0

        # Smooth progress animation loop
        self._animate()

    def _animate(self):
        """Smoothly inch progress bar toward current target."""
        if self._progress < self._target:
            self._progress = min(self._progress + 2, self._target)
            bar_width = int(3.6 * self._progress)
            self._bar.place(x=0, y=0, relheight=1, width=bar_width)
            self.splash.after(16, self._animate)  # ~60fps

    def set_status(self, text, progress):
        """Update status label and progress target (0–100)."""
        self._status_var.set(text)
        self._target = progress
        if self._progress < self._target:
            self._animate()
        self.splash.update_idletasks()

    def close(self):
        """Fade out splash and show main window."""
        self._fade(alpha=1.0)

    def _fade(self, alpha):
        try:
            self.splash.attributes("-alpha", alpha)
            if alpha > 0:
                self.splash.after(20, lambda: self._fade(round(alpha - 0.05, 2)))
            else:
                self.splash.destroy()
                self.root.deiconify()  # show main window
                self.root.lift()
        except Exception:
            # Splash already destroyed
            try:
                self.root.deiconify()
            except Exception:
                pass


class MappingApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Trident Aerial System 🔱")
        self.root.geometry("720x900")
        self.root.minsize(540, 500)
        self.root.resizable(True, True)
        self.root.configure(bg="#1e1e2e")

        # Set window icon (title bar + taskbar)
        try:
            icon_path = resource_path("icon.ico")
            self.root.iconbitmap(icon_path)
        except Exception:
            pass  # silently skip if icon file not found

        self.mav_reader = None
        self.cam = None
        self.tcp_listener = None
        self.running = False
        self.capture_count = 0

        # Show splash while system initialises
        self.splash = SplashScreen(self.root)

        self._build_scrollable_shell()
        self._build_ui()
        self._start_system()

    # ===================================================
    # SCROLLABLE SHELL
    # Wraps all content in a Canvas so the full app
    # scrolls when the window is smaller than the content
    # ===================================================
    def _build_scrollable_shell(self):
        BG = "#1e1e2e"

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")

        scrollbar = tk.Scrollbar(
            self.root, orient="vertical", command=self.canvas.yview
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        # Inner frame — all UI widgets go here instead of self.root
        self.inner = tk.Frame(self.canvas, bg=BG)
        self._canvas_window = self.canvas.create_window(
            (0, 0), window=self.inner, anchor="nw"
        )

        # Update scroll region when inner content changes size
        self.inner.bind("<Configure>", self._on_inner_configure)

        # Stretch inner frame width when window is resized
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Mouse wheel — Windows, Linux, Mac
        self.canvas.bind_all(
            "<MouseWheel>",
            lambda e: self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"),
        )
        self.canvas.bind_all(
            "<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units")
        )
        self.canvas.bind_all(
            "<Button-5>", lambda e: self.canvas.yview_scroll(1, "units")
        )

    def _on_inner_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self._canvas_window, width=event.width)

    # ===================================================
    # UI BUILD
    # ===================================================
    def _build_ui(self):
        BG = "#161622"
        CARD = "#030302"
        GREEN = "#50fa7b"
        FG = "#f8f8f2"
        MUTED = "#6272a4"
        BLUE = "#8be9fd"
        FONT = ("Segoe UI", 10)
        FONT_BOLD = ("Segoe UI", 10, "bold")
        PAD = 12

        # All widgets go inside self.inner (the scrollable frame)
        W = self.inner
        W.columnconfigure(0, weight=1)

        # --------------------------------------------------
        # ROW 0 — Title
        # --------------------------------------------------
        title_frame = tk.Frame(W, bg=BG)
        title_frame.grid(row=0, column=0, sticky="ew", pady=(16, 4))
        title_frame.columnconfigure(0, weight=1)
        tk.Label(
            title_frame,
            text="Trident Aerial System 🔱",
            font=("Segoe UI", 16, "bold"),
            bg=BG,
            fg="#f2e82a",
        ).pack()
        tk.Label(
            title_frame,
            text="Automated Aerial Intelligence",
            font=FONT,
            bg=BG,
            fg=MUTED,
        ).pack(pady=(2, 0))

        # --------------------------------------------------
        # ROW 1 — Status cards
        # --------------------------------------------------
        status_frame = tk.Frame(W, bg=BG)
        status_frame.grid(row=1, column=0, sticky="ew", padx=PAD, pady=(6, 4))
        for i in range(5):
            status_frame.columnconfigure(i, weight=1)

        def make_card(parent, col, label):
            card = tk.Frame(
                parent,
                bg=CARD,
                padx=10,
                pady=10,
                highlightthickness=1,
                highlightbackground="#44475a",
            )
            card.grid(row=0, column=col, sticky="ew", padx=3)
            tk.Label(card, text=label, font=("Segoe UI", 8), bg=CARD, fg=MUTED).pack()
            var = tk.StringVar(value="—")
            lbl = tk.Label(card, textvariable=var, font=FONT_BOLD, bg=CARD, fg=FG)
            lbl.pack()
            return var, lbl

        self.var_mavlink, self.lbl_mavlink = make_card(status_frame, 0, "MAVLink")
        self.var_camera, self.lbl_camera = make_card(status_frame, 1, "Camera")
        self.var_gps, self.lbl_gps = make_card(status_frame, 2, "GPS Fix")
        self.var_sats, self.lbl_sats = make_card(status_frame, 3, "Satellites")
        self.var_nadir, self.lbl_nadir = make_card(status_frame, 4, "Nadir Lock")

        # --------------------------------------------------
        # ROW 2/3 — Aircraft telemetry
        # --------------------------------------------------
        tk.Label(
            W, text="AIRCRAFT TELEMETRY", font=("Segoe UI", 8), bg=BG, fg=MUTED
        ).grid(row=2, column=0, sticky="w", padx=PAD + 4, pady=(6, 1))

        telem_outer = tk.Frame(
            W,
            bg=CARD,
            padx=14,
            pady=10,
            highlightthickness=1,
            highlightbackground="#44475a",
        )
        telem_outer.grid(row=3, column=0, sticky="ew", padx=PAD, pady=(0, 2))

        telem_grid = tk.Frame(telem_outer, bg=CARD)
        telem_grid.pack(fill="x")

        def telem_row(parent, row, col_offset, label):
            tk.Label(
                parent, text=label, font=FONT, bg=CARD, fg=MUTED, width=16, anchor="w"
            ).grid(row=row, column=col_offset, sticky="w", pady=2, padx=(0, 6))
            var = tk.StringVar(value="—")
            tk.Label(
                parent,
                textvariable=var,
                font=FONT_BOLD,
                bg=CARD,
                fg=FG,
                anchor="w",
                width=16,
            ).grid(row=row, column=col_offset + 1, sticky="w")
            return var

        self.var_lat = telem_row(telem_grid, 0, 0, "Latitude")
        self.var_lon = telem_row(telem_grid, 1, 0, "Longitude")
        self.var_alt = telem_row(telem_grid, 2, 0, "Altitude MSL")
        self.var_rel_alt = telem_row(telem_grid, 3, 0, "Relative Alt")
        self.var_yaw = telem_row(telem_grid, 0, 2, "Yaw")
        self.var_pitch = telem_row(telem_grid, 1, 2, "Pitch")
        self.var_roll = telem_row(telem_grid, 2, 2, "Roll")
        self.var_speed = telem_row(telem_grid, 3, 2, "Ground Speed")

        # --------------------------------------------------
        # ROW 4/5 — Camera mount
        # --------------------------------------------------
        tk.Label(
            W,
            text="CAMERA MOUNT  (Telem 2 / MOUNT_STATUS)",
            font=("Segoe UI", 8),
            bg=BG,
            fg=MUTED,
        ).grid(row=4, column=0, sticky="w", padx=PAD + 4, pady=(6, 1))

        mount_outer = tk.Frame(
            W,
            bg=CARD,
            padx=14,
            pady=10,
            highlightthickness=1,
            highlightbackground="#44475a",
        )
        mount_outer.grid(row=5, column=0, sticky="ew", padx=PAD, pady=(0, 2))

        mount_grid = tk.Frame(mount_outer, bg=CARD)
        mount_grid.pack(fill="x")

        def mount_row(parent, row, col_offset, label):
            tk.Label(
                parent, text=label, font=FONT, bg=CARD, fg=MUTED, width=16, anchor="w"
            ).grid(row=row, column=col_offset, sticky="w", pady=2, padx=(0, 6))
            var = tk.StringVar(value="—")
            lbl = tk.Label(
                parent,
                textvariable=var,
                font=FONT_BOLD,
                bg=CARD,
                fg=FG,
                anchor="w",
                width=16,
            )
            lbl.grid(row=row, column=col_offset + 1, sticky="w")
            return var, lbl

        self.var_cam_pan, self.lbl_cam_pan = mount_row(mount_grid, 0, 0, "Pan (°)")
        self.var_cam_tilt, self.lbl_cam_tilt = mount_row(mount_grid, 0, 2, "Tilt (°)")
        self.var_cam_roll, self.lbl_cam_roll = mount_row(mount_grid, 1, 0, "Roll (°)")
        self.var_img_dir, self.lbl_img_dir = mount_row(
            mount_grid, 1, 2, "Img Direction"
        )

        # --------------------------------------------------
        # ROW 6 — Image counter
        # --------------------------------------------------
        count_frame = tk.Frame(
            W,
            bg=CARD,
            padx=14,
            pady=12,
            highlightthickness=1,
            highlightbackground="#44475a",
        )
        count_frame.grid(row=6, column=0, sticky="ew", padx=PAD, pady=(6, 2))

        count_inner = tk.Frame(count_frame, bg=CARD)
        count_inner.pack()
        self.var_count = tk.StringVar(value="0")
        tk.Label(
            count_inner,
            textvariable=self.var_count,
            font=("Segoe UI", 44, "bold"),
            bg=CARD,
            fg=GREEN,
        ).pack(side="left")
        tk.Label(
            count_inner, text=" images captured", font=("Segoe UI", 13), bg=CARD, fg=FG
        ).pack(side="left", anchor="s", pady=12)

        # --------------------------------------------------
        # ROW 6b — Mission complete banner (hidden until fired)
        # --------------------------------------------------
        self.mission_banner = tk.Frame(
            W,
            bg="#1a3a1a",
            padx=14,
            pady=12,
            highlightthickness=2,
            highlightbackground="#50fa7b",
        )
        # Not gridded yet — shown only on mission complete

        self.var_banner = tk.StringVar(value="")
        tk.Label(
            self.mission_banner,
            textvariable=self.var_banner,
            font=("Segoe UI", 13, "bold"),
            bg="#1a3a1a",
            fg="#50fa7b",
            justify="center",
        ).pack()

        tk.Button(
            self.mission_banner,
            text="Reset for New Mission",
            font=("Segoe UI", 9),
            bg="#2a2a3e",
            fg="#f8f8f2",
            activebackground="#44475a",
            relief="flat",
            cursor="hand2",
            padx=12,
            pady=6,
            command=self._reset_mission,
        ).pack(pady=(8, 0))

        # --------------------------------------------------
        # ROW 7 — Manual capture button
        # --------------------------------------------------
        btn_frame = tk.Frame(W, bg=BG)
        btn_frame.grid(row=7, column=0, sticky="ew", pady=(6, 2))
        btn_frame.columnconfigure(0, weight=1)

        self.btn_capture = tk.Button(
            btn_frame,
            text="⚡  Manual Capture",
            font=("Segoe UI", 12, "bold"),
            bg="#6272a4",
            fg="white",
            activebackground="#7a8abf",
            activeforeground="white",
            relief="flat",
            cursor="hand2",
            padx=24,
            pady=10,
            command=self._manual_capture,
        )
        self.btn_capture.pack()
        tk.Label(
            btn_frame,
            text="Manual capture is for testing only.  "
            "In a live mission the Pixhawk triggers automatically.",
            font=("Segoe UI", 8),
            bg=BG,
            fg=MUTED,
        ).pack(pady=(3, 0))

        # --------------------------------------------------
        # ROW 8 — System log
        # Fixed tall height so it always shows plenty of output.
        # The outer canvas scrollbar lets you reach it by scrolling.
        # --------------------------------------------------
        log_frame = tk.Frame(W, bg=BG)
        log_frame.grid(row=8, column=0, sticky="ew", padx=PAD, pady=(8, 4))
        log_frame.columnconfigure(0, weight=1)

        tk.Label(
            log_frame, text="SYSTEM LOG", font=("Segoe UI", 8), bg=BG, fg=MUTED
        ).grid(row=0, column=0, sticky="w")

        self.log_box = scrolledtext.ScrolledText(
            log_frame,
            height=18,  # fixed tall height — always visible
            font=("Courier New", 9),
            bg="#13131f",
            fg=FG,
            relief="flat",
            state="disabled",
            wrap="word",
        )
        self.log_box.grid(row=1, column=0, sticky="ew")

        # --------------------------------------------------
        # ROW 9 — Status bar
        # --------------------------------------------------
        self.var_status = tk.StringVar(value="Initialising...")
        tk.Label(
            W,
            textvariable=self.var_status,
            font=("Segoe UI", 8),
            bg="#13131f",
            fg=MUTED,
            anchor="w",
            padx=8,
        ).grid(row=9, column=0, sticky="ew", pady=(4, 8))

    # ===================================================
    # LOGGING
    # ===================================================
    def _log(self, message, level="INFO"):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        colours = {
            "INFO": "#f8f8f2",
            "OK": "#50fa7b",
            "WARN": "#f1fa8c",
            "ERROR": "#ff5555",
        }
        colour = colours.get(level, "#f8f8f2")
        self.log_box.configure(state="normal")
        self.log_box.tag_configure(level, foreground=colour)
        self.log_box.insert("end", f"[{ts}] {message}\n", level)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    # ===================================================
    # SYSTEM STARTUP
    # ===================================================
    def _start_system(self):
        threading.Thread(target=self._init_system, daemon=True).start()

    def _init_system(self):
        ensure_dir(SAVE_DIR)
        ensure_dir("logs")

        def sp(text, pct):
            """Update splash from background thread safely."""
            self.root.after(0, lambda: self.splash.set_status(text, pct))

        # --- Camera ---
        sp("Initialising camera...", 10)
        self._update_status("Initialising camera...")
        self._log("Starting camera...", "INFO")
        try:
            # CameraCapture already imported at top
            self.cam = CameraCapture()
            self._log("Camera ready", "OK")
            sp("Camera connected ✓", 35)
            self.root.after(
                0,
                lambda: self._set_card(
                    self.var_camera, self.lbl_camera, "Connected", "#50fa7b"
                ),
            )
        except Exception as e:
            self._log(f"Camera error: {e}", "ERROR")
            sp("Camera error — continuing...", 35)
            self.root.after(
                0,
                lambda: self._set_card(
                    self.var_camera, self.lbl_camera, "Error", "#ff5555"
                ),
            )

        # --- MAVLink ---
        sp(f"Connecting to MAVLink {MAVLINK_CONNECTION} ...", 45)
        self._update_status(f"Connecting to MAVLink  {MAVLINK_CONNECTION} ...")
        self._log("Connecting to MAVLink...", "INFO")
        try:
            # MAVLinkReader already imported at top

            def on_mavlink_trigger():
                count = self.mav_reader.get_trigger_count()
                self._log(f"Pixhawk trigger #{count} received", "OK")
                self._do_capture(source=f"MAVLINK_{count}")

            def on_mission_complete():
                total = self.mav_reader.get_trigger_count()
                self._log(
                    f"✓ Mission complete — {total} images captured. "
                    f"Stopping mapping mission.",
                    "OK",
                )
                self.root.after(0, lambda: self._show_mission_complete(total))

            self.mav_reader = MAVLinkReader(
                connection_string=MAVLINK_CONNECTION,
                on_camera_trigger=on_mavlink_trigger,
                on_mission_complete=on_mission_complete,
            )
            self._log("MAVLink connected", "OK")
            if CAMERA_MODE == "nadir":
                self._log("Nadir lock command sent via Telem 2", "OK")
                sp("MAVLink connected ✓  Nadir lock sent", 75)
                self.root.after(
                    0,
                    lambda: self._set_card(
                        self.var_nadir, self.lbl_nadir, "Sent", "#f1fa8c"
                    ),
                )
            else:
                self._log("Camera mode: FREE — no nadir lock", "INFO")
                sp("MAVLink connected ✓  Camera free", 75)
                self.root.after(
                    0,
                    lambda: self._set_card(
                        self.var_nadir, self.lbl_nadir, "Free ✓", "#50fa7b"
                    ),
                )
            self.root.after(
                0,
                lambda: self._set_card(
                    self.var_mavlink, self.lbl_mavlink, "Connected", "#50fa7b"
                ),
            )
        except Exception as e:
            self._log(f"MAVLink error: {e}", "ERROR")
            sp("MAVLink error — continuing...", 75)
            self.root.after(
                0,
                lambda: self._set_card(
                    self.var_mavlink, self.lbl_mavlink, "Error", "#ff5555"
                ),
            )
            self.root.after(
                0,
                lambda: self._set_card(
                    self.var_nadir, self.lbl_nadir, "N/A", "#ff5555"
                ),
            )

        # --- TCP listener ---
        sp("Starting TCP listener...", 88)
        try:
            # TCPListener already imported at top

            def on_tcp():
                self._log("Manual TCP trigger received", "INFO")
                self._do_capture(source="TCP_MANUAL")

            self.tcp_listener = TCPListener(
                host=TCP_HOST, port=TCP_PORT, callback=on_tcp
            )
            self.tcp_listener.start()
            self._log("TCP listener active on port 5555", "INFO")
        except Exception as e:
            self._log(f"TCP listener error: {e}", "WARN")

        self.running = True
        sp("System ready ✓", 100)
        import time as _time

        _time.sleep(0.6)  # brief pause at 100% so user sees it complete
        self.root.after(0, self.splash.close)
        self._update_status("System ready — waiting for mission triggers")
        self._log("System ready. Waiting for Pixhawk triggers.", "OK")
        threading.Thread(target=self._telemetry_loop, daemon=True).start()

    # ===================================================
    # TELEMETRY LOOP
    # ===================================================
    def _telemetry_loop(self):
        while self.running:
            if self.mav_reader:
                t = self.mav_reader.get_telemetry()

                def update(t=t):
                    # GPS fix card
                    fix = t["fix_type"]
                    if fix >= 3:
                        self._set_card(
                            self.var_gps, self.lbl_gps, f"3D ({fix})", "#50fa7b"
                        )
                    elif fix == 2:
                        self._set_card(self.var_gps, self.lbl_gps, "2D Fix", "#f1fa8c")
                    else:
                        self._set_card(self.var_gps, self.lbl_gps, "No Fix", "#ff5555")

                    # Satellites card
                    sats = t["satellites"]
                    sc = (
                        "#50fa7b"
                        if sats >= 8
                        else "#f1fa8c" if sats >= 6 else "#ff5555"
                    )
                    self._set_card(self.var_sats, self.lbl_sats, str(sats), sc)

                    # Aircraft telemetry
                    self.var_lat.set(
                        f"{t['lat']:.6f}°" if t["lat"] is not None else "—"
                    )
                    self.var_lon.set(
                        f"{t['lon']:.6f}°" if t["lon"] is not None else "—"
                    )
                    self.var_alt.set(
                        f"{t['alt']:.1f} m" if t["alt"] is not None else "—"
                    )
                    self.var_rel_alt.set(
                        f"{t['relative_alt']:.1f} m"
                        if t["relative_alt"] is not None
                        else "—"
                    )

                    def fmt_rad(rad):
                        return f"{math.degrees(rad):.1f}°" if rad is not None else "—"

                    self.var_yaw.set(fmt_rad(t.get("yaw")))
                    self.var_pitch.set(fmt_rad(t.get("pitch")))
                    self.var_roll.set(fmt_rad(t.get("roll")))

                    vx = t.get("vx", 0) or 0
                    vy = t.get("vy", 0) or 0
                    self.var_speed.set(f"{math.sqrt(vx**2 + vy**2):.1f} m/s")

                    # Camera mount angles
                    cam_pan = t.get("camera_pan")
                    cam_tilt = t.get("camera_tilt")
                    cam_roll = t.get("camera_roll")

                    if cam_pan is not None:
                        self.var_cam_pan.set(f"{cam_pan:.1f}°")
                        self.var_cam_tilt.set(
                            f"{cam_tilt:.1f}°" if cam_tilt is not None else "—"
                        )
                        self.var_cam_roll.set(
                            f"{cam_roll:.1f}°" if cam_roll is not None else "—"
                        )
                        self.var_img_dir.set(f"{cam_pan % 360:.1f}° (mount)")
                        self.lbl_img_dir.configure(fg="#50fa7b")

                        # Nadir confirmation
                        if cam_tilt is not None and abs(cam_tilt + 90) < 5:
                            self._set_card(
                                self.var_nadir, self.lbl_nadir, "Confirmed ✓", "#50fa7b"
                            )
                        else:
                            self._set_card(
                                self.var_nadir,
                                self.lbl_nadir,
                                f"{cam_tilt:.0f}°" if cam_tilt else "—",
                                "#f1fa8c",
                            )
                    else:
                        self.var_cam_pan.set("—")
                        self.var_cam_tilt.set("—")
                        self.var_cam_roll.set("—")
                        yaw_r = t.get("yaw")
                        if yaw_r is not None:
                            self.var_img_dir.set(
                                f"{math.degrees(yaw_r) % 360:.1f}° (yaw fallback)"
                            )
                            self.lbl_img_dir.configure(fg="#f1fa8c")
                        else:
                            self.var_img_dir.set("—")

                self.root.after(0, update)
            time.sleep(0.5)

    # ===================================================
    # CAPTURE
    # ===================================================
    def _do_capture(self, source="MANUAL"):
        try:
            # embed_gps already imported at top

            frame_data = self.cam.get_frame() if self.cam else None
            if frame_data is None:
                self._log("Capture failed: no frame available", "ERROR")
                return

            telemetry = self.mav_reader.get_telemetry() if self.mav_reader else {}
            if (
                not telemetry
                or telemetry.get("fix_type", 0) < 3
                or telemetry.get("lat") is None
            ):
                self._log(
                    f"Capture skipped: no GPS fix "
                    f"(fix_type={telemetry.get('fix_type', 0)}, "
                    f"sats={telemetry.get('satellites', 0)})",
                    "WARN",
                )
                return

            ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
            file_path = os.path.join(SAVE_DIR, f"image_{ts}.jpg")
            cv2.imwrite(file_path, frame_data["image"])
            embed_gps(file_path, telemetry, frame_data)

            self.capture_count += 1

            cam_pan = telemetry.get("camera_pan")
            if cam_pan is not None:
                dir_str = f"CamPan: {cam_pan % 360:.1f}°"
            elif telemetry.get("yaw") is not None:
                dir_str = (
                    f"Yaw fallback: " f"{math.degrees(telemetry['yaw']) % 360:.1f}°"
                )
            else:
                dir_str = "Dir: N/A"

            self._log(
                f"[{source}] {os.path.basename(file_path)} | "
                f"({telemetry['lat']:.5f}, {telemetry['lon']:.5f}, "
                f"{telemetry['alt']:.1f}m) | {dir_str}",
                "OK",
            )

            self.root.after(0, lambda: self.var_count.set(str(self.capture_count)))

        except Exception as e:
            self._log(f"Capture error: {e}", "ERROR")

    def _manual_capture(self):
        self._log("Manual capture triggered by operator", "INFO")
        threading.Thread(
            target=self._do_capture, kwargs={"source": "MANUAL_BUTTON"}, daemon=True
        ).start()

    # ===================================================
    # MISSION COMPLETE
    # ===================================================
    def _show_mission_complete(self, total_images):
        self.var_banner.set(
            f"✓  Mapping Mission Complete\n"
            f"{total_images} geotagged images saved to '{SAVE_DIR}/'\n"
            f"Hand the captures folder to your processing software."
        )
        self.mission_banner.grid(
            row=6, column=0, sticky="ew", padx=12, pady=(4, 2), in_=self.inner
        )
        self._update_status(
            f"Mission complete — {total_images} images captured. "
            f"Stopping mapping mission."
        )

    def _reset_mission(self):
        """Hide the banner and reset for a new mission."""
        self.mission_banner.grid_remove()
        self.capture_count = 0
        self.var_count.set("0")
        if self.mav_reader:
            self.mav_reader.reset_mission_state()
        self._log("Mission state reset — ready for new mission", "INFO")
        self._update_status("System ready — waiting for mission triggers")

    # ===================================================
    # HELPERS
    # ===================================================
    def _set_card(self, var, lbl, text, colour):
        var.set(text)
        lbl.configure(fg=colour)

    def _update_status(self, msg):
        self.root.after(0, lambda: self.var_status.set(msg))


if __name__ == "__main__":
    root = tk.Tk()
    app = MappingApp(root)
    root.mainloop()
