import pytest

import rebecca as R
import rebecca_update as U


class FakeMouse:
    def __init__(self):
        self.log, self.position = [], (500, 500)

    def press(self, b): self.log.append(("press", b))
    def release(self, b): self.log.append(("release", b))
    def scroll(self, x, y): self.log.append(("scroll", y))

    def move(self, x, y):
        self.log.append(("move", x, y))
        self.position = (self.position[0] + x, self.position[1] + y)


class FakeKeys:
    def __init__(self): self.log = []
    def press(self, k): self.log.append(("press", k))
    def release(self, k): self.log.append(("release", k))


def hand(x, y, pinch=False, fist=False):
    h = object.__new__(R.HandInfo)
    h.x = h.px = x
    h.y = h.py = y
    h.pinch, h.fist, h.src = pinch, fist, "hand"
    return h


class Clock:   # 30 frames per second, deterministic
    t = 0.0

    def __call__(self):
        self.t += 1 / 30
        return self.t


@pytest.fixture
def make_driver(monkeypatch):
    monkeypatch.setattr(R, "MouseController", FakeMouse)
    monkeypatch.setattr(R, "KeyboardController", FakeKeys)

    def make(app, invert=False):
        d = R.CadDriver(R.PROFILES[app], False, 1800, 30, invert)
        d.clock = Clock()
        return d
    return make


def orbit(d, frames=10):
    for i in range(frames):
        d.update([hand(0.3 + 0.01 * i, 0.5, pinch=True)])


@pytest.mark.parametrize("title,app", [
    ("Part Studio 1 | My doc - Onshape - Google Chrome", "onshape"),
    ("Autodesk Fusion - Bracket v12", "fusion360"),
    ("Cool model - Sketchfab", "webviewer"),
    ("SOLIDWORKS Premium", "solidworks"),
    ("Notepad", None), ("REBECCA", None), ("", None),
])
def test_detect_app(title, app):
    assert R.detect_app(title) == app


def test_fusion_orbit_is_shift_plus_middle_drag(make_driver):
    d = make_driver("fusion360")
    orbit(d)
    assert d.mouse.log[0] == ("press", R.Button.middle)
    assert ("press", R.Key.shift) in d.kb.log
    assert any(e[0] == "move" for e in d.mouse.log)


def test_onshape_orbit_is_right_drag_and_pan_adds_ctrl(make_driver):
    d = make_driver("onshape")
    orbit(d)
    assert d.mouse.log[0] == ("press", R.Button.right)
    d.release()
    d.mouse.log.clear(), d.kb.log.clear()
    for _ in range(5):
        d.update([hand(0.3, 0.5, fist=True)])
    assert d.mouse.log[0] == ("press", R.Button.right)
    assert ("press", R.Key.ctrl) in d.kb.log


def test_one_frame_blip_is_ignored(make_driver):
    d = make_driver("fusion360")
    d.update([hand(0.3, 0.5, pinch=True)])
    for _ in range(5):
        d.update([])
    assert not any(e[0] == "press" for e in d.mouse.log)


def test_cursor_returns_and_buttons_release_when_hand_leaves(make_driver):
    d = make_driver("fusion360")
    orbit(d)
    assert d.mouse.position != (500, 500)
    for _ in range(5):
        d.update([])
    assert d.mouse.position == (500, 500)
    assert ("release", R.Button.middle) in d.mouse.log and ("release", R.Key.shift) in d.kb.log


def test_release_all_frees_everything(make_driver):
    d = make_driver("fusion360")
    orbit(d)
    R.release_all()
    assert ("release", R.Button.middle) in d.mouse.log


@pytest.mark.parametrize("invert,sign", [(False, 1), (True, -1)])
def test_two_hand_zoom_scrolls(make_driver, invert, sign):
    d = make_driver("fusion360", invert)
    for i in range(10):
        d.update([hand(0.4 - 0.01 * i, 0.5, pinch=True), hand(0.6 + 0.01 * i, 0.5, pinch=True)])
    scrolls = [e[1] for e in d.mouse.log if e[0] == "scroll"]
    assert scrolls and all(s * sign > 0 for s in scrolls)


def test_two_fists_twist_moves_horizontally(make_driver):
    import math
    d = make_driver("fusion360")
    for i in range(12):
        a = i * 0.1
        d.update([hand(0.3, 0.5, fist=True), hand(0.3 + 0.3 * math.cos(a), 0.5 + 0.3 * math.sin(a), fist=True)])
    assert d.mode == "twist"
    assert any(e[0] == "move" and e[2] == 0 for e in d.mouse.log)


def test_version_compare():
    assert U.is_newer("v0.2.0", "0.1.0") and U.is_newer("v1.0", "0.9.9")
    assert not U.is_newer("v0.1.0", "0.1.0") and not U.is_newer("v0.1.0", "0.2.0")


def test_defaults_keep_camera_window_hidden():
    assert R.DEFAULTS["preview"] is False and R.DEFAULTS["pill"] is True


def test_one_euro_is_steady_when_still_and_follows_fast_moves():
    import random
    random.seed(1)
    f, t, out = R.OneEuro(), 0.0, []
    for _ in range(90):                       # hand held still with sensor jitter
        t += 1 / 30
        out.append(f(0.5 + random.uniform(-0.004, 0.004), t))
    assert max(out[30:]) - min(out[30:]) < 0.004
    for i in range(1, 16):                    # then a quick sweep: output must not lag far behind
        t += 1 / 30
        last = f(0.5 + 0.03 * i, t)
    assert 0.95 - last < 0.12


def test_calibration_thresholds():
    assert R.thresholds_from(0.9, 0.1) == (0.38, 0.58)
    assert R.thresholds_from(0.4, 0.3) is None          # open and pinched look too alike
    on, off = R.thresholds_from(1.5, 0.02)
    assert on <= 0.45 and off >= on + 0.1


def test_admin_check_is_false_off_windows(monkeypatch):
    monkeypatch.setattr(R.sys, "platform", "linux")
    assert R.foreground_is_elevated() is False
