import importlib.util
import json
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
adapter = module('adapter', ROOT / 'services/desktop-worker/firbo-desktop.py')
repair = module('repair', ROOT / 'scripts/repair-debian-display.py')

class WakeTests(unittest.TestCase):
    def run_wake(self, values='LockedHint=no\nDisplay=:0\nType=x11\nActive=yes', after='On', before='Off'):
        calls = []
        def run(args, **kwargs):
            calls.append(args)
            if args[:2] == ['xset', 'q']:
                out = 'Monitor is ' + (after if len(calls) > 1 else before)
            elif args[:2] == ['loginctl', 'show-user']: out = '7'
            elif args[:2] == ['loginctl', 'show-session']: out = values
            else: out = ''
            return subprocess.CompletedProcess(args, 0, out, '')
        with patch.object(adapter.subprocess, 'run', side_effect=run), patch.dict(os.environ, {'DISPLAY': ':0'}), patch.object(adapter.time, 'sleep'):
            try: adapter.wake_display()
            except ValueError as exc: return calls, str(exc)
        return calls, None

    def test_unlocked_matching_display_wakes_once_without_policy_changes(self):
        calls, error = self.run_wake()
        self.assertIsNone(error)
        self.assertEqual([x for x in calls if x[:2] == ['xset', 'dpms']], [['xset', 'dpms', 'force', 'on']])
        self.assertFalse(any('unlock-session' in x or '-dpms' in x for x in calls))

    def test_locked_or_unknown_or_other_session_never_wakes(self):
        for data in ['LockedHint=yes\nDisplay=:0\nType=x11', 'Display=:0\nType=x11',
                     'LockedHint=no\nDisplay=:1\nType=x11', 'LockedHint=no\nDisplay=:0\nType=wayland']:
            calls, error = self.run_wake(data)
            self.assertIn(error, ['desktop_session_locked', 'desktop_session_unverified'])
            self.assertFalse(any(x[:2] == ['xset', 'dpms'] for x in calls))

    def test_power_on_is_read_only(self):
        calls, error = self.run_wake(before='On')
        self.assertIsNone(error)
        self.assertEqual(calls, [['xset', 'q']])

    def test_failed_wake_is_not_success(self):
        _, error = self.run_wake(after='Off')
        self.assertEqual(error, 'desktop_display_wake_failed')

    def test_unavailable_xset_fails_finitely(self):
        with patch.object(adapter.subprocess, 'run', side_effect=FileNotFoundError):
            with self.assertRaisesRegex(ValueError, 'desktop_display_power_unavailable'): adapter.wake_display()

    def test_no_dpms_extension_allows_normal_capture(self):
        with patch.object(adapter.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'DPMS extension not supported')) as run:
            adapter.wake_display()
            self.assertEqual(run.call_count, 1)

    def test_black_capture_stops_before_inference_and_valid_capture_still_works(self):
        from PIL import Image, ImageGrab
        with patch.object(adapter, 'wake_display'), patch.object(adapter, 'verify_unlocked_session'), patch.object(adapter.subprocess, 'run'), patch.object(adapter.time, 'sleep'), patch.dict(os.environ, {'DISPLAY': ':0'}):
            for color in ['black', 'white']:
                with patch.object(ImageGrab, 'grab', return_value=Image.new('RGB', (100, 80), color)):
                    if color == 'black':
                        with self.assertRaisesRegex(ValueError, 'desktop_capture_black'): adapter.capture()
                    else:
                        frame = adapter.capture()
                        self.assertEqual((frame['width'], frame['height']), (100, 80))
                        self.assertTrue(frame['image'])

    def test_black_frame_wakes_blanker_once_and_rechecks_capture(self):
        from PIL import Image, ImageGrab
        with patch.object(adapter, 'wake_display'), patch.object(adapter, 'verify_unlocked_session') as verify, patch.object(adapter.subprocess, 'run') as run, patch.object(adapter.time, 'sleep'), patch.dict(os.environ, {'DISPLAY': ':0'}), patch.object(ImageGrab, 'grab', side_effect=[Image.new('RGB', (100,80), 'black'),Image.new('RGB', (100,80), 'white')]):
            self.assertTrue(adapter.capture()['image'])
            self.assertEqual(verify.call_count, 2)
            self.assertEqual(run.call_args.args[0], ['xset', 's', 'reset'])
            self.assertEqual(run.call_count, 1)

    def test_locked_black_frame_never_resets_blanker(self):
        from PIL import Image, ImageGrab
        with patch.object(adapter, 'wake_display'), patch.object(adapter, 'verify_unlocked_session', side_effect=ValueError('desktop_session_locked')), patch.object(adapter.subprocess, 'run') as run, patch.dict(os.environ, {'DISPLAY': ':0'}), patch.object(ImageGrab, 'grab', return_value=Image.new('RGB', (100,80), 'black')):
            with self.assertRaisesRegex(ValueError, 'desktop_session_locked'): adapter.capture()
            run.assert_not_called()

    def test_inactive_session_is_identified_without_wake_or_session_switch(self):
        calls, error = self.run_wake('LockedHint=no\nDisplay=:0\nType=x11\nActive=no')
        self.assertEqual(error, 'desktop_session_inactive')
        self.assertFalse(any(x[:2] == ['xset', 'dpms'] for x in calls))
        self.assertFalse(any('activate' in x or 'unlock-session' in x for x in calls))

    def test_inactive_session_never_captures_even_with_monitor_on(self):
        from PIL import ImageGrab
        with patch.object(adapter, 'verify_unlocked_session', side_effect=ValueError('desktop_session_inactive')), patch.object(adapter, 'wake_display') as wake, patch.object(ImageGrab, 'grab') as grab:
            with self.assertRaisesRegex(ValueError, 'desktop_session_inactive'): adapter.capture()
            wake.assert_not_called(); grab.assert_not_called()

    def test_session_switch_during_planning_blocks_the_next_input(self):
        with patch.dict(os.environ, {'DISPLAY': ':0', 'WAYLAND_DISPLAY': ''}), patch.object(adapter.os, 'geteuid', return_value=1000), patch.object(adapter, 'verify_unlocked_session', side_effect=ValueError('desktop_session_inactive')), patch.object(adapter, 'xdo') as xdo:
            with self.assertRaisesRegex(ValueError, 'desktop_session_inactive'): adapter.perform({'action':'key','key':'Return'})
            xdo.assert_not_called()

class InstallTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.target = Path(self.dir.name) / 'firbo-desktop.py'
        self.old = b'print("old")\n'
        self.new = b'print("new")\n'
        self.target.write_bytes(self.old)
        self.target.chmod(0o700)
    def tearDown(self): self.dir.cleanup()
    def install(self, payload=None):
        return repair.install_file(self.target, payload or self.new, repair.digest(self.old), repair.digest(self.new))
    def test_atomic_update_private_backup_and_idempotency(self):
        receipt = self.install()
        self.assertTrue(receipt['changed'])
        backup = self.target.parent / receipt['backup'] / self.target.name
        self.assertEqual(backup.read_bytes(), self.old)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.target.read_bytes(), self.new)
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o700)
        self.assertFalse(self.install()['changed'])
        self.assertEqual(len(list(self.target.parent.glob('firbo-display-backup-*'))), 1)
    def test_reject_corrupt_payload_unknown_version_and_symlink(self):
        with self.assertRaisesRegex(ValueError, 'source_hash_mismatch'): self.install(b'print("other")')
        self.target.write_bytes(b'custom version')
        with self.assertRaisesRegex(ValueError, 'installed_version_unrecognized'): self.install()
        self.target.unlink(); self.target.symlink_to('/etc/hosts')
        with self.assertRaisesRegex(ValueError, 'unsafe_target'): self.install()
    def test_group_writable_target_is_rejected(self):
        self.target.chmod(0o720)
        with self.assertRaisesRegex(ValueError, 'target_owner_or_size'): self.install()
    def test_concurrent_change_is_preserved(self):
        chmod = os.chmod
        def race(path, mode):
            chmod(path, mode)
            self.target.write_bytes(b'concurrent change')
        with patch.object(repair.os, 'chmod', side_effect=race):
            with self.assertRaisesRegex(ValueError, 'target_changed'): self.install()
        self.assertEqual(self.target.read_bytes(), b'concurrent change')
    def test_probe_timeout_keeps_installation_receipt(self):
        receipt = self.install()
        with patch.object(repair.subprocess, 'run', side_effect=subprocess.TimeoutExpired('probe', 20)):
            result = repair.verify_capture(self.target, receipt)
        self.assertTrue(result['changed']); self.assertFalse(result['capture_verified'])
        self.assertEqual(result['backup'], receipt['backup'])
    def test_failed_capture_keeps_finite_error_without_pixels(self):
        for out in ['garbage', '{"error":"desktop_session_locked"}', '{"image":"PRIVATE_PIXELS","error":"secret output"}']:
            with patch.object(repair.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, out)):
                result = repair.verify_capture(self.target, {'changed': True})
            self.assertFalse(result['capture_verified'])
            self.assertNotIn('PRIVATE_PIXELS', json.dumps(result))
            self.assertNotIn('secret output', json.dumps(result))
    def test_verified_capture_has_only_hash_and_dimensions(self):
        with patch.object(repair.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '{"image":"PIXELS","width":20,"height":10}')):
            result = repair.verify_capture(self.target, {'changed': True})
        self.assertTrue(result['capture_verified']); self.assertNotIn('PIXELS', json.dumps(result))
        self.assertEqual(result['frame_sha256'], repair.digest(b'PIXELS'))
    def test_release_manifest_matches_adapter(self):
        data = (ROOT / 'services/desktop-worker/firbo-desktop.py').read_bytes()
        self.assertEqual(repair.digest(data), repair.NEW_SHA)
        compile(data, 'adapter', 'exec')

    def test_rollback_restores_only_known_repaired_version(self):
        import sys
        downloads = Path(self.dir.name) / 'Downloads'
        downloads.mkdir()
        self.target.rename(downloads / self.target.name)
        self.target = downloads / self.target.name
        receipt = self.install()
        with patch.object(repair.Path, 'home', return_value=Path(self.dir.name)), patch.object(repair.os, 'geteuid', return_value=1000), patch.object(repair, 'OLD_SHA', repair.digest(self.old)), patch.object(repair, 'NEW_SHA', repair.digest(self.new)), patch.object(sys, 'argv', ['repair', '--rollback', receipt['backup'], '--apply']), patch('sys.stdout', new_callable=io.StringIO) as out:
            repair.main()
            self.assertTrue(json.loads(out.getvalue())['restored'])
            self.assertEqual(self.target.read_bytes(), self.old)
            self.target.write_bytes(b'newer custom version')
            with self.assertRaisesRegex(ValueError, 'installed_version_unrecognized'): repair.main()

if __name__ == '__main__': unittest.main()
