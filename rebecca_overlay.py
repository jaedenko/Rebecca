"""
On-screen status pill: a tiny always-on-top badge ("ORBIT - Onshape") so you can see Rebecca is live
while the camera window is hidden. Click-through and never takes focus, so it can't get in your way.
All Tk calls happen on one dedicated thread; everyone else just posts messages to a queue.
"""
import queue
import sys
import threading
import time


class Overlay:
    KEY = "#010203"   # this colour is made transparent on Windows, which gives the pill its rounded shape

    def __init__(self):
        self.q = queue.Queue()
        self.thread = None

    # ---- thread-safe API ----------------------------------------------------
    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, name="overlay", daemon=True)
            self.thread.start()

    def show(self, text, color="#00dcff"):
        self.q.put(("show", text, color))

    def hide(self, after=0.0):
        self.q.put(("hide", after))

    def stop(self):
        self.q.put(("stop",))

    # ---- the Tk thread ------------------------------------------------------
    def _run(self):
        if sys.platform == "darwin":
            return  # the menu-bar icon owns the main thread there; the tray icon + sounds cover it
        win = sys.platform == "win32"
        try:
            if win:
                import ctypes
                try:   # crisp text on high-DPI screens, for this thread's windows only (mouse maths untouched)
                    ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
                except Exception:
                    pass
            import tkinter as tk
            from tkinter import font as tkfont
            root = tk.Tk()
        except Exception as e:
            print("[overlay] disabled:", e)
            return

        root.withdraw()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        try:
            root.attributes("-alpha", 0.95)
            if win:
                root.attributes("-transparentcolor", self.KEY)
        except tk.TclError:
            pass
        root.configure(bg=self.KEY)
        scale = max(1.0, root.winfo_fpixels("1i") / 96.0)
        font = tkfont.Font(family="Segoe UI" if win else "DejaVu Sans", size=-int(15 * scale), weight="bold")
        h = int(40 * scale)
        canvas = tk.Canvas(root, height=h, bg=self.KEY, highlightthickness=0, bd=0)
        canvas.pack()
        state = {"visible": False, "hide_at": None, "styled": False}

        def make_click_through():
            if not win or state["styled"]:
                return
            try:
                import ctypes
                u = ctypes.windll.user32
                hwnd = u.GetParent(root.winfo_id()) or root.winfo_id()
                ex = u.GetWindowLongW(hwnd, -20)
                # layered | transparent (click-through) | toolwindow (no taskbar) | noactivate (never steals focus)
                u.SetWindowLongW(hwnd, -20, ex | 0x80000 | 0x20 | 0x80 | 0x08000000)
                state["styled"] = True
            except Exception:
                pass

        def pill(x0, y0, x1, y1, **kw):
            r = (y1 - y0) / 2
            canvas.create_oval(x0, y0, x0 + 2 * r, y1, width=0, **kw)
            canvas.create_oval(x1 - 2 * r, y0, x1, y1, width=0, **kw)
            canvas.create_rectangle(x0 + r, y0, x1 - r, y1, width=0, **kw)

        def draw(text, color):
            w = font.measure(text) + int(62 * scale)
            canvas.config(width=w)
            canvas.delete("all")
            b = max(1, int(1.5 * scale))
            pill(0, 0, w, h, fill=color)                      # coloured rim
            pill(b, b, w - b, h - b, fill="#07151e")          # dark body
            d = int(6 * scale)
            cy = h // 2
            canvas.create_oval(int(20 * scale) - d, cy - d, int(20 * scale) + d, cy + d, fill=color, width=0)
            canvas.create_text(int(36 * scale), cy, text=text, anchor="w", fill="#d8faff", font=font)
            x = (root.winfo_screenwidth() - w) // 2
            root.geometry(f"{w}x{h}+{x}+{int(18 * scale)}")

        def pump():
            try:
                while True:
                    cmd = self.q.get_nowait()
                    if cmd[0] == "show":
                        draw(cmd[1], cmd[2])
                        state["hide_at"] = None
                        if not state["visible"]:
                            root.deiconify()
                            state["visible"] = True
                        root.attributes("-topmost", True)
                        root.update_idletasks()
                        make_click_through()
                    elif cmd[0] == "hide":
                        state["hide_at"] = time.time() + cmd[1]
                    elif cmd[0] == "stop":
                        root.destroy()
                        return
            except queue.Empty:
                pass
            if state["hide_at"] is not None and time.time() >= state["hide_at"]:
                root.withdraw()
                state["visible"], state["hide_at"] = False, None
            root.after(40, pump)

        root.after(40, pump)
        try:
            root.mainloop()
        finally:
            # Tk objects must die on the thread that made them, or Python aborts at exit
            # ("Tcl_AsyncDelete: async handler deleted by the wrong thread").
            import gc
            state.clear()
            canvas = font = None
            try:
                root.destroy()
            except Exception:
                pass
            root = None
            gc.collect()
