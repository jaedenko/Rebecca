#!/usr/bin/env python3
"""
REBECCA - Really Exciting Borderline Ecstatic CAD Control Articulator   (engine + command line)

For everyday use run the tray app (rebecca_tray.py / Rebecca.exe). This module is the engine
behind it, and also works on its own for debugging.

Gestures (either hand):
  PINCH  (thumb + index)           -> ORBIT   (hold + move hand)
  FIST   (all fingers curled)      -> PAN     (hold + move hand)
  BOTH HANDS PINCHED, spread/close -> ZOOM
  BOTH FISTS, turn like a wheel    -> TWIST   (roll in SolidWorks, otherwise spins the model)
  OPEN HAND / no hand              -> idle    (your "lift the mouse" clutch)

Examples:
  python rebecca.py --list-cameras
  python rebecca.py --setup                              # pick a camera, save, exit
  python rebecca.py --now --dry-run --preview            # try tracking without touching the mouse
  python rebecca.py                                      # wait for Ctrl+Alt+R (camera window hidden)
Settings live in ~/.rebecca.json.
"""
import argparse
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")  # quiet the "camera index not found" spam
os.environ.setdefault("OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS", "0")  # much faster webcam start on Windows

import cv2
import mediapipe as mp
from pynput import keyboard
from pynput.keyboard import Controller as KeyboardController, Key
from pynput.mouse import Button, Controller as MouseController

# ---------------------------------------------------------------------------
# Per-app navigation profiles: (mouse button, [modifier keys]) per action.
# ---------------------------------------------------------------------------
PROFILES = {
    "fusion360":  {"orbit": ("middle", ["shift"]), "pan": ("middle", [])},
    # Onshape defaults: right-drag rotates, Ctrl+right-drag pans (middle-drag pans too, but can re-fit the view)
    "onshape":    {"orbit": ("right", []),         "pan": ("right", ["ctrl"])},
    "solidworks": {"orbit": ("middle", []),        "pan": ("middle", ["ctrl"]), "roll": ("middle", ["alt"])},
    "blender":    {"orbit": ("middle", []),        "pan": ("middle", ["shift"])},
    "freecad":    {"orbit": ("middle", []),        "pan": ("middle", ["ctrl"])},
    # three.js-style web viewers (Sketchfab, Printables, GrabCAD...): left-drag orbit, right-drag pan
    "webviewer":  {"orbit": ("left", []),          "pan": ("right", [])},
    "generic":    {"orbit": ("middle", []),        "pan": ("middle", ["ctrl"])},
}
PROFILE_LABELS = {
    "fusion360": "Fusion 360", "onshape": "Onshape", "solidworks": "SolidWorks", "blender": "Blender",
    "freecad": "FreeCAD", "webviewer": "Web 3D viewers (Sketchfab, Printables...)", "generic": "Generic (middle-drag)",
}
# window-title hints for auto-detection, checked in order
APP_HINTS = [("onshape", "onshape"), ("fusion", "fusion360"), ("solidworks", "solidworks"),
             ("blender", "blender"), ("freecad", "freecad"), ("sketchfab", "webviewer"),
             ("printables", "webviewer"), ("grabcad", "webviewer"), ("thingiverse", "webviewer")]

BUTTONS = {"left": Button.left, "middle": Button.middle, "right": Button.right}
MODS = {"shift": Key.shift, "ctrl": Key.ctrl, "alt": Key.alt}

PINCH_ON, PINCH_OFF = 0.30, 0.50
SWITCH_FRAMES = 3
DEADZONE = 0.0006
CYAN, DIM = (255, 220, 0), (140, 110, 0)  # BGR

CONFIG_PATH = Path.home() / ".rebecca.json"
DEFAULTS = {"camera": 0, "app": "fusion360", "auto_app": True, "hotkey": "<ctrl>+<alt>+r",
            "mode": "toggle", "idle_timeout": 45, "preview": False, "sounds": True, "arm": False}


# ---------------------------------------------------------------------------
# config, cues, active-window detection
# ---------------------------------------------------------------------------
def load_config():
    try:
        return {**DEFAULTS, **json.loads(CONFIG_PATH.read_text())}
    except Exception:
        return dict(DEFAULTS)


