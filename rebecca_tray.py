#!/usr/bin/env python3
"""
Rebecca - system-tray app. Runs quietly in the background; the camera stays OFF until you press
the hotkey (default Ctrl+Alt+R) over your CAD viewport. Everything is in the tray icon's menu.
"""
import argparse
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

if getattr(sys, "frozen", False):
    # a windowed exe has no console: send prints (ours and the libraries') to a small log file instead
    try:
        _log = Path.home() / ".rebecca.log"
        if _log.exists() and _log.stat().st_size > 1_000_000:
            _log.unlink()
        sys.stdout = sys.stderr = open(_log, "a", buffering=1, encoding="utf-8")
    except Exception:
        pass

import pystray

import rebecca as R
from rebecca_icon import make_icon

PORT = 47831  # single-instance lock


def pretty_hotkey(spec):
    return " + ".join(p.strip("<>").replace("_", " ").title() if p.startswith("<") else p.upper()
                      for p in spec.split("+"))


# ----- start at login --------------------------------------------------------
def _launch_command():
    if getattr(sys, "frozen", False):
        return [sys.executable]
    exe = sys.executable
    if sys.platform == "win32" and exe.lower().endswith("python.exe"):
        exe = exe[:-len("python.exe")] + "pythonw.exe"   # no console window
    return [exe, os.path.abspath(__file__)]


def _plist_path():
    return Path.home() / "Library" / "LaunchAgents" / "com.rebecca.app.plist"


def autostart_enabled():
    try:
        if sys.platform == "win32":
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
                winreg.QueryValueEx(k, "Rebecca")
            return True
        if sys.platform == "darwin":
            return _plist_path().exists()
    except OSError:
        pass
    return False


def set_autostart(on):
    cmd = _launch_command()
    if sys.platform == "win32":
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run",
                            0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, "Rebecca", 0, winreg.REG_SZ, " ".join(f'"{c}"' for c in cmd))
            else:
                try:
                    winreg.DeleteValue(k, "Rebecca")
                except FileNotFoundError:
                    pass
    elif sys.platform == "darwin":
        p = _plist_path()
        if on:
            args = "".join(f"<string>{c}</string>" for c in cmd)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>'
                         '<key>Label</key><string>com.rebecca.app</string>'
                         f'<key>ProgramArguments</key><array>{args}</array>'
                         '<key>RunAtLoad</key><true/></dict></plist>')
        elif p.exists():
            p.unlink()


def single_instance():
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", PORT))
        s.listen(1)
        return s
    except OSError:
        return None


