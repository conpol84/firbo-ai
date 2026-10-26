# Existing X11 worker capture repair

This adapter is used by the existing local FIRBO Connector desktop worker. It does not add another server, route, task authority or model provider. The Connector starts this Python process for each action; updating the known adapter does not require restarting the service.

Every capture and input action first requires a positively active, unlocked, matching X11 session. An inactive session stops as `desktop_session_inactive` before wake, capture or model inference. This adapter never activates a session or switches virtual terminals; the owner must return to the existing graphical session through the normal desktop/login screen.

When DPMS reports Off/Standby/Suspend, capture verifies logind's current user session is X11, explicitly unlocked, and matches DISPLAY, then requests `xset dpms force on`. Locked, unknown or mismatched sessions stop with a finite error. No unlock, idle-policy change, permission change, input fallback or device substitution occurs. If the first frame stays black after DPMS wakes, capture verifies the unlocked matching session again and resets the transient X11 blanker once (`xset s reset`), then captures again. This does not disable screensaving or alter its timeout; it never sends an unlock or locker-deactivation command. Persistently black frames stop before paid inference. This release upgrades the known first DPMS repair; its private backup allows rollback to that version. An unsupported DPMS extension leaves normal capture available. A nonblack frame alone is not desktop-goal acceptance.

## Owner-authorized installation

Use the existing desktop user, not root. The installer only accepts an immutable 40-character commit and the two declared adapter hashes. It refuses unknown installed versions, symlinks, foreign ownership and group/world-writable files. It preserves a private backup, checks for concurrent changes, and atomically replaces only `~/Downloads/firbo-desktop.py`. Pairing/configuration, other adapters, services and RLS are untouched.

After retrieving the installer from the reviewed immutable release and verifying its SHA-256:

```sh
python3 -B repair-debian-display.py --source REVIEWED_40_CHARACTER_COMMIT
python3 -B repair-debian-display.py --source REVIEWED_40_CHARACTER_COMMIT --apply
```

The resulting receipt includes the installed SHA, backup folder and capture verification. A failed capture probe preserves the successful installation receipt; `capture_verified: false` remains unaccepted even if transport succeeded. Screenshot pixels are never included in this repair receipt. `changed: null` on an installation error means inspect the target/backup before retrying, not that no change occurred.

Rollback uses the backup folder returned by this installation, and only replaces the known repaired hash (never an unrecognized subsequent version):

```sh
python3 -B repair-debian-display.py --rollback firbo-display-backup-XXXXXXXX
python3 -B repair-debian-display.py --rollback firbo-display-backup-XXXXXXXX --apply
```

Run `python3 -m unittest discover -s tests -p test_debian_display.py -v`. Pillow is required for the capture test and worker. Runtime acceptance still requires the owner-authorized exact-device repair receipt, a successful native task, and independently observed Stop behavior. Do not claim these from source tests.

The adapter derives from `conpol84/javris-clone` at `ff973cdd567c7526a892de99435a6ee24cb1c0a8`, `frontend/public/firbo-desktop.py`, Apache-2.0. Original capture/input logic is retained except for the documented power-state and black-frame checks. License is in the repository root.
