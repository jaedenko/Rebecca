#!/usr/bin/env python3
"""
REBECCA - Really Exciting Borderline Ecstatic CAD Control Articulator

Hands-free inspection of a finished CAD model, or a link someone sent you.
Hotkey-activated: the camera is OFF until you press the hotkey, and OFF again after.

Gestures (either hand):
  PINCH  (thumb + index)           -> ORBIT   (hold + move hand)
  FIST   (all fingers curled)      -> PAN     (hold + move hand)
  BOTH HANDS PINCHED, spread/close -> ZOOM
  BOTH FISTS, turn like a wheel    -> TWIST   (roll in SolidWorks, otherwise spins the model)
  OPEN HAND / no hand              -> idle    (your "lift the mouse" clutch)

Hotkey:
  toggle (default):  press <ctrl>+<alt>+r to start a session, press again to stop.
                     A session also ends by itself after --idle-timeout seconds with no hands.
  hold:              --mode hold --hotkey "<f8>"  -> live only while the key is held.
                     (Use a key that isn't a modifier your app profile also presses.)

In the preview window:  C = next camera   A = next app profile   SPACE = pause   Q = end session

Examples:
  python rebecca.py --list-cameras
  python rebecca.py --pick-camera
  python rebecca.py --app onshape --dry-run --now     # preview only, starts immediately
  python rebecca.py --app webviewer                    # Sketchfab / Printables / three.js viewers
Settings (camera, app, hotkey, mode) are remembered in ~/.rebecca.json  (--no-save to skip).
"""
import argparse
import json
import math
import os
import sys
import threading
import time
from pathlib import Path

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")  # quiet the "camera index not found" spam

import cv2
import mediapipe as mp
from pynput import keyboard
from pynput.keyboard import Controller as KeyboardController, Key
from pynput.mouse import Button, Controller as MouseController

# ---------------------------------------------------------------------------
# Per-app navigation profiles: (mouse button, [modifier keys]) per action.
# Defaults of each app's own mouse navigation. Edit freely, or press A in the preview.
# ---------------------------------------------------------------------------
PROFILES = {
    "fusion360":  {"orbit": ("middle", ["shift"]), "pan": ("middle", [])},
    "onshape":    {"orbit": ("right", []),         "pan": ("right", ["ctrl"])},
    "solidworks": {"orbit": ("middle", []),        "pan": ("middle", ["ctrl"]), "roll": ("middle", ["alt"])},
    "blender":    {"orbit": ("middle", []),        "pan": ("middle", ["shift"])},
    "freecad":    {"orbit": ("middle", []),        "pan": ("middle", ["ctrl"])},
    # three.js-style web viewers (Sketchfab, Printables, GrabCAD previews...): left-drag orbit, right-drag pan
    "webviewer":  {"orbit": ("left", []),          "pan": ("right", [])},
    "generic":    {"orbit": ("middle", []),        "pan": ("middle", ["ctrl"])},
}

BUTTONS = {"left": Button.left, "middle": Button.middle, "right": Button.right}
MODS = {"shift": Key.shift, "ctrl": Key.ctrl, "alt": Key.alt}

PINCH_ON, PINCH_OFF = 0.30, 0.50
SWITCH_FRAMES = 3
DEADZONE = 0.0006
CYAN, DIM = (255, 220, 0), (140, 110, 0)  # BGR

CONFIG_PATH = Path.home() / ".rebecca.json"
DEFAULTS = {"camera": 0, "app": "fusion360", "hotkey": "<ctrl>+<alt>+r",
            "mode": "toggle", "idle_timeout": 45}