class TrayApp:
    def __init__(self, headless=False):
        self.cfg = R.load_config()
        self.first_run = not R.CONFIG_PATH.exists()
        self.active = threading.Event()
        self.state = {"live": False, "mode": None, "app": None}
        self.cameras = []
        self.hk = None
        self.quitting = False
        self.args = argparse.Namespace(dry_run=False, sensitivity=1800, zoom_gain=30,
                                       invert_zoom=False, twist_gain=600, no_save=False)
        self.icon = None if headless else pystray.Icon("Rebecca", make_icon(), "Rebecca", self.build_menu())

    # ----- helpers -----------------------------------------------------------
    def save(self):
        R.save_config(self.cfg)

    def notify(self, msg):
        print("[tray]", msg)
        try:
            self.icon.notify(msg, "Rebecca")
        except Exception:
            pass

    def status_text(self):
        if self.state["live"]:
            mode = (self.state["mode"] or "ready").upper()
            app = R.PROFILE_LABELS.get(self.state["app"], "")
            return f"LIVE  -  {mode}  -  {app}".rstrip(" -")
        return f"Idle  -  press {pretty_hotkey(self.cfg['hotkey'])} to start"

    def refresh(self):
        if not self.icon:
            return
        try:
            self.icon.icon = make_icon(self.state["live"], self.state["mode"])
            self.icon.title = "Rebecca: " + self.status_text()
            self.icon.update_menu()
        except Exception:
            pass

    def on_status(self, d):
        if d.get("error"):
            self.notify(d["error"])
        if d.get("info"):
            self.notify(d["info"])
        for k in ("live", "mode", "app"):
            if k in d:
                self.state[k] = d[k]
        self.refresh()

    # ----- session worker + hotkey ------------------------------------------
    def worker(self):
        while not self.quitting:
            if self.active.is_set():
                try:
                    R.run_session(self.cfg, self.args, self.active, on_status=self.on_status)
                except Exception as e:
                    print("[tray] session crashed:", repr(e))
                    self.active.clear()
                    self.on_status({"live": False, "mode": None, "error": f"Rebecca hit an error: {e}"})
            else:
                time.sleep(0.05)

    def start_hotkey(self):
        self.stop_hotkey()
        try:
            self.hk = R.start_hotkey(self.cfg["hotkey"], self.cfg["mode"], self.active)
        except Exception as e:
            self.hk = None
            self.notify(f"That hotkey isn't usable ({e}). Pick another from the tray menu.")

    def stop_hotkey(self):
        if self.hk:
            try:
                self.hk.stop()
            except Exception:
                pass
            self.hk = None

    def toggle(self):
        if self.active.is_set():
            self.active.clear()
        else:
            self.active.set()

    # ----- menu actions ------------------------------------------------------
    def flip(self, key):
        self.cfg[key] = not self.cfg[key]
        self.save()
        self.refresh()

    def flip_autostart(self):
        try:
            set_autostart(not autostart_enabled())
        except Exception as e:
            self.notify(f"Couldn't change start-at-login: {e}")
        self.refresh()

    def set_mode(self, mode):
        self.cfg["mode"] = mode
        self.save()
        self.start_hotkey()
        self.refresh()

    def set_auto(self):
        self.cfg["auto_app"] = True
        self.save()
        self.refresh()

    def set_app(self, name):
        self.cfg["app"], self.cfg["auto_app"] = name, False
        self.save()
        self.refresh()

    def set_camera(self, idx):
        self.cfg["camera"] = idx
        self.save()
        self.refresh()
        if self.active.is_set():
            self.notify("Camera changed. It takes effect the next time you start Rebecca.")

    def scan_cameras(self):
        if self.active.is_set():
            return self.notify("Stop Rebecca first, then scan for cameras.")

        def work():
            self.notify("Scanning for cameras...")
            self.cameras = R.probe_cameras()
            self.notify(f"Found {len(self.cameras)} camera(s). Pick one under Camera.")
            self.refresh()
        threading.Thread(target=work, daemon=True).start()

    def pick_visually(self):
        if self.active.is_set():
            return self.notify("Stop Rebecca first, then choose a camera.")

        def work():
            idx = R.pick_camera(self.cfg["camera"])
            if idx is not None:
                self.set_camera(idx)
        threading.Thread(target=work, daemon=True).start()

    def change_hotkey(self):
        def work():
            self.notify("Press the new hotkey now (hold a modifier like Ctrl or Alt, tap a key, release).")
            self.stop_hotkey()
            spec = R.record_hotkey(timeout=12)
            if spec:
                self.cfg["hotkey"] = spec
                self.save()
                self.notify(f"Hotkey is now {pretty_hotkey(spec)}.")
            else:
                self.notify(f"No usable hotkey captured (use Ctrl/Alt/Shift plus a key). Keeping "
                            f"{pretty_hotkey(self.cfg['hotkey'])}.")
            self.start_hotkey()
            self.refresh()
        threading.Thread(target=work, daemon=True).start()

    def quit(self):
        self.quitting = True
        self.active.clear()
        self.stop_hotkey()
        time.sleep(0.2)
        R.close_models()
        if self.icon:
            self.icon.stop()

    # ----- menu ---------------------------------------------------------------
    def camera_items(self):
        I = pystray.MenuItem
        cams = self.cameras or [(self.cfg["camera"], 0, 0)]
        for idx, w, h in cams:
            label = f"Camera {idx}" + (f"   ({w}x{h})" if w else "")
            yield I(label, self._cam_action(idx), checked=self._cam_checked(idx), radio=True)
        yield pystray.Menu.SEPARATOR
        yield I("Scan for cameras", lambda icon, item: self.scan_cameras())
        yield I("Identify visually...", lambda icon, item: self.pick_visually())

    def _cam_action(self, idx):
        return lambda icon, item: self.set_camera(idx)

    def _cam_checked(self, idx):
        return lambda item: self.cfg["camera"] == idx

    def app_items(self):
        I = pystray.MenuItem
        yield I("Auto-detect from the active window (recommended)", lambda icon, item: self.set_auto(),
                checked=lambda item: bool(self.cfg["auto_app"]), radio=True)
        yield pystray.Menu.SEPARATOR
        for name in sorted(R.PROFILES):
            yield I(R.PROFILE_LABELS[name], self._app_action(name), checked=self._app_checked(name), radio=True)

    def _app_action(self, name):
        return lambda icon, item: self.set_app(name)

    def _app_checked(self, name):
        return lambda item: (not self.cfg["auto_app"]) and self.cfg["app"] == name

    def build_menu(self):
        I, M = pystray.MenuItem, pystray.Menu
        return M(
            I(lambda item: self.status_text(), None, enabled=False),
            I("Start / stop now", lambda icon, item: self.toggle(), default=True),
            M.SEPARATOR,
            I("Camera", M(self.camera_items)),
            I("App to control", M(self.app_items)),
            I("Show camera preview", lambda icon, item: self.flip("preview"),
              checked=lambda item: bool(self.cfg["preview"])),
            I("Sound cues", lambda icon, item: self.flip("sounds"),
              checked=lambda item: bool(self.cfg["sounds"])),
            I("Arm-relative tracking (experimental)", lambda icon, item: self.flip("arm"),
              checked=lambda item: bool(self.cfg["arm"])),
            M.SEPARATOR,
            I(lambda item: f"Hotkey: {pretty_hotkey(self.cfg['hotkey'])}", M(
                I("Change hotkey...", lambda icon, item: self.change_hotkey()),
                M.SEPARATOR,
                I("Press to start, press again to stop", lambda icon, item: self.set_mode("toggle"),
                  checked=lambda item: self.cfg["mode"] == "toggle", radio=True),
                I("Hold to use, release to stop", lambda icon, item: self.set_mode("hold"),
                  checked=lambda item: self.cfg["mode"] == "hold", radio=True))),
            I("Start at login", lambda icon, item: self.flip_autostart(),
              checked=lambda item: autostart_enabled()),
            M.SEPARATOR,
            I("Quit Rebecca", lambda icon, item: self.quit()),
        )

    # ----- run ----------------------------------------------------------------
    def _setup(self, icon):
        icon.visible = True
        threading.Thread(target=self.worker, daemon=True).start()
        self.start_hotkey()
        if self.first_run:
            self.save()
            self.notify(f"Rebecca is running in your tray. Put your cursor over a CAD viewport and press "
                        f"{pretty_hotkey(self.cfg['hotkey'])}. Right-click the icon for settings.")

    def run(self):
        self.icon.run(setup=self._setup)


