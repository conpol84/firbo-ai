#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Derived from conpol84/javris-clone frontend/public/firbo-desktop.py.
# Modified 2026-10-26: bounded DPMS wake and blank-capture guard.
"""One owner-authorized X11 action. JSON stdin/stdout; no listening socket.

Run as the logged-in desktop user. Desktop control is NOT a folder sandbox.
Screenshots are returned to the caller, never written to a public directory.
"""
import base64
import io
import json
import os
import re
import signal
import subprocess
import sys
import time


def xdo(*args, text=None):
    return subprocess.run(["xdotool", *map(str, args)], input=text, text=True,
                          capture_output=True, check=True, timeout=25).stdout.strip()


def display_power():
    try:
        out = subprocess.run(["xset", "q"], capture_output=True, text=True,
                             check=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        raise ValueError("desktop_display_power_unavailable") from None
    match = re.search(r"Monitor is (On|Off|Standby|Suspend)", out)
    return match.group(1) if match else None  # Xvfb may not implement DPMS.


def wake_display():
    """Wake only this unlocked X11 session. Never change lock/idle policies."""
    if display_power() not in ("Off", "Standby", "Suspend"):
        return
    try:
        def query(*args):
            return subprocess.run(["loginctl", *args], capture_output=True,
                                  text=True, check=True, timeout=3).stdout.strip()
        session = query("show-user", str(os.getuid()), "-p", "Display", "--value")
        if not re.fullmatch(r"[A-Za-z0-9]{1,20}", session):
            raise ValueError("desktop_session_unverified")
        values = dict(line.split("=", 1) for line in query(
            "show-session", session, "-p", "LockedHint", "-p", "Display", "-p", "Type"
        ).splitlines() if "=" in line)
        if values.get("LockedHint") == "yes":
            raise ValueError("desktop_session_locked")
        target = os.environ.get("DISPLAY", "")
        if (values.get("LockedHint") != "no" or values.get("Type") != "x11"
                or not re.fullmatch(r":\d+(?:\.\d+)?", target)
                or values.get("Display") != target.split(".")[0]):
            raise ValueError("desktop_session_unverified")
        subprocess.run(["xset", "dpms", "force", "on"], capture_output=True,
                       check=True, timeout=3)
        time.sleep(0.2)
        if display_power() != "On":
            raise ValueError("desktop_display_wake_failed")
    except (OSError, subprocess.SubprocessError):
        raise ValueError("desktop_display_wake_failed") from None


def capture():
    from PIL import ImageGrab
    wake_display()
    image = ImageGrab.grab(xdisplay=os.environ["DISPLAY"]).convert("RGB")
    if max(channel[1] for channel in image.getextrema()) < 8:
        raise ValueError("desktop_capture_black")
    original = image.size
    image.thumbnail((1280, 960))
    for quality in (75, 60, 45, 30):
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=quality)
        if out.tell() <= 90000:
            return {"width": image.width, "height": image.height,
                    "screen_width": original[0], "screen_height": original[1],
                    "image": base64.b64encode(out.getvalue()).decode("ascii")}
    raise ValueError("desktop_capture_too_large")


def physical_stop():
    pointer = xdo("getmouselocation", "--shell")
    if "X=0\nY=0\n" in pointer:
        raise ValueError("desktop_local_stop")


def perform(action):
    if sys.platform != "linux" or not os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        raise ValueError("desktop_x11_required")
    if os.geteuid() == 0:
        raise ValueError("desktop_user_required")
    kind = action.get("action")
    if kind == "observe":
        return capture()
    # The top-left corner is a local physical stop, independent of the server.
    physical_stop()
    if kind in ("click", "move", "drag"):
        width, height = map(int, xdo("getdisplaygeometry").split())
        fw, fh = action.get("width"), action.get("height")
        if not all(type(v) is int and v > 0 for v in (fw, fh)):
            raise ValueError("desktop_bad_coordinates")
        # Refuse an action for a resized/reconfigured display.
        if [width, height] != [action.get("screen_width"), action.get("screen_height")]:
            raise ValueError("desktop_display_changed")
        def point(x, y):
            if not all(type(v) is int for v in (x, y)) or not (0 <= x < fw and 0 <= y < fh):
                raise ValueError("desktop_bad_coordinates")
            return round(x * width / fw), round(y * height / fh)
        x, y = point(action.get("x"), action.get("y"))
        xdo("mousemove", "--sync", x, y)
        if kind == "click":
            button = {"left": 1, "middle": 2, "right": 3}.get(action.get("button", "left"))
            count = action.get("count", 1)
            if not button or type(count) is not int or count not in (1, 2):
                raise ValueError("desktop_bad_click")
            xdo("click", "--repeat", count, "--delay", 100, button)
        elif kind == "drag":
            end = point(action.get("to_x"), action.get("to_y"))
            try:
                xdo("mousedown", 1)
                xdo("mousemove", "--sync", *end)
            finally:
                xdo("mouseup", 1)
    elif kind == "type":
        text = action.get("text")
        if not isinstance(text, str) or len(text) > 4000 or "\0" in text:
            raise ValueError("desktop_bad_text")
        # Legacy xdotool temporarily remaps absent Unicode keys. A 5ms burst
        # can outrun the target application's keymap processing and drop letters.
        # Pace input and recheck the physical Stop between bounded chunks.
        for offset in range(0, len(text), 16):
            physical_stop()
            xdo("type", "--clearmodifiers", "--delay", 60, "--file", "-",
                text=text[offset:offset + 16])
    elif kind == "key":
        key = action.get("key", "")
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_]+(?:\+[A-Za-z0-9_]+){0,4}", key):
            raise ValueError("desktop_bad_key")
        xdo("key", "--clearmodifiers", key)
    elif kind == "scroll":
        amount = action.get("amount")
        if type(amount) is not int or not 1 <= abs(amount) <= 20:
            raise ValueError("desktop_bad_scroll")
        xdo("click", "--repeat", abs(amount), "--delay", 50, 5 if amount > 0 else 4)
    elif kind == "wait":
        duration = action.get("ms", 1000)
        if type(duration) is not int or not 0 <= duration <= 5000:
            raise ValueError("desktop_bad_wait")
        time.sleep(duration / 1000)
    else:
        raise ValueError("desktop_bad_action")
    return {"acted": True}


if __name__ == "__main__":
    def interrupted(_signum, _frame):
        # Release synthetic held inputs if Stop arrives midway through a chord
        # or drag; exiting alone would not release X11 button state.
        try:
            xdo("mouseup", 1)
            xdo("keyup", "Control_L", "Control_R", "Shift_L", "Shift_R", "Alt_L", "Alt_R", "Super_L", "Super_R")
        finally:
            raise SystemExit(130)
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        raw = sys.stdin.read(20001)
        if len(raw) > 20000:
            raise ValueError("desktop_bad_action")
        print(json.dumps(perform(json.loads(raw))))
    except Exception as error:
        code = str(error) if isinstance(error, ValueError) and str(error).startswith("desktop_") else "desktop_adapter_failed"
        print(json.dumps({"error": code}))
        sys.exit(1)