# ---------------------------------------------------------------------------
# config + cameras
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
# HUD
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
    cv2.putText(frame, f"REBECCA // {app.upper()} // CAM {cam_idx}", (16, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, CYAN, 1, cv2.LINE_AA)
    cv2.putText(frame, f"MODE: {label}" + ("   [DRY RUN]" if dry else ""), (16, 54),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, CYAN, 1, cv2.LINE_AA)
    cv2.putText(frame, "C=camera  A=app  SPACE=pause  Q=end", (16, h - 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, DIM, 1, cv2.LINE_AA)


# ---------------------------------------------------------------------------
# one hotkey-activated session: camera on -> track -> camera off
# ---------------------------------------------------------------------------
def run_session(cfg, args, active):
    cap = open_camera(cfg["camera"])
    if cap is None:
        print(f"[rebecca] camera {cfg['camera']} won't open. Try: python rebecca.py --pick-camera")
        active.clear()
        return
    driver = CadDriver(PROFILES[cfg["app"]], args.dry_run, args.sensitivity,
                       args.zoom_gain, args.invert_zoom, args.twist_gain)
    hands_model = mp.solutions.hands.Hands(
        static_image_mode=False, max_num_hands=2, model_complexity=1,
        min_detection_confidence=0.6, min_tracking_confidence=0.6)
    pose_model = mp.solutions.pose.Pose(
        model_complexity=0, min_detection_confidence=0.5,
        min_tracking_confidence=0.5) if args.arm else None
    win = "REBECCA"
    if not args.no_preview:
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(win, 480, 270)
        try:
            cv2.setWindowProperty(win, cv2.WND_PROP_TOPMOST, 1)
        except cv2.error:
            pass
    pinch_state, paused, last_seen = {}, False, time.time()
    app_names = sorted(PROFILES)
    print(f"[rebecca] LIVE  camera {cfg['camera']}  profile {cfg['app']}")
    try:
        while active.is_set():
            ok, frame = cap.read()
            if not ok:
                print("[rebecca] camera stopped delivering frames")
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

            if pose_model and infos:
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
            elif args.mode == "toggle" and cfg["idle_timeout"] and now - last_seen > cfg["idle_timeout"]:
                print("[rebecca] no hands for a while - closing session")
                break

            if paused:
                driver._request(None)
                mode = driver.mode
            else:
                mode = driver.update(infos)

            if not args.no_preview:
                draw_hud(frame, lms, infos, mode, paused, args.dry_run, cfg["app"], cfg["camera"])
                cv2.imshow(win, frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
                if key == ord(" "):
                    paused = not paused
                if key == ord("a"):
                    driver.release()
                    cfg["app"] = app_names[(app_names.index(cfg["app"]) + 1) % len(app_names)]
                    driver.profile = PROFILES[cfg["app"]]
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
        hands_model.close()
        if pose_model:
            pose_model.close()
        if not args.no_preview:
            cv2.destroyWindow(win)
            cv2.waitKey(1)
        active.clear()
        print("[rebecca] session closed, camera released")


# ---------------------------------------------------------------------------
# global hotkey
# ---------------------------------------------------------------------------
def start_hotkey(spec, mode, active):
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


def main():
    ap = argparse.ArgumentParser(
        description="REBECCA - hotkey-activated hand-gesture inspection of CAD models.")
    ap.add_argument("--app", choices=sorted(PROFILES), default=None)
    ap.add_argument("--camera", type=int, default=None, help="camera index (see --list-cameras)")
    ap.add_argument("--list-cameras", action="store_true", help="show which cameras work, then exit")
    ap.add_argument("--pick-camera", action="store_true", help="choose a camera from live previews")
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
    ap.add_argument("--arm", action="store_true",
                    help="track relative to your shoulder (cancels body sway; heavier on CPU)")
    ap.add_argument("--no-preview", action="store_true", help="no camera window (hotkey ends the session)")
    ap.add_argument("--dry-run", action="store_true", help="track and preview, never touch the mouse")
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
    for k in ("app", "camera", "hotkey", "mode", "idle_timeout"):
        v = getattr(args, k)
        if v is not None:
            cfg[k] = v
    args.mode = cfg["mode"]

    if args.pick_camera or (first_run and args.camera is None):
        chosen = pick_camera(cfg["camera"])
        if chosen is not None:
            cfg["camera"] = chosen
    if not args.no_save:
        save_config(cfg)

    active = threading.Event()
    if args.now:
        active.set()
    start_hotkey(cfg["hotkey"], cfg["mode"], active)
    how = "press it again to stop" if cfg["mode"] == "toggle" else "hold it while you gesture"
    print(f"[rebecca] waiting. Hotkey {cfg['hotkey']} -> camera {cfg['camera']}, "
          f"profile {cfg['app']} ({how}). Ctrl+C here to quit.")
    try:
        while True:
            if active.is_set():
                run_session(cfg, args, active)
            else:
                time.sleep(0.05)
    except KeyboardInterrupt:
        print("\n[rebecca] bye")


if __name__ == "__main__":
    main()
