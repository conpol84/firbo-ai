#!/usr/bin/env python3
"""Persist ONLY FIRBO's already-working Ollama network on the existing Compose overlay.

--check: validate a proposed one-service Compose change without writing it.
--apply: atomically update the existing memory overlay after backup & semantic diff.
This never starts, stops, builds or recreates any container.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/root/javris-clone/deploy/hostinger")
BASE = ROOT / "docker-compose.yml"
OVERLAY = ROOT / "compose.firbo-memory.yaml"
BACKUPS = Path("/var/backups/firbo-memory-compose")
NETWORK_KEY = "firbo_ollama_external"
VALID_NETWORK = re.compile(r"^firbo-local-[a-z0-9_-]{5,100}$")
CONFIG_LABEL = "com.docker.compose.project.config_files"
PROJECT_LABEL = "com.docker.compose.project"


class Blocked(Exception):
    pass


def shell(*args: str, cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            args, check=True, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=40, cwd=cwd
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        raise Blocked("runtime_preflight_failed") from None
    return result.stdout.strip()


def inspect_container(name: str) -> dict:
    try:
        data = json.loads(shell("docker", "inspect", name))
        row = data[0]
        if row.get("State", {}).get("Running") is not True:
            raise Blocked("container_not_running")
        return row
    except (ValueError, KeyError, IndexError, TypeError):
        raise Blocked("container_inspect_invalid") from None


def verify_live_network() -> tuple[str, str]:
    api = inspect_container("firbo-api")
    ollama = inspect_container("firbo-ollama")
    labels = api.get("Config", {}).get("Labels") or {}
    if labels.get(PROJECT_LABEL) != "hostinger":
        raise Blocked("wrong_compose_project")
    files = labels.get(CONFIG_LABEL, "").split(",")
    if files != [str(BASE), str(OVERLAY)]:
        raise Blocked("active_compose_file_set_changed")
    api_nets = (api.get("NetworkSettings") or {}).get("Networks") or {}
    ollama_nets = (ollama.get("NetworkSettings") or {}).get("Networks") or {}
    if "hostinger_default" not in api_nets:
        raise Blocked("primary_network_missing")
    common = [
        n for n in api_nets if n in ollama_nets and VALID_NETWORK.fullmatch(n)
    ]
    if len(common) != 1:
        raise Blocked("ollama_network_not_unique_or_not_attached")
    network = common[0]
    # Verify the external network exists; never create or expose a new network.
    shell("docker", "network", "inspect", network)
    return network, str(api.get("Id", ""))


def patch_memory_overlay(source: str, network: str) -> str:
    """Conservative textual patch; refuse unknown YAML structures rather than reformat.

    The semantic Docker Compose JSON comparison is a SECOND independent gate.
    """
    if not VALID_NETWORK.fullmatch(network):
        raise Blocked("unexpected_network_name")
    if not source or len(source) > 100_000 or "\r" in source or "\t" in source:
        raise Blocked("unsupported_compose_source")
    if NETWORK_KEY in source:
        raise Blocked("network_key_already_present_requires_review")
    lines = source.splitlines(keepends=True)
    services = [i for i, s in enumerate(lines) if s.strip() == "services:" and s.startswith("services:")]
    if len(services) != 1:
        raise Blocked("services_structure_ambiguous")
    start = services[0] + 1
    end = next((i for i in range(start, len(lines)) if lines[i].strip()
                and not lines[i].startswith((" ", "#", "\n"))), len(lines))
    matches = [i for i in range(start, end) if re.fullmatch(r"  firbo-api:\s*", lines[i])]
    if len(matches) != 1:
        raise Blocked("api_service_structure_ambiguous")
    pos = matches[0]
    next_service = next((i for i in range(pos + 1, end)
                        if re.match(r"^  [A-Za-z0-9_-]+:\s*$", lines[i])), end)
    if any(re.match(r"^    (networks|network_mode):", s) for s in lines[pos + 1:next_service]):
        raise Blocked("api_network_already_declared")
    lines[pos + 1:pos + 1] = [
        "    networks:\n",
        "      - default\n",
        f"      - {NETWORK_KEY}\n",
    ]
    root = [i for i, s in enumerate(lines) if re.fullmatch(r"networks:\s*", s)]
    if len(root) > 1:
        raise Blocked("root_networks_ambiguous")
    if root:
        lines[root[0] + 1:root[0] + 1] = [
            f"  {NETWORK_KEY}:\n",
            "    external: true\n",
            f"    name: {network}\n",
        ]
    else:
        if lines and not lines[-1].endswith("\n"):
            lines.append("\n")
        lines.extend([
            "\nnetworks:\n",
            f"  {NETWORK_KEY}:\n",
            "    external: true\n",
            f"    name: {network}\n",
        ])
    return "".join(lines)


def get_config(overlay: Path) -> dict:
    output = shell(
        "docker", "compose", "-p", "hostinger",
        "-f", str(BASE), "-f", str(overlay),
        "config", "--format", "json", cwd=ROOT,
    )
    try:
        data = json.loads(output)
        if not isinstance(data, dict):
            raise ValueError
        return data
    except ValueError:
        raise Blocked("compose_json_invalid") from None


def verify_only_network_change(before: dict, after: dict, network: str) -> None:
    original = copy.deepcopy(before)
    candidate = copy.deepcopy(after)
    services_before = original.get("services") or {}
    services_after = candidate.get("services") or {}
    if set(services_before) != set(services_after) or "firbo-api" not in services_before:
        raise Blocked("service_set_changed")
    old = services_before["firbo-api"]
    new = services_after["firbo-api"]
    initial_nets = old.get("networks") or {}
    added_nets = new.get("networks") or {}
    if not isinstance(initial_nets, dict) or not isinstance(added_nets, dict):
        raise Blocked("network_contract_invalid")
    if set(initial_nets) not in (set(), {"default"}):
        raise Blocked("complex_primary_network_requires_review")
    if set(added_nets) != {"default", NETWORK_KEY}:
        raise Blocked("required_networks_not_preserved")
    # docker compose config --format json is a normalized *rendering*, not
    # guaranteed to preserve a source YAML network stanza byte-for-byte.
    # Different CLI releases can omit external:true once the external name is
    # resolved, or emit harmless empty/default fields. The source patch above
    # itself always writes external:true and the existing network name.
    # Keep a STRICT allowlist here: never accept changed names, explicit
    # external:false, drivers, nonempty IPAM/labels or unrelated network config.
    definition = (candidate.get("networks") or {}).get(NETWORK_KEY)
    if not isinstance(definition, dict) or definition.get("name") != network:
        raise Blocked("external_network_name_mismatch")
    if "external" in definition and definition["external"] is not True:
        raise Blocked("external_network_not_external")
    empty_defaults = {
        "labels": ({}, None),
        "driver_opts": ({}, None),
        "ipam": ({}, None),
        "driver": (None, ""),
        "attachable": (False, None),
        "internal": (False, None),
    }
    for attribute, value in definition.items():
        if attribute in ("name", "external"):
            continue
        if attribute not in empty_defaults or value not in empty_defaults[attribute]:
            raise Blocked("external_network_has_unexpected_attributes")
    candidate["networks"].pop(NETWORK_KEY)
    if "networks" not in original:
        candidate.pop("networks", None)
    new["networks"] = initial_nets
    if not initial_nets and "networks" not in old:
        new.pop("networks", None)
    if candidate != original:
        raise Blocked("unrelated_compose_configuration_changed")


def check_file(path: Path) -> None:
    if not path.is_file() or path.is_symlink():
        raise Blocked("missing_or_linked_compose_file")
    if path.stat().st_size > 100_000:
        raise Blocked("compose_file_too_large")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="validate without changing any deployment files")
    mode.add_argument("--apply", action="store_true", help="write backup and persist network config without restarting")
    args = parser.parse_args()
    if args.apply and os.geteuid() != 0:
        raise Blocked("apply_requires_root")
    for f in (BASE, OVERLAY):
        check_file(f)
    network, api_id = verify_live_network()
    source = OVERLAY.read_text(encoding="utf-8")
    proposal = patch_memory_overlay(source, network)

    with tempfile.TemporaryDirectory(prefix="firbo-m4-check-") as temp:
        candidate_path = Path(temp) / "compose.firbo-memory.yaml"
        candidate_path.write_text(proposal, encoding="utf-8")
        before = get_config(OVERLAY)
        after = get_config(candidate_path)
        verify_only_network_change(before, after, network)
    print("FIRBO_M4_NETWORK_PREFLIGHT_PASS")
    if args.check:
        return 0
    # Compare-and-swap: no one has edited the current overlay while validating.
    if OVERLAY.read_text(encoding="utf-8") != source:
        raise Blocked("compose_changed_during_preflight")
    live_network, live_id = verify_live_network()
    if live_network != network or live_id != api_id:
        raise Blocked("container_changed_during_preflight")
    BACKUPS.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = BACKUPS / f"compose.firbo-memory.{stamp}.yaml"
    if backup.exists():
        raise Blocked("backup_name_collision")
    shutil.copy2(OVERLAY, backup)
    backup.chmod(0o600)
    old_stat = OVERLAY.stat()
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=ROOT,
        prefix=".firbo-m4-network-", delete=False
    ) as output:
        temporary = Path(output.name)
        output.write(proposal)
    try:
        os.chmod(temporary, stat.S_IMODE(old_stat.st_mode))
        os.chown(temporary, old_stat.st_uid, old_stat.st_gid)
        os.replace(temporary, OVERLAY)
        verify_only_network_change(before, get_config(OVERLAY), network)
    except Exception:
        # Restore only the exact backed-up overlay. Containers are untouched.
        shutil.copy2(backup, OVERLAY)
        raise
    finally:
        temporary.unlink(missing_ok=True)
    print(f"FIRBO_M4_NETWORK_COMPOSE_BACKUP={backup}")
    print("FIRBO_M4_NETWORK_PERSISTED_NO_RESTART")
    print("Future Compose recreation MUST use the same two currently-active files.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Blocked as error:
        raise SystemExit(f"FIRBO_M4_NETWORK_BLOCKED: {error}") from None