def save_config(cfg):
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    except OSError:
        pass


def cue(kind):
    """Short sound so you know the camera went live / off without looking anywhere."""
    def play():
        try:
            if sys.platform == "win32":
                import winsound
                winsound.Beep(988 if kind == "start" else 523, 80)
            elif sys.platform == "darwin":
                snd = "Tink" if kind == "start" else "Pop"
                subprocess.run(["afplay", f"/System/Library/Sounds/{snd}.aiff"], timeout=3)
        except Exception:
            pass
    threading.Thread(target=play, daemon=True).start()


def foreground_title():
    """Title of the window you're looking at ('' if unknown). Used to pick the right mouse mapping."""
    try:
        if sys.platform == "win32":
            import ctypes
            u = ctypes.windll.user32
            hwnd = u.GetForegroundWindow()
            n = u.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(hwnd, buf, n + 1)
            return buf.value
        if sys.platform == "darwin":
            script = ['tell application "System Events"',
                      'set p to first application process whose frontmost is true',
                      'set t to ""', 'try', 'set t to name of front window of p', 'end try',
                      'return (name of p) & " | " & t', 'end tell']
            args = ["osascript"] + [x for line in script for x in ("-e", line)]
            return subprocess.run(args, capture_output=True, text=True, timeout=1.5).stdout.strip()
        return subprocess.run(["xdotool", "getactivewindow", "getwindowname"],
                              capture_output=True, text=True, timeout=1.5).stdout.strip()
    except Exception:
        return ""


def detect_app(title):
    t = (title or "").lower()
    if "rebecca" in t:
        return None
    for needle, name in APP_HINTS:
        if needle in t:
            return name
    return None


# ---------------------------------------------------------------------------
# cameras
# ---------------------------------------------------------------------------
def open_camera(idx):
    cap = cv2.VideoCapture(idx)
    if not cap.isOpened():
        cap.release()
        return None
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 960)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 540)
    return cap


def probe_cameras(limit=8):
    """Return [(index, width, height)] for every camera that actually delivers a frame."""
    found = []
    for i in range(limit):
        cap = cv2.VideoCapture(i)
        ok, frame = cap.read() if cap.isOpened() else (False, None)
        cap.release()
        if ok:
            found.append((i, frame.shape[1], frame.shape[0]))
    return found


def next_camera(cur, limit=8):
    """Open the next working camera after `cur` (wrapping). Caller must release `cur` first."""
    for step in range(1, limit + 1):
        j = (cur + step) % limit
        cap = open_camera(j)
        if cap is not None:
            ok, _ = cap.read()
            if ok:
                return j, cap
            cap.release()
    return None, None


