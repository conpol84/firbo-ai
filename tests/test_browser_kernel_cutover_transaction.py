"""Transaction simulation for Browser kernel cutover (no Docker/network writes)."""
import importlib.util
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"scripts/deploy-browser-kernel-egress.py"
spec=importlib.util.spec_from_file_location("firbo_kernel_transaction",SOURCE)
release=importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

def old_wrapper():
    slash=chr(92)
    return chr(10).join([
        "#!/usr/bin/env bash","set -euo pipefail",
        "exec /usr/bin/docker run --rm -i --init "+slash,
        release.BEFORE,
        "  --read-only "+slash,
        "  --cap-drop ALL "+slash,
        "  firbo-browser-mcp:0.2.0",
    ])+chr(10)

def prepped(stack,root,events):
    wrapper=root/"firbo-browser-mcp"
    wrapper.write_text(old_wrapper())
    paths={
      "WRAPPER":wrapper,
      "GUARD_INSTALLED":root/"kernel-guard",
      "DROPIN":root/"openjarvis-dropin",
      "STATE":root/"manifest"/"receipt.json",
      "BACKUP_BASE":root/"backups",
    }
    for key,value in paths.items():
        stack.enter_context(patch.object(release,key,value))
    stack.enter_context(patch.object(release,"before",return_value=old_wrapper()))
    stack.enter_context(patch.object(release.os,"chown",return_value=None))
    def fake_run(*argv,**kw):
        events.append(("command",argv))
        if argv[-3:]==("rev-parse","HEAD"):
            return "source-commit"
        if argv[:1]==("python3",):
            return "FIRBO_BROWSER_DIRECT_READ_NO_MODEL_E2E_PASS"
        return ""
    stack.enter_context(patch.object(release,"run",side_effect=fake_run))
    return paths

class TransactionTests(unittest.TestCase):
    def test_kernel_policy_setup_failure_restores_old_wrapper_and_removes_scoped_resources(self):
        with tempfile.TemporaryDirectory() as dirname,ExitStack() as stack:
            events=[]
            paths=prepped(stack,Path(dirname),events)
            stack.enter_context(patch.object(
                release.fw,"ensure",side_effect=RuntimeError("simulated_failure")
            ))
            stack.enter_context(patch.object(
                release.fw,"remove",side_effect=lambda:events.append(("remove",))
            ))
            stack.enter_context(patch.object(release.fw,"run",return_value=""))
            with self.assertRaises(RuntimeError):
                release.apply()
            self.assertEqual(paths["WRAPPER"].read_text(),old_wrapper())
            self.assertFalse(paths["STATE"].exists())
            self.assertFalse(paths["DROPIN"].exists())
            self.assertFalse(paths["GUARD_INSTALLED"].exists())
            self.assertIn(("remove",),events)
            self.assertTrue(any(p.name=="firbo-browser-mcp"
                                for p in paths["BACKUP_BASE"].rglob("*")))

    def test_complete_cutover_runs_negative_probe_before_root_wrapper_change(self):
        with tempfile.TemporaryDirectory() as dirname,ExitStack() as stack:
            events=[]
            paths=prepped(stack,Path(dirname),events)
            stack.enter_context(patch.object(release.fw,"ensure",
                side_effect=lambda:events.append(("ensure",))))
            stack.enter_context(patch.object(release.fw,"verify",return_value=None))
            def probe():
                self.assertEqual(paths["WRAPPER"].read_text(),old_wrapper())
                events.append(("negative_probe",))
            stack.enter_context(patch.object(release,"socket_negative_probe",
                                             side_effect=probe))
            stack.enter_context(patch.object(release,"guard_verify",
                side_effect=lambda:events.append(("verify",))))
            stack.enter_context(patch.object(release,"wait_health",
                                             return_value=None))
            release.apply()
            text=paths["WRAPPER"].read_text()
            self.assertIn(release.AFTER,text)
            self.assertNotIn(release.BEFORE,text)
            self.assertIn(release.GUARD_COMMAND,text)
            self.assertEqual(paths["DROPIN"].read_text(),release.DROPIN_TEXT)
            self.assertTrue(paths["STATE"].exists())
            self.assertEqual(paths["GUARD_INSTALLED"].read_text(),
              (ROOT/"scripts/browser-kernel-guard.py").read_text())
            self.assertEqual(next(paths["BACKUP_BASE"].rglob("firbo-browser-mcp")).read_text(),
                             old_wrapper())
            self.assertLess(events.index(("ensure",)),events.index(("negative_probe",)))
            self.assertLess(events.index(("negative_probe",)),events.index(("verify",)))
            self.assertTrue(any(e[0]=="command" and e[1][:2]==(
                "systemctl","restart") for e in events))

if __name__=="__main__":
    unittest.main()
