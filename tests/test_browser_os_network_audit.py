"""No-cost, no-network tests of read-only host Browser egress audit."""
from __future__ import annotations
import importlib.util
import inspect
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "scripts/audit-browser-os-network.py"
spec = importlib.util.spec_from_file_location("browser_os_audit", SRC)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class BrowserOsNetworkAuditTests(unittest.TestCase):
    def test_accept_exact_old_browser_bridge_wrapper_without_claiming_network_isolation(self):
        wrapper = """#!/usr/bin/env bash
set -euo pipefail
exec /usr/bin/docker run --rm -i --init \\
  --network bridge \\
  --read-only \\
  --cap-drop ALL \\
  --security-opt no-new-privileges \\
  --security-opt seccomp=/usr/local/share/firbo-playwright-seccomp.json \\
  --pids-limit 256 \\
  firbo-browser-mcp:0.2.0
"""
        w = module.inspect_wrapper(wrapper)
        self.assertTrue(w["shared_default_bridge"])
        self.assertFalse(w["dedicated_bridge"])
        self.assertTrue(w["image_ref_matches"])
        self.assertTrue(w["security_flags_present"])

    def test_unknown_multinetwork_or_host_is_never_dedicated(self):
        for command in (
            "--network bridge --network firbo-test",
            "--network host",
            "--network none",
            "--network",
            "unknown content",
        ):
            w = module.inspect_wrapper(command)
            self.assertFalse(w["dedicated_bridge"], command)

    def test_one_named_custom_network_requires_real_bridge_driver(self):
        w = module.inspect_wrapper("--network firbo-restricted --read-only")
        self.assertTrue(w["dedicated_bridge"])
        self.assertEqual(w["network"], "firbo-restricted")

    def test_effective_kernel_is_never_claimed_from_iptables_nftables_presence(self):
        import hashlib
        source = (ROOT / "services/browser-mcp/network-policy.mjs").read_bytes()
        policy = hashlib.sha256(source).hexdigest()
        self.assertEqual(policy, module.EXPECTED_POLICY_SHA256)
        old_wrapper = module.WRAPPER
        old_command = module.command
        with tempfile.TemporaryDirectory() as d:
            wrapper = Path(d) / "installed-browser-wrapper"
            wrapper.write_text(
                "--network bridge --read-only --cap-drop ALL "
                "--security-opt no-new-privileges --security-opt seccomp=/path "
                "--pids-limit 256 firbo-browser-mcp:0.2.0"
            )
            def pretend(argv, *, seconds=7):
                if argv[:2] == ["docker", "run"]:
                    return True, module.EXPECTED_POLICY_SHA256 + "  /app/network-policy.mjs"
                if argv[:2] == ["iptables", "-w"]:
                    return True, ""
                if argv[:3] == ["nft", "list", "table"]:
                    return True, ""
                return False, ""
            module.WRAPPER = wrapper
            module.command = pretend
            try:
                outcome = module.audit()
                self.assertTrue(outcome["live_image_policy_sha256_match"])
                self.assertTrue(outcome["browser_uses_shared_default_bridge"])
                self.assertFalse(outcome["browser_has_dedicated_bridge"])
                self.assertTrue(outcome["docker_iptables_user_chain_exists"])
                self.assertTrue(outcome["docker_nftables_bridge_table_present"])
                self.assertFalse(outcome["kernel_private_network_egress_accepted"])
                self.assertFalse(outcome["broad_subscriber_browser_release_approved"])
                wrapper.write_text(wrapper.read_text().replace("--network bridge","--network firbo-egress"))
                def bridge(argv, *, seconds=7):
                    if argv[:3] == ["docker", "network", "inspect"]:
                        return True, "bridge"
                    return pretend(argv, seconds=seconds)
                module.command = bridge
                new = module.audit()
                self.assertTrue(new["browser_has_dedicated_bridge"])
                self.assertFalse(new["kernel_private_network_egress_accepted"])
            finally:
                module.WRAPPER = old_wrapper
                module.command = old_command

    def test_no_dangerous_host_mutation_or_credentials_collected(self):
        code = SRC.read_text()
        for forbidden in (
            "iptables -I", "iptables -A", "iptables-restore",
            "nft add ", "docker network create", "docker restart",
            "systemctl restart", "docker tag ", "docker build ",
            "/etc/shadow", "/home/jarvis/.openjarvis/serve.env",
            "OPENJARVIS_API_KEY", "curl ",
        ):
            self.assertNotIn(forbidden, code)
        self.assertIn("kernel_private_network_egress_accepted", code)
        self.assertIn("FIRBO_BROWSER_OS_EGRESS_ACCEPTANCE_STILL_OPEN", code)
        self.assertNotIn("shell=True", code)
        self.assertIn("docker\", \"run\", \"--rm\", \"--network\", \"none", code)

if __name__ == "__main__":
    unittest.main()
