#!/usr/bin/env python3
"""FIRBO Browser V1 — scoped kernel IPv4 firewall for its PRIVATE Docker bridge.

No secrets, app databases, provider calls, or other container/network changes.
Runs as root via the dedicated guarded installer and OpenJarvis ExecStartPre.
The installed Browser wrapper calls 'verify' before creating EVERY browser
session. A missing/modified firewall therefore refuses new browser sessions.

The following is a layer in addition to Playwright's DNS/IP URL inspection.
Only a labelled Docker bridge with IPv6 disabled may be used. We create
one targeted jump at the very TOP of DOCKER-USER and INPUT, never modify
Docker-owned chains/rules or global default policies, and never ACCEPT a
packet past Docker's own forwarding checks.
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys

NETWORK="firbo-browser-egress-v1"
BRIDGE="br-firbo-v1"
CHAIN="FIRBO_BROWSER_V1"
LABEL="firbo.browser.egress"
LABEL_VALUE="locked-v1"
# No non-public/metadata/overlay/private destination may be forwarded. Local
# host access (even via its public IP) is blocked by the bridge INPUT hook.
BOGONS=(
 "0.0.0.0/8","10.0.0.0/8","100.64.0.0/10","127.0.0.0/8",
 "169.254.0.0/16","172.16.0.0/12","192.0.0.0/24",
 "192.0.2.0/24","192.88.99.0/24","192.168.0.0/16",
 "198.18.0.0/15","198.51.100.0/24","203.0.113.0/24",
 "224.0.0.0/4","240.0.0.0/4",
)
# Browsing + outbound DNS only. Explicit RETURN preserves Docker routing
# policy/NAT; it does NOT grant a global firewall ACCEPT.
ALLOWED_PORTS=(("tcp","80"),("tcp","443"),("tcp","53"),("udp","53"),("udp","443"))
JUMP=("-i",BRIDGE,"-j",CHAIN)
HOST_DROP=("-i",BRIDGE,"-j","DROP")
# Even with Docker EnableIPv6=false, protect against link-local IPv6 packets
# on a bridge whose kernel auto-configures IPv6 independently.
V6_DROP=("-i",BRIDGE,"-j","DROP")

def run(*argv:str,checked:bool=True)->str:
    p=subprocess.run(argv,capture_output=True,text=True,timeout=12,check=False)
    if checked and p.returncode!=0:
        raise RuntimeError("kernel_policy_command_failed")
    return p.stdout.strip() if p.returncode==0 else ""

def ipt(*args:str,checked:bool=True)->str:
    return run("iptables","-w","3",*args,checked=checked)

def present(*args:str)->bool:
    try:
        p=subprocess.run(("iptables","-w","3","-C",*args),
                         capture_output=True,timeout=8,check=False)
        return p.returncode==0
    except (OSError,subprocess.TimeoutExpired):
        return False

def v6ipt(*args:str,checked:bool=True)->str:
    return run("ip6tables","-w","3",*args,checked=checked)

def v6present(*args:str)->bool:
    try:
        p=subprocess.run(("ip6tables","-w","3","-C",*args),
                         capture_output=True,timeout=8,check=False)
        return p.returncode==0
    except (OSError,subprocess.TimeoutExpired):
        return False

def v6_first_rule(chain:str)->str:
    rules=[line.strip() for line in v6ipt("-S",chain).splitlines()
           if line.strip().startswith("-A ")]
    return rules[0] if rules else ""

def network_record()->dict:
    raw=run("docker","network","inspect",NETWORK)
    info=json.loads(raw)
    if not isinstance(info,list) or len(info)!=1 or not isinstance(info[0],dict):
        raise RuntimeError("network_identity_unverified")
    row=info[0]
    options=row.get("Options") or {}
    labels=row.get("Labels") or {}
    ipam=(row.get("IPAM") or {}).get("Config") or []
    if (row.get("Name")!=NETWORK or row.get("Driver")!="bridge"
        or row.get("Internal") is not False or row.get("EnableIPv6") is not False
        or options.get("com.docker.network.bridge.name")!=BRIDGE
        or options.get("com.docker.network.bridge.enable_icc")!="false"
        or labels.get(LABEL)!=LABEL_VALUE
        or not isinstance(ipam,list) or len(ipam)!=1
        or not ipam[0].get("Gateway") or not ipam[0].get("Subnet")):
        raise RuntimeError("network_identity_unverified")
    return row

def docker_iptables_backend()->bool:
    # Native nftables does not use DOCKER-USER as an enforcement point.
    # The nft executable is optional on hosts whose Docker is using
    # iptables-nft. Still reject an actual native nftables Docker table.
    try:
        native_nft=run("nft","list","table","ip","docker-bridges",checked=False)
    except (OSError,subprocess.TimeoutExpired):
        native_nft=""
    if native_nft:
        return False
    cfg="/etc/docker/daemon.json"
    if os.path.isfile(cfg):
        try:
            with open(cfg,encoding="utf-8") as handle:
                setting=json.load(handle)
            if setting.get("firewall-backend")=="nftables":
                return False
            if setting.get("iptables") is False:
                return False
        except (ValueError,OSError,TypeError):
            return False
    # DOCKER-USER must be the FIRST forwarded rule. An earlier ACCEPT
    # on FORWARD bypasses all our scoped policy despite -C succeeding.
    return bool(ipt("-S","DOCKER-USER",checked=False)
                and present("FORWARD","-j","DOCKER-USER")
                and first_rule("FORWARD")=="-A FORWARD -j DOCKER-USER")

def expected()->list[tuple[str,...]]:
    return (
        [("-d",cidr,"-j","DROP") for cidr in BOGONS]
        +[("-p",protocol,"--dport",port,"-j","RETURN")
          for protocol,port in ALLOWED_PORTS]
        +[("-j","DROP")]
    )

def first_rule(chain:str)->str:
    rules=[line.strip() for line in ipt("-S",chain).splitlines()
           if line.strip().startswith("-A ")]
    return rules[0] if rules else ""

def policy_rules()->list[str]:
    return [line.strip() for line in ipt("-S",CHAIN).splitlines()
            if line.strip().startswith("-A ")]

def assert_policy()->None:
    # Chain count + -C each rule prevent unknown user-provided rules.
    lines=policy_rules()
    if len(lines)!=len(expected()):
        raise RuntimeError("firewall_rule_count_drift")
    for rule in expected():
        if not present(CHAIN,*rule):
            raise RuntimeError("firewall_rule_missing")
    drop_count=len(BOGONS)
    if (not all("-j DROP" in line for line in lines[:drop_count])
        or not all("-j RETURN" in line for line in
                   lines[drop_count:drop_count+len(ALLOWED_PORTS)])
        or "-j DROP" not in lines[-1]):
        raise RuntimeError("firewall_rule_order_drift")

def verify()->None:
    if os.geteuid()!=0:
        raise RuntimeError("root_required")
    network_record()
    if not docker_iptables_backend():
        raise RuntimeError("backend_not_iptables")
    if (not v6present("INPUT",*V6_DROP)
        or not v6present("FORWARD",*V6_DROP)
        or v6_first_rule("INPUT")!=f"-A INPUT -i {BRIDGE} -j DROP"
        or v6_first_rule("FORWARD")!=f"-A FORWARD -i {BRIDGE} -j DROP"):
        raise RuntimeError("ipv6_kernel_hooks_missing")
    if (not present("DOCKER-USER",*JUMP)
        or not present("INPUT",*HOST_DROP)
        or first_rule("DOCKER-USER")!=
           f"-A DOCKER-USER -i {BRIDGE} -j {CHAIN}"
        or first_rule("INPUT")!=f"-A INPUT -i {BRIDGE} -j DROP"):
        raise RuntimeError("firewall_hooks_not_first")
    assert_policy()

def ensure()->None:
    if os.geteuid()!=0:
        raise RuntimeError("root_required")
    network_record()
    if not docker_iptables_backend():
        raise RuntimeError("backend_not_iptables")
    if not ipt("-S",CHAIN,checked=False):
        ipt("-N",CHAIN)
        for rule in expected():
            ipt("-A",CHAIN,*rule)
    else:
        assert_policy()
    if not present("DOCKER-USER",*JUMP):
        ipt("-I","DOCKER-USER","1",*JUMP)
    if not present("INPUT",*HOST_DROP):
        ipt("-I","INPUT","1",*HOST_DROP)
    if not v6present("FORWARD",*V6_DROP):
        v6ipt("-I","FORWARD","1",*V6_DROP)
    if not v6present("INPUT",*V6_DROP):
        v6ipt("-I","INPUT","1",*V6_DROP)
    verify()

def remove()->None:
    if os.geteuid()!=0:
        raise RuntimeError("root_required")
    # Cleanup is restricted to one uniquely named chain and bridge. Never
    # flush other firewall chains or touch DROP/ACCEPT default policies.
    if present("DOCKER-USER",*JUMP):
        ipt("-D","DOCKER-USER",*JUMP)
    if present("INPUT",*HOST_DROP):
        ipt("-D","INPUT",*HOST_DROP)
    if v6present("INPUT",*V6_DROP):
        v6ipt("-D","INPUT",*V6_DROP)
    if v6present("FORWARD",*V6_DROP):
        v6ipt("-D","FORWARD",*V6_DROP)
    if ipt("-S",CHAIN,checked=False):
        # No third-party/unrecognised rules may be removed.
        lines=policy_rules()
        for line in lines:
            if not (line.startswith(f"-A {CHAIN} ")
                    and any(flag in line for flag in
                            ("-j DROP","-j RETURN"))):
                raise RuntimeError("foreign_chain_rule_refused")
        ipt("-F",CHAIN)
        ipt("-X",CHAIN)

def main()->int:
    if len(sys.argv)!=2 or sys.argv[1] not in (
        "verify","ensure","remove","check"):
        print("FIRBO_BROWSER_KERNEL_GUARD_USAGE_ERROR")
        return 2
    try:
        if sys.argv[1]=="verify":
            verify()
        elif sys.argv[1]=="ensure":
            ensure()
        elif sys.argv[1]=="remove":
            remove()
        else:
            network_record()
            if not docker_iptables_backend():
                raise RuntimeError("backend_not_iptables")
            if not v6ipt("-S","INPUT",checked=False) or not v6ipt("-S","FORWARD",checked=False):
                raise RuntimeError("ipv6_firewall_unavailable")
        print("FIRBO_BROWSER_KERNEL_"+sys.argv[1].upper()+"_PASS")
        return 0
    except (RuntimeError,OSError,subprocess.TimeoutExpired,
            json.JSONDecodeError,KeyError,ValueError):
        # Never print raw firewall rules, route data, secrets, IPs or commands.
        print("FIRBO_BROWSER_KERNEL_"+sys.argv[1].upper()+"_BLOCKED")
        return 1

if __name__=="__main__":
    raise SystemExit(main())