def selftest():
    """Used by the build pipeline: proves the packaged app contains everything it needs (no camera required)."""
    import numpy as np
    import mediapipe as mp
    lines, ok = [], True

    def check(name, fn):
        nonlocal ok
        try:
            lines.append(f"ok    {name}: {fn()}")
        except Exception as e:
            ok = False
            lines.append(f"FAIL  {name}: {e!r}")

    app = TrayApp(headless=True)
    check("icons", lambda: [make_icon(live, m).size for live in (False, True) for m in (None, "orbit")])
    check("menus", lambda: (len(list(app.camera_items())), len(list(app.app_items()))))
    check("pystray menu", lambda: type(app.build_menu()).__name__)
    check("hands model", lambda: R.get_hands().process(np.zeros((480, 640, 3), np.uint8)) is not None)
    pose = Path(mp.__file__).parent / "modules" / "pose_landmark" / "pose_landmark_lite.tflite"
    check("pose model bundled", lambda: pose.exists() or (_ for _ in ()).throw(FileNotFoundError(str(pose))))
    check("mouse/keyboard control", lambda: (R.MouseController(), R.KeyboardController()) and "ok")
    check("hotkey parse", lambda: R.keyboard.HotKey.parse("<ctrl>+<alt>+r"))
    check("active window", lambda: repr(R.foreground_title())[:40])
    out = "\n".join(lines)
    try:
        (Path(tempfile.gettempdir()) / "rebecca-selftest.log").write_text(out)
    except OSError:
        pass
    print(out)
    sys.exit(0 if ok else 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.selftest:
        selftest()
    lock = single_instance()
    if lock is None:
        msg = "Rebecca is already running. Look for its ring icon in the system tray (the ^ near the clock)."
        print(msg)
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, msg, "Rebecca", 0x40)
        return
    TrayApp().run()


if __name__ == "__main__":
    main()