def pick_camera(current=0):
    """Live preview of each camera; N/P to switch, Enter to choose, Esc to cancel."""
    cams = probe_cameras()
    if not cams:
        print("[rebecca] no cameras found. Check permissions / that nothing else is using it.")
        return None
    idxs = [c[0] for c in cams]
    pos = idxs.index(current) if current in idxs else 0
    win, cap, chosen = "REBECCA - choose camera", None, None
    while True:
        if cap is None:
            cap = open_camera(idxs[pos])
        ok, frame = cap.read() if cap else (False, None)
        if ok:
            frame = cv2.flip(frame, 1)
            cv2.putText(frame, f"camera {idxs[pos]}  ({pos + 1}/{len(idxs)})", (16, 32),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, CYAN, 2, cv2.LINE_AA)
            cv2.putText(frame, "N/P = switch    ENTER = use this one    ESC = cancel", (16, frame.shape[0] - 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, CYAN, 1, cv2.LINE_AA)
            cv2.imshow(win, frame)
        key = cv2.waitKey(30) & 0xFF
        if key in (13, 10, 32):
            chosen = idxs[pos]
            break
        if key == 27:
            break
        if key in (ord("n"), ord("p")):
            pos = (pos + (1 if key == ord("n") else -1)) % len(idxs)
            if cap:
                cap.release()
            cap = None
    if cap:
        cap.release()
    cv2.destroyWindow(win)
    cv2.waitKey(1)
    return chosen


# ---------------------------------------------------------------------------
# gesture analysis + mouse driver
# ---------------------------------------------------------------------------
def dist(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


class HandInfo:
    def __init__(self, lm, was_pinching):
        size = dist(lm[0], lm[9]) or 1e-6
        self.pinch_ratio = dist(lm[4], lm[8]) / size
        curled = sum(
            dist(lm[t], lm[0]) < dist(lm[p], lm[0])
            for t, p in ((8, 6), (12, 10), (16, 14), (20, 18))
        )
        self.fist = curled >= 4
        thresh = PINCH_OFF if was_pinching else PINCH_ON
        self.pinch = (not self.fist) and self.pinch_ratio < thresh
        pts = [lm[i] for i in (0, 5, 9, 13, 17)]
        self.x = sum(p.x for p in pts) / 5
        self.y = sum(p.y for p in pts) / 5
        self.px, self.py, self.src = self.x, self.y, "hand"  # motion coords (arm mode overrides)


class CadDriver:
    def __init__(self, profile, dry, sensitivity, zoom_gain, invert_zoom, twist_gain=600):
        self.profile = profile
        self.dry = dry
        self.sens = sensitivity
        self.zoom_gain = zoom_gain * (-1 if invert_zoom else 1)
        self.twist_gain = twist_gain
        self.mouse = MouseController()
        self.kb = KeyboardController()
        self.mode = None
        self.cand, self.cand_n = None, 0
        self.last = None
        self.smooth = None
        self.rem = [0.0, 0.0]
        self.zlast = None
        self.zrem = 0.0
        self.alast = None
        self.src = None
        self.home = None   # cursor position before a drag, restored afterwards
        self.held = None   # (button, mods) currently pressed

    def _press(self, action):
        btn, mods = self.profile.get(action) or self.profile["orbit"]
        if self.dry:
            return
        self.home = self.mouse.position
        for m in mods:
            self.kb.press(MODS[m])
        self.mouse.press(BUTTONS[btn])
        self.held = (btn, mods)

    def release(self):
        if self.held and not self.dry:
            btn, mods = self.held
            self.mouse.release(BUTTONS[btn])
            for m in reversed(mods):
                self.kb.release(MODS[m])
            if self.home:
                self.mouse.position = self.home  # view moved, cursor goes back where it was
        self.held = None

    def _request(self, want):
        if want == self.cand:
            self.cand_n += 1
        else:
            self.cand, self.cand_n = want, 1
        if self.cand_n >= SWITCH_FRAMES and want != self.mode:
            self.release()
            self.mode = want
            self.last = None
            self.smooth = None
            self.rem = [0.0, 0.0]
            self.zlast = None
            self.zrem = 0.0
            self.alast = None
            self.src = None
            if want in ("orbit", "pan", "twist"):
                self._press(want)

    def update(self, hands):
        pinched = [h for h in hands if h.pinch]
        fists = [h for h in hands if h.fist]
        if len(pinched) == 2:
            want, ref = "zoom", None
        elif len(fists) == 2:
            want, ref = "twist", None
        elif pinched:
            want, ref = "orbit", pinched[0]
        elif fists:
            want, ref = "pan", fists[0]
        else:
            want, ref = None, None
        self._request(want)

        if self.mode == "zoom" and want == "zoom":
            d = math.hypot(pinched[0].x - pinched[1].x, pinched[0].y - pinched[1].y)
            if self.zlast is not None:
                self.zrem += (d - self.zlast) * self.zoom_gain
                clicks = int(self.zrem)
                if clicks:
                    self.zrem -= clicks
                    if not self.dry:
                        self.mouse.scroll(0, clicks)
            self.zlast = d
        elif self.mode == "twist" and want == "twist":
            a, b = sorted(fists, key=lambda h: h.x)
            ang = math.atan2(b.y - a.y, b.x - a.x)
            if self.alast is not None:
                d = (ang - self.alast + math.pi) % (2 * math.pi) - math.pi
                self.rem[0] += d * self.twist_gain
                mx = int(self.rem[0])
                if mx:
                    self.rem[0] -= mx
                    if not self.dry:
                        self.mouse.move(mx, 0)
            self.alast = ang
        elif self.mode in ("orbit", "pan") and want == self.mode and ref is not None:
            if ref.src != self.src:  # switched hand<->arm tracking: don't jump
                self.src, self.last, self.smooth = ref.src, None, None
            pos = (ref.px, ref.py)
            if self.smooth is None:
                self.smooth = pos
            else:
                a = 0.5
                self.smooth = (self.smooth[0] + a * (pos[0] - self.smooth[0]),
                               self.smooth[1] + a * (pos[1] - self.smooth[1]))
            if self.last is not None:
                dx = self.smooth[0] - self.last[0]
                dy = self.smooth[1] - self.last[1]
                if abs(dx) < DEADZONE:
                    dx = 0
                if abs(dy) < DEADZONE:
                    dy = 0
                self.rem[0] += dx * self.sens
                self.rem[1] += dy * self.sens
                mx, my = int(self.rem[0]), int(self.rem[1])
                if mx or my:
                    self.rem[0] -= mx
                    self.rem[1] -= my
                    if not self.dry:
                        self.mouse.move(mx, my)
            self.last = self.smooth
        return self.mode


# ---------------------------------------------------------------------------
# models (loaded once, kept warm between sessions so the hotkey feels instant)
# ---------------------------------------------------------------------------
_MODELS = {}


def get_hands():
    if "hands" not in _MODELS:
        _MODELS["hands"] = mp.solutions.hands.Hands(
            static_image_mode=False, max_num_hands=2, model_complexity=1,
            min_detection_confidence=0.6, min_tracking_confidence=0.6)
    return _MODELS["hands"]


def get_pose():
    if "pose" not in _MODELS:
        _MODELS["pose"] = mp.solutions.pose.Pose(
            model_complexity=0, min_detection_confidence=0.5, min_tracking_confidence=0.5)
    return _MODELS["pose"]


def close_models():
    for m in _MODELS.values():
        try:
            m.close()
        except Exception:
            pass
    _MODELS.clear()


# ---------------------------------------------------------------------------
# HUD (only drawn when the preview window is switched on)
# ---------------------------------------------------------------------------
def draw_hud(frame, hands_lm, infos, mode, paused, dry, app, cam_idx):
    h, w = frame.shape[:2]
    for lm in hands_lm:
        for a, b in mp.solutions.hands.HAND_CONNECTIONS:
            p1 = (int(lm.landmark[a].x * w), int(lm.landmark[a].y * h))
            p2 = (int(lm.landmark[b].x * w), int(lm.landmark[b].y * h))
            cv2.line(frame, p1, p2, DIM, 1, cv2.LINE_AA)
        for p in lm.landmark:
            cv2.circle(frame, (int(p.x * w), int(p.y * h)), 2, CYAN, -1, cv2.LINE_AA)
    for i in infos:
        c = (int(i.x * w), int(i.y * h))
        r = 28 if (i.pinch or i.fist) else 18
        cv2.circle(frame, c, r, CYAN, 2, cv2.LINE_AA)
        cv2.circle(frame, c, r + 8, DIM, 1, cv2.LINE_AA)
    pinched = [i for i in infos if i.pinch]
    if len(pinched) == 2:
        cv2.line(frame, (int(pinched[0].x * w), int(pinched[0].y * h)),
                 (int(pinched[1].x * w), int(pinched[1].y * h)), CYAN, 2, cv2.LINE_AA)
    label = "PAUSED" if paused else (mode.upper() if mode else "STANDBY")
    cv2.putText(frame, f"REBECCA // {PROFILE_LABELS.get(app, app).upper()[:24]} // CAM {cam_idx}", (16, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, CYAN, 1, cv2.LINE_AA)
    cv2.putText(frame, f"MODE: {label}" + ("   [DRY RUN]" if dry else ""), (16, 54),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, CYAN, 1, cv2.LINE_AA)
    cv2.putText(frame, "C=camera  A=app  SPACE=pause  Q=end", (16, h - 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, DIM, 1, cv2.LINE_AA)


# ---------------------------------------------------------------------------
# one hotkey-activated session: camera on -> track -> camera off
# ---------------------------------------------------------------------------
def run_session(cfg, args, active, on_status=None):
    """
    Runs until `active` is cleared (hotkey / tray / idle timeout / Q). `cfg` is read live, so the
    tray can change preview, app, sounds... while a session is running.
    on_status(dict) is called with keys among: live, mode, app, error, info.
    """
    def emit(**kw):
        if on_status:
            try:
                on_status(kw)
            except Exception:
                pass

    cap = open_camera(cfg["camera"])
    if cap is None:
        msg = f"Camera {cfg['camera']} won't open. Pick another one from the Rebecca tray menu."
        print("[rebecca]", msg)
        emit(error=msg, live=False)
        active.clear()
        return

    hands_model = get_hands()
    pose_model = None
    driver = CadDriver(PROFILES[cfg["app"]], args.dry_run, args.sensitivity,
                       args.zoom_gain, args.invert_zoom, args.twist_gain)
    effective = cfg["app"]
    if cfg.get("auto_app", True):
        effective = detect_app(foreground_title()) or cfg["app"]
    driver.profile = PROFILES[effective]

    can_preview = sys.platform != "darwin" or threading.current_thread() is threading.main_thread()
    win, win_open = "REBECCA", False
    pinch_state, paused = {}, False
    last_seen = last_detect = time.time()
    last_mode = None
    app_names = sorted(PROFILES)

    print(f"[rebecca] LIVE  camera {cfg['camera']}  profile {effective}")
    if cfg.get("sounds", True):
        cue("start")
    emit(live=True, mode=None, app=effective)
    try:
        while active.is_set():
            ok, frame = cap.read()
            if not ok:
                print("[rebecca] camera stopped delivering frames")
                emit(error="The camera stopped sending video.")
                break
            frame = cv2.flip(frame, 1)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            res = hands_model.process(rgb)

            infos, lms = [], []
            if res.multi_hand_landmarks:
                for lm, hd in zip(res.multi_hand_landmarks, res.multi_handedness):
                    label = hd.classification[0].label
                    info = HandInfo(lm.landmark, pinch_state.get(label, False))
                    pinch_state[label] = info.pinch
                    infos.append(info)
                    lms.append(lm)

            if cfg.get("arm") and infos:
                try:
                    pose_model = pose_model or get_pose()
                except Exception as e:  # pose model needs a one-time download
                    cfg["arm"] = False
                    emit(error="Arm tracking needs a one-time model download and couldn't get it: %s" % e)
                if pose_model:
                    pres = pose_model.process(rgb)
                    if pres.pose_landmarks:
                        P = pres.pose_landmarks.landmark
                        ls, rs = P[11], P[12]
                        sw = math.hypot(ls.x - rs.x, ls.y - rs.y)  # shoulder width = our ruler
                        if sw > 0.05:
                            for info in infos:
                                _, sh = min(((15, ls), (16, rs)), key=lambda t: math.hypot(
                                    P[t[0]].x - info.x, P[t[0]].y - info.y))
                                info.px = (info.x - sh.x) / sw * 0.25
                                info.py = (info.y - sh.y) / sw * 0.25
                                info.src = "arm"

            now = time.time()
            if infos:
                last_seen = now
            elif cfg["mode"] == "toggle" and cfg["idle_timeout"] and now - last_seen > cfg["idle_timeout"]:
                print("[rebecca] no hands for a while - closing session")
                emit(info="No hands for a while, so Rebecca turned the camera off.")
                break

            # follow the window you're looking at (Fusion vs Onshape vs ...), about once a second
            if now - last_detect > 1.0:
                last_detect = now
                wanted = effective
                if cfg.get("auto_app", True):
                    wanted = detect_app(foreground_title()) or effective
                else:
                    wanted = cfg["app"]
                if wanted != effective:
                    driver.release()
                    effective = wanted
                    driver.profile = PROFILES[effective]
                    emit(live=True, mode=last_mode, app=effective)

            if paused:
                driver._request(None)
                mode = driver.mode
            else:
                mode = driver.update(infos)
            if mode != last_mode:
                last_mode = mode
                emit(live=True, mode=mode, app=effective)

            # camera window: hidden by default, can be switched on/off live
            want_win = bool(cfg.get("preview")) and can_preview
            if want_win and not win_open:
                cv2.namedWindow(win, cv2.WINDOW_NORMAL)
                cv2.resizeWindow(win, 480, 270)
                try:
                    cv2.setWindowProperty(win, cv2.WND_PROP_TOPMOST, 1)
                except cv2.error:
                    pass
                win_open = True
            elif win_open and not want_win:
                cv2.destroyWindow(win)
                cv2.waitKey(1)
                win_open = False
            if win_open:
                draw_hud(frame, lms, infos, mode, paused, args.dry_run, effective, cfg["camera"])
                cv2.imshow(win, frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
                if key == ord(" "):
                    paused = not paused
                if key == ord("a"):
                    driver.release()
                    cfg["auto_app"] = False
                    cfg["app"] = effective = app_names[(app_names.index(effective) + 1) % len(app_names)]
                    driver.profile = PROFILES[effective]
                    emit(live=True, mode=last_mode, app=effective)
                    if not args.no_save:
                        save_config(cfg)
                if key == ord("c"):
                    driver.release()
                    cap.release()
                    j, ncap = next_camera(cfg["camera"])
                    cap = ncap or open_camera(cfg["camera"])
                    if ncap:
                        cfg["camera"] = j
                        if not args.no_save:
                            save_config(cfg)
                    if cap is None:
                        break
    finally:
        driver.release()  # never leave a mouse button stuck down
        if cap:
            cap.release()  # camera light off
        if win_open:
            cv2.destroyWindow(win)
            cv2.waitKey(1)
        active.clear()
        if cfg.get("sounds", True):
            cue("stop")
        emit(live=False, mode=None)
        print("[rebecca] session closed, camera released")


# ---------------------------------------------------------------------------
# global hotkey
# ---------------------------------------------------------------------------
_MOD_ORDER = ["ctrl", "alt", "alt_gr", "shift", "cmd"]


def start_hotkey(spec, mode, active):
    """Toggle mode: press to start/stop. Hold mode: live only while the keys are down."""
    if mode == "toggle":
        def toggle():
            if active.is_set():
                active.clear()
            else:
                active.set()
        listener = keyboard.GlobalHotKeys({spec: toggle})
    else:
        keys = set(keyboard.HotKey.parse(spec))
        pressed = set()

        def on_press(k):
            pressed.add(listener.canonical(k))
            if keys <= pressed:
                active.set()

        def on_release(k):
            c = listener.canonical(k)
            pressed.discard(c)
            if c in keys:
                active.clear()
        listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.daemon = True
    listener.start()
    return listener


def _key_spec(k):
    if isinstance(k, keyboard.Key):
        name = k.name
        for suf in ("_l", "_r"):
            if name.endswith(suf):
                name = name[:-len(suf)]
        return f"<{name}>"
    vk = getattr(k, "vk", None)
    if sys.platform == "win32" and vk is not None and 48 <= vk <= 90:
        return chr(vk).lower()   # with Ctrl held, k.char is a control character; the virtual-key code isn't
    ch = getattr(k, "char", None)
    if ch and ch.isprintable():
        return ch.lower()
    return f"<{vk}>" if vk is not None else None


def record_hotkey(timeout=10.0):
    """Listen for the next key combination and return it as a pynput spec like '<ctrl>+<alt>+r'."""
    held, order, result = set(), [], {}
    done = threading.Event()
    mods = {f"<{m}>" for m in _MOD_ORDER}

    def on_press(k):
        s = _key_spec(k)
        if s and s not in held:
            held.add(s)
            if s not in order:
                order.append(s)

    def on_release(k):
        s = _key_spec(k)
        if s in held and any(x not in mods for x in order):
            result["spec"] = "+".join(sorted(
                order, key=lambda x: _MOD_ORDER.index(x[1:-1]) if x in mods else 99))
            done.set()
        held.discard(s)

    with keyboard.Listener(on_press=on_press, on_release=on_release):
        done.wait(timeout)
    spec = result.get("spec")
    if not spec:
        return None
    has_mod = any(m in spec for m in mods)
    is_fn = re.fullmatch(r"<f\d+>", spec) is not None
    if not (has_mod or is_fn):   # a bare letter would fire every time you type it
        return None
    try:
        keyboard.HotKey.parse(spec)
    except ValueError:
        return None
    return spec


# ---------------------------------------------------------------------------
# command line (debugging / power users)
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="REBECCA engine - hotkey-activated hand-gesture CAD inspection.")
    ap.add_argument("--app", choices=sorted(PROFILES), default=None, help="force one mouse mapping (turns off auto-detect)")
    ap.add_argument("--auto-app", action="store_true", help="pick the mapping from the active window (default)")
    ap.add_argument("--camera", type=int, default=None, help="camera index (see --list-cameras)")
    ap.add_argument("--list-cameras", action="store_true", help="show which cameras work, then exit")
    ap.add_argument("--pick-camera", action="store_true", help="choose a camera from live previews")
    ap.add_argument("--setup", action="store_true", help="pick a camera, save settings, then exit")
    ap.add_argument("--hotkey", default=None, help='pynput syntax, e.g. "<ctrl>+<alt>+r" or "<f8>"')
    ap.add_argument("--mode", choices=["toggle", "hold"], default=None)
    ap.add_argument("--idle-timeout", type=float, default=None,
                    help="toggle mode: end the session after N seconds without hands (0 = never)")
    ap.add_argument("--now", action="store_true", help="start a session immediately (no hotkey press)")
    ap.add_argument("--sensitivity", type=float, default=1800,
                    help="mouse pixels per full camera-frame width of hand travel")
    ap.add_argument("--zoom-gain", type=float, default=30)
    ap.add_argument("--invert-zoom", action="store_true")
    ap.add_argument("--twist-gain", type=float, default=600,
                    help="mouse pixels per radian of two-fist twist (negative reverses)")
    ap.add_argument("--arm", action="store_true", help="track relative to your shoulder (needs a pose model download)")
    ap.add_argument("--preview", dest="preview", action="store_true", default=None, help="show the camera window")
    ap.add_argument("--no-preview", dest="preview", action="store_false", help="hide the camera window (default)")
    ap.add_argument("--dry-run", action="store_true", help="track, never touch the mouse")
    ap.add_argument("--no-save", action="store_true", help="don't write ~/.rebecca.json")
    args = ap.parse_args()

    if args.list_cameras:
        cams = probe_cameras()
        for i, w, h in cams:
            print(f"camera {i}: {w}x{h}")
        if not cams:
            print("no working cameras found")
        return

    first_run = not CONFIG_PATH.exists()
    cfg = load_config()
    for k in ("camera", "hotkey", "mode", "idle_timeout", "preview"):
        v = getattr(args, k)
        if v is not None:
            cfg[k] = v
    if args.app is not None:
        cfg["app"], cfg["auto_app"] = args.app, False
    if args.auto_app:
        cfg["auto_app"] = True
    if args.arm:
        cfg["arm"] = True

    if args.pick_camera or args.setup or (first_run and args.camera is None):
        chosen = pick_camera(cfg["camera"])
        if chosen is not None:
            cfg["camera"] = chosen
    if not args.no_save:
        save_config(cfg)
    if args.setup:
        print(f"[rebecca] setup saved: camera {cfg['camera']}, hotkey {cfg['hotkey']}")
        return

    active = threading.Event()
    if args.now:
        active.set()
    start_hotkey(cfg["hotkey"], cfg["mode"], active)
    how = "press it again to stop" if cfg["mode"] == "toggle" else "hold it while you gesture"
    print(f"[rebecca] waiting. Hotkey {cfg['hotkey']} -> camera {cfg['camera']} ({how}). Ctrl+C here to quit.")
    try:
        while True:
            if active.is_set():
                run_session(cfg, args, active)
            else:
                time.sleep(0.05)
    except KeyboardInterrupt:
        print("\n[rebecca] bye")
    finally:
        close_models()


if __name__ == "__main__":
    main()
