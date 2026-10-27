#!/usr/bin/env python3
"""FIRBO Production V1 — safe, READ-ONLY Hostinger Browser network posture.

No firewall/network/container changes, no HTTP provider requests, no credentials,
no user data, no model calls. Outputs only boolean/policy identifiers.

The existing application-level Chromium policy is helpful but is *not* a
kernel-level egress boundary. A shared Docker bridge could be used by other
containers; DO NOT add global DOCKER-USER/INPUT rules without first inspecting
this live host. Requires owner root terminal to inspect root-owned wrapper.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

IMAGE = "firbo-browser-mcp:0.2.0"
WRAPPER = Path("/usr/local/sbin/firbo-browser-mcp")
POLICY_SOURCE = Path(__file__).resolve().parents[1] / "services/browser-mcp/network-policy.mjs"
EXPECTED_POLICY_SHA256 = "a66379f52d9a265e8eb17e76ae5011c035a48876389ccdeb843b9b1741856299"


def command(argv: list[str], *, seconds: int = 7) -> tuple[bool, str]:
    """No shell, no environment contents, no logging of untrusted command output."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=seconds, check=False)
        return p.returncode == 0, p.stdout.strip()[:160]
    except (OSError, subprocess.TimeoutExpired):
        return False, ""


def inspect_wrapper(data: str) -> dict[str, bool | str]:
    """Recognize the installed, root-owned wrapper without parsing secrets."""
    flags = re.findall(r"(?:^|\s)--network\s+([\w.-]+)", data, re.M)
    selected = flags[0] if len(flags) == 1 else "unknown"
    return {
        "network": selected,
        "image_ref_matches": IMAGE in data,
        "security_flags_present": all(k in data for k in (
            "--read-only", "--cap-drop ALL", "--security-opt no-new-privileges",
            "--security-opt seccomp=", "--pids-limit ",
        )),
        "dedicated_bridge": selected not in ("bridge", "host", "none", "unknown"),
        "shared_default_bridge": selected == "bridge",
    }


def audit() -> dict[str, object]:
    source_bytes = POLICY_SOURCE.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    if source_hash != EXPECTED_POLICY_SHA256:
        raise RuntimeError("browser_repo_policy_changed")
    if not WRAPPER.is_file() or WRAPPER.is_symlink():
        raise RuntimeError("browser_owner_wrapper_missing")
    wrapper = inspect_wrapper(WRAPPER.read_text(encoding="utf-8"))
    ok_hash, observed_hash = command([
        "docker", "run", "--rm", "--network", "none", "--read-only",
        "--entrypoint", "sha256sum", IMAGE, "/app/network-policy.mjs",
    ], seconds=15)
    image_match = ok_hash and observed_hash.split(maxsplit=1)[0] == source_hash

    # Docker 29+ may use nftables instead of iptables. DOCKER-USER is NOT
    # an enforcement hook under nftables: the status flags are diagnostics,
    # not a licence to flip broad subscriber browsing ON.
    iptables_chain, _ = command(["iptables", "-w", "1", "-S", "DOCKER-USER"])
    iptables_forward_hook, _ = command([
        "iptables", "-w", "1", "-C", "FORWARD", "-j", "DOCKER-USER",
    ])
    nft_bridge_table, _ = command(["nft", "list", "table", "ip", "docker-bridges"])
    daemon_conf = Path("/etc/docker/daemon.json")
    config_backend = "unspecified"
    docker_ipv6 = "unspecified"
    if daemon_conf.is_file():
        try:
            conf = json.loads(daemon_conf.read_text(encoding="utf-8"))
            backend = conf.get("firewall-backend")
            if backend in ("iptables", "nftables"):
                config_backend = backend
            if isinstance(conf.get("ipv6"), bool):
                docker_ipv6 = str(conf["ipv6"]).lower()
        except (ValueError, OSError):
            config_backend = "unreadable"

    # Only exact named, single network; no network creation and no inspection
    # of other applications. This may not exist yet and that's expected.
    network_name = wrapper["network"]
    network_known = bool(re.fullmatch(r"[a-zA-Z][\w.-]{0,62}", str(network_name)))
    dedicated_network_present = False
    if wrapper["dedicated_bridge"] and network_known:
        inspect_ok, driver = command([
            "docker", "network", "inspect", "-f", "{{.Driver}}",
            str(network_name),
        ])
        dedicated_network_present = inspect_ok and driver == "bridge"

    return {
        "repo_policy_sha256_match": source_hash == EXPECTED_POLICY_SHA256,
        "live_image_policy_sha256_match": image_match,
        "wrapper_image_ref_match": wrapper["image_ref_matches"],
        "wrapper_security_flags_present": wrapper["security_flags_present"],
        "wrapper_network_mode": network_name,
        "browser_uses_shared_default_bridge": wrapper["shared_default_bridge"],
        "browser_has_dedicated_bridge": dedicated_network_present,
        "docker_iptables_user_chain_exists": iptables_chain,
        "docker_iptables_forward_hook_present": iptables_forward_hook,
        "docker_nftables_bridge_table_present": nft_bridge_table,
        "docker_configured_firewall_backend": config_backend,
        "docker_ipv6_configured": docker_ipv6,
        # Never infer effective firewall policy from chain/table existence.
        "kernel_private_network_egress_accepted": False,
        "broad_subscriber_browser_release_approved": False,
    }


def main() -> int:
    print("FIRBO_BROWSER_OS_NETWORK_READ_ONLY_AUDIT_V1")
    try:
        result = audit()
    except (OSError, UnicodeError, RuntimeError):
        print("FIRBO_BROWSER_OS_NETWORK_AUDIT_INCOMPLETE")
        print("kernel_private_network_egress_accepted=false")
        return 1
    for key, value in result.items():
        if isinstance(value, bool):
            value = "true" if value else "false"
        print(f"{key}={value}")
    print("FIRBO_BROWSER_OS_NETWORK_AUDIT_READ_ONLY_PASS")
    print("FIRBO_BROWSER_OS_EGRESS_ACCEPTANCE_STILL_OPEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
