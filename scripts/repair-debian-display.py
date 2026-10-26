#!/usr/bin/env python3
"""Replace one known native capture adapter, with a private rollback copy.

No pairing/configuration/permissions changes and no service restart. Each native
action already starts this Python adapter anew. Use the existing desktop user.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

OLD_SHA = "ee7835e7b74f9fcab98acd4e38e1fd3d293dcf33d44f189ab16a3b50628728bc"
NEW_SHA = "5b44017f0c4cdf88d1db65eea090aa69d64a1f8cfc05dc9360c50a1188bd33db"


def digest(data):
    return hashlib.sha256(data).hexdigest()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def install_file(target, payload, old_sha=OLD_SHA, new_sha=NEW_SHA):
    if digest(payload) != new_sha:
        raise ValueError("source_hash_mismatch")
    compile(payload, str(target), "exec")
    if target.is_symlink() or target.parent.is_symlink() or not target.is_file():
        raise ValueError("unsafe_target")
    info = target.stat()
    if (info.st_uid != os.getuid() or info.st_size > 100000
            or target.parent.stat().st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o022):
        raise ValueError("target_owner_or_size")
    previous = target.read_bytes()
    if digest(previous) == new_sha:
        return {"changed": False, "sha256": new_sha}
    if digest(previous) != old_sha:
        raise ValueError("installed_version_unrecognized")
    folder = Path(tempfile.mkdtemp(prefix="firbo-display-backup-", dir=target.parent))
    backup = folder / target.name
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(previous)
        stream.flush()
        os.fsync(stream.fileno())
    fd, temporary = tempfile.mkstemp(prefix=".firbo-display-stage-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, stat.S_IMODE(info.st_mode))
        if target.is_symlink() or target.read_bytes() != previous:
            raise ValueError("target_changed")
        os.replace(temporary, target)
        if digest(target.read_bytes()) != new_sha:
            raise ValueError("installed_hash_mismatch")
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {"changed": True, "sha256": new_sha, "backup": folder.name}


def verify_capture(target, installed):
    # A failed probe must retain the fact that installation already completed.
    try:
        probe = subprocess.run(["/usr/bin/python3", "-B", str(target)],
                               input='{"action":"observe"}', text=True,
                               capture_output=True, timeout=20)
        frame = json.loads(probe.stdout)
        error = frame.get("error")
        if (probe.returncode != 0 or error or not frame.get("image")
                or type(frame.get("width")) is not int or type(frame.get("height")) is not int):
            code = error if isinstance(error, str) and re.fullmatch(r"desktop_[a-z_]+", error) else "desktop_capture_unverified"
            return {**installed, "capture_verified": False, "error": code}
        return {**installed, "capture_verified": True,
                "width": frame["width"], "height": frame["height"],
                "frame_sha256": digest(frame["image"].encode())}
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError):
        return {**installed, "capture_verified": False, "error": "desktop_capture_unverified"}


def main():
    parser = argparse.ArgumentParser()
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--source")
    operation.add_argument("--rollback", help="Backup folder from the installation receipt")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if os.geteuid() == 0 or not Path("/etc/debian_version").is_file():
        raise ValueError("debian_desktop_user_required")
    target = Path.home() / "Downloads" / "firbo-desktop.py"
    if args.rollback:
        if not re.fullmatch(r"firbo-display-backup-[a-z0-9_]{8}", args.rollback):
            raise ValueError("invalid_backup")
        backup = target.parent / args.rollback / target.name
        if (backup.is_symlink() or backup.parent.is_symlink() or not backup.is_file()
                or backup.stat().st_uid != os.getuid() or backup.stat().st_size > 100000):
            raise ValueError("invalid_backup")
        payload = backup.read_bytes()
        if digest(payload) != OLD_SHA:
            raise ValueError("backup_hash_mismatch")
        if not args.apply:
            print(json.dumps({"checked": True, "rollback_sha256": OLD_SHA}))
            return
        print(json.dumps({**install_file(target, payload, NEW_SHA, OLD_SHA), "restored": True}))
        return
    if not re.fullmatch(r"[a-f0-9]{40}", args.source):
        raise ValueError("immutable_source_required")
    if target.is_symlink() or not target.is_file() or digest(target.read_bytes()) not in (OLD_SHA, NEW_SHA):
        raise ValueError("installed_version_unrecognized")
    url = f"https://raw.githubusercontent.com/conpol84/firbo-ai/{args.source}/services/desktop-worker/firbo-desktop.py"
    with build_opener(ProxyHandler({}), NoRedirect()).open(url, timeout=15) as response:
        payload = response.read(100001)
    if len(payload) > 100000 or digest(payload) != NEW_SHA:
        raise ValueError("source_hash_mismatch")
    compile(payload, str(target), "exec")
    if not args.apply:
        print(json.dumps({"checked": True, "target_sha256": NEW_SHA}))
        return
    installed = install_file(target, payload)
    # Only dimensions/hash leave the local process, never image pixels.
    print(json.dumps(verify_capture(target, installed)))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        code = str(exc) if isinstance(exc, ValueError) and re.fullmatch(r"[a-z_]+", str(exc)) else "display_repair_failed"
        print(json.dumps({"changed": None, "capture_verified": False, "error": code}))
        raise SystemExit(1)
