#!/usr/bin/env python3
"""FIRBO V1: exact, rollbackable browser-only kernel network release.

Commands:
  --check: read-only preflight, NO changes.
  --apply: owner-confirmed no-active-browser-tasks cutover; backups and
           automatically restores the old working Browser on any failure.
  --rollback: owner-confirmed explicit rollback to the saved old wrapper.

Changes ONLY: one new labelled browser Docker bridge, its own iptables chain +
interface-specific INPUT/DOCKER-USER jumps, Browser root wrapper, ONE OpenJarvis
systemd drop-in and a dedicated root-owned guard executable. Never changes
other containers, global Docker config, default iptables policies, DB,
Caddy, browsers' model providers, passwords, keys, route code or image.

On boot OpenJarvis's ExecStartPre re-ensures the exact policy; BEFORE each
new container session, the wrapper independently verifies every kernel rule.
If Docker changes backend, IPv6 or network/firewall hooks, new Browser
sessions FAIL CLOSED rather than expose an unrestricted container.
"""
from __future__ import annotations

import fcntl
import hashlib
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

import importlib.util
from pathlib import Path
_guard_file=Path(__file__).resolve().with_name("browser-kernel-guard.py")
_spec=importlib.util.spec_from_file_location("firbo_browser_kernel_guard",_guard_file)
assert _spec and _spec.loader
fw=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fw)

ROOT=Path(__file__).resolve().parents[1]
WRAPPER=Path("/usr/local/sbin/firbo-browser-mcp")
SESSION_WRAPPER=Path("/usr/local/sbin/firbo-browser-session-create")
GUARD_INSTALLED=Path("/usr/local/sbin/firbo-browser-kernel-guard")
DROPIN=Path("/etc/systemd/system/openjarvis.service.d/50-firbo-browser-egress.conf")
STATE=Path("/var/lib/firbo-browser-egress-v1/manifest.json")
BACKUP_BASE=Path("/var/backups/firbo-browser-egress-v1")
IMAGE="firbo-browser-mcp:0.2.0"
PINNED_IMAGE_POLICY="a66379f52d9a265e8eb17e76ae5011c035a48876389ccdeb843b9b1741856299"
MODE_FLAG="--owner-confirms-no-active-browser-tasks"
DROPIN_TEXT=(
 "[Unit]\nRequires=docker.service\nAfter=docker.service\n"
 "[Service]\nExecStartPre=+"+str(GUARD_INSTALLED)+" ensure\n"
)
GUARD_COMMAND=(
 str(GUARD_INSTALLED)+" verify >/dev/null || "
 "{ echo FIRBO_BROWSER_KERNEL_EGRESS_NOT_VERIFIED >&2; exit 73; }"
)
BEFORE='  --network bridge \\'
AFTER='  --network '+fw.NETWORK+' \\'

def run(*argv:str,check=True,timeout=20)->str:
    p=subprocess.run(argv,capture_output=True,text=True,timeout=timeout,
                     check=False)
    if check and p.returncode:
        raise RuntimeError("external_preflight_or_acceptance_failed")
    return p.stdout.strip() if p.returncode==0 else ""

def locked()->object:
    path=Path("/run/lock/firbo-browser-route-release.lock")
    fd=os.open(str(path),os.O_RDWR|os.O_CREAT,0o600)
    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    return fd

def image_policy_hash()->str:
    return run("docker","run","--rm","--network","none","--read-only",
               "--entrypoint","sha256sum",IMAGE,
               "/app/network-policy.mjs",timeout=20).split()[0]

def exact_source()->None:
    # Work only on a clean, immutable reviewed checkout: no substitutions
    # from PATH or a mutable external host. The owner command pins full SHA.
    if run("git","-C",str(ROOT),"rev-parse","--show-toplevel")!=str(ROOT):
        raise RuntimeError("unexpected_repository_root")
    remote=run("git","-C",str(ROOT),"config","--get","remote.origin.url")
    if remote not in {
      "https://github.com/conpol84/firbo-ai",
      "https://github.com/conpol84/firbo-ai.git",
      "git@github.com:conpol84/firbo-ai",
      "git@github.com:conpol84/firbo-ai.git",
    }:
        raise RuntimeError("source_repository_mismatch")
    if run("git","-C",str(ROOT),"status","--porcelain"):
        raise RuntimeError("dirty_checkout")
    for path in ("scripts/browser-kernel-guard.py",
                 "scripts/deploy-browser-kernel-egress.py"):
        blob=run("git","-C",str(ROOT),"show","HEAD:"+path)
        if blob+"\n" != (ROOT/path).read_text(encoding="utf8"):
            # Git strips the terminal newline in stdout .strip; strict bytes
            # comparison must account for the expected trailing newline only.
            if blob != (ROOT/path).read_text(encoding="utf8").rstrip("\n"):
                raise RuntimeError("source_file_not_git_pinned")

def before()->str:
    if os.geteuid()!=0:
        raise RuntimeError("root_required")
    exact_source()
    for path in (WRAPPER,SESSION_WRAPPER):
        if not path.is_file() or path.is_symlink():
            raise RuntimeError("root_browser_wrapper_missing")
        st=path.stat()
        if st.st_uid!=0 or (st.st_mode & 0o022):
            raise RuntimeError("wrapper_owner_or_mode_untrusted")
    original=WRAPPER.read_text(encoding="utf-8")
    if original.count(BEFORE)!=1 or AFTER in original:
        raise RuntimeError("wrapper_network_drift")
    if not all(token in original for token in (
        "--read-only","--cap-drop ALL",
        "--security-opt no-new-privileges",
        "--security-opt seccomp=",IMAGE,
    )):
        raise RuntimeError("wrapper_security_flags_drift")
    session=SESSION_WRAPPER.read_text(encoding="utf-8")
    if "--network none" not in session or IMAGE not in session:
        raise RuntimeError("session_factory_drift")
    if STATE.exists() or GUARD_INSTALLED.exists() or DROPIN.exists():
        raise RuntimeError("previous_or_partial_kernel_install_exists")
    if fw.run("docker","network","inspect",fw.NETWORK,checked=False):
        raise RuntimeError("network_name_already_exists")
    if run("systemctl","is-active","openjarvis.service")!="active":
        raise RuntimeError("openjarvis_not_active")
    if not fw.docker_iptables_backend():
        raise RuntimeError("docker_firewall_backend_unreviewed")
    # IPv6 native link-local must also be kernel-filterable before creating
    # any dedicated bridge. Never fall back to IPv4-only enforcement.
    if not fw.v6ipt("-S","INPUT",checked=False) or not fw.v6ipt("-S","FORWARD",checked=False):
        raise RuntimeError("ipv6_firewall_unavailable")
    if fw.v6present("INPUT",*fw.V6_DROP) or fw.v6present("FORWARD",*fw.V6_DROP):
        raise RuntimeError("ipv6_hook_name_conflict")
    if fw.ipt("-S",fw.CHAIN,checked=False):
        raise RuntimeError("old_kernel_chain_conflict")
    if fw.present("DOCKER-USER",*fw.JUMP) or fw.present("INPUT",*fw.HOST_DROP):
        raise RuntimeError("existing_firewall_hook_conflict")
    if image_policy_hash()!=PINNED_IMAGE_POLICY:
        raise RuntimeError("running_image_policy_drift")
    return original

def guard_verify()->None:
    fw.verify()
    if run(str(GUARD_INSTALLED),"verify")!="FIRBO_BROWSER_KERNEL_VERIFY_PASS":
        raise RuntimeError("installed_guard_unverified")

def patch_wrapper(original:str)->str:
    if original.count(BEFORE)!=1 or AFTER in original:
        raise RuntimeError("wrapper_patch_precondition_failed")
    marker="set -euo pipefail\n"
    if original.count(marker)!=1:
        raise RuntimeError("wrapper_entrypoint_unreviewed")
    return original.replace(BEFORE,AFTER,1).replace(
        marker,marker+GUARD_COMMAND+"\n",1
    )

def atomic_file(path:Path,text:str,mode:int)->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+".firbo-staged")
    if temp.exists() or temp.is_symlink():
        raise RuntimeError("staging_file_conflict")
    with open(temp,"x",encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.chown(temp,0,0)
    os.chmod(temp,mode)
    os.replace(temp,path)

def health()->None:
    if run("systemctl","is-active","openjarvis.service")!="active":
        raise RuntimeError("openjarvis_unhealthy")
    # Local-only HTTP without shell, curl, system proxy variables or secrets.
    health=http.client.HTTPConnection("127.0.0.1",8765,timeout=3)
    try:
        health.request("GET","/health")
        resp=health.getresponse()
        if resp.status!=200:
            raise RuntimeError("browser_host_health_unverified")
        resp.read()
    finally:
        health.close()
    check=http.client.HTTPConnection("127.0.0.1",8765,timeout=3)
    try:
        check.request("POST","/v1/firbo/browser",
                      body=b"{}",headers={"Content-Type":"application/json"})
        response=check.getresponse()
        if response.status!=401:
            raise RuntimeError("browser_auth_boundary_missing")
        response.read()
    finally:
        check.close()

def wait_health()->None:
    for _ in range(22):
        try:
            health()
            return
        except (RuntimeError,OSError,urllib.error.URLError,TimeoutError):
            time.sleep(1)
    raise RuntimeError("openjarvis_restarted_but_unhealthy")

def socket_negative_probe()->None:
    network=fw.network_record()
    gateway=network["IPAM"]["Config"][0]["Gateway"]
    # No payload or HTTP traffic to private IPs, just bounded TCP handshakes.
    script=r"""
const {Socket}=require('node:net');
const gateway=process.env.FIRBO_BRIDGE_GATEWAY;
async function blocked(host){
 return new Promise(resolve=>{
  let finished=false;const socket=new Socket();
  const done=(ok)=>{if(finished)return;finished=true;socket.destroy();resolve(ok)};
  socket.setTimeout(1500,()=>done(true));
  socket.once('connect',()=>done(false));
  socket.once('error',err=>done(
   ['ETIMEDOUT','EHOSTUNREACH','ENETUNREACH','EACCES','EPERM'].includes(err.code)
  ));
  socket.connect(65534,host);
 });
}
(async()=>{
 const results=await Promise.all([
  blocked(gateway), blocked('10.255.255.254'),
  blocked('169.254.169.254')
 ]);
 if(results.some(x=>x!==true))process.exit(19);
 const ipv6=await new Promise(resolve=>{
  const s=new Socket();
  let finished=false;
  const done=ok=>{if(finished)return;finished=true;s.destroy();resolve(ok)};
  s.setTimeout(1500,()=>done(false)); // Timeout indicates an IPv6 route exists.
  s.once('connect',()=>done(false));
  s.once('error',err=>done(
   ['ENETUNREACH','EHOSTUNREACH','EAFNOSUPPORT','EADDRNOTAVAIL'].includes(err.code)
  ));
  s.connect(443,'2606:4700:4700::1111');
 });
 if(!ipv6)process.exit(20);
 console.log('FIRBO_BROWSER_KERNEL_PRIVATE_NETWORK_NEGATIVE_PASS');
})().catch(()=>process.exit(21));
"""
    result=run(
        "docker","run","--rm","--network",fw.NETWORK,
        "--read-only","--cap-drop","ALL",
        "--security-opt","no-new-privileges",
        "--memory","192m","--pids-limit","48",
        "-e","FIRBO_BRIDGE_GATEWAY="+gateway,
        "--entrypoint","node",IMAGE,"-e",script,
        timeout=26,
    )
    if "FIRBO_BROWSER_KERNEL_PRIVATE_NETWORK_NEGATIVE_PASS" not in result:
        raise RuntimeError("kernel_negative_probe_unverified")

def restore_state(manifest:dict)->None:
    """Rollback only the files/network/rules CREATED by this installer."""
    backup=Path(manifest["backup_dir"])
    original=backup/"firbo-browser-mcp"
    if original.is_file() and WRAPPER.is_file():
        shutil.copy2(original,WRAPPER)
        os.chown(WRAPPER,0,0)
    if DROPIN.is_file() and DROPIN.read_text()==DROPIN_TEXT:
        DROPIN.unlink()
    run("systemctl","daemon-reload",check=False)
    # Restore old already-accepted browser service while kernel guard is
    # still active; no Browser session can run unrestricted during rollback.
    run("systemctl","restart","openjarvis.service",check=False,timeout=30)
    try:
        fw.remove()
    except (RuntimeError,OSError,subprocess.TimeoutExpired):
        # Preserve restrictive rules rather than touching foreign firewall.
        print("FIRBO_BROWSER_FIREWALL_CLEANUP_NEEDS_REVIEW")
    run("docker","network","rm",fw.NETWORK,check=False)
    if GUARD_INSTALLED.is_file():
        data=GUARD_INSTALLED.read_bytes()
        if data==(ROOT/"scripts/browser-kernel-guard.py").read_bytes():
            GUARD_INSTALLED.unlink()
    # Keep backups/manifest for forensics if cleanup incomplete.
    if not fw.run("docker","network","inspect",fw.NETWORK,checked=False):
        if STATE.is_file():
            STATE.unlink()
        print("FIRBO_BROWSER_KERNEL_ROLLBACK_COMPLETE")

def apply()->None:
    original=before()
    stamp=time.strftime("%Y%m%dT%H%M%SZ",time.gmtime())
    backup=BACKUP_BASE/stamp
    backup.mkdir(parents=True,mode=0o700,exist_ok=False)
    os.chmod(backup,0o700)
    shutil.copy2(WRAPPER,backup/"firbo-browser-mcp")
    os.chmod(backup/"firbo-browser-mcp",0o700)
    STATE.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
    os.chmod(STATE.parent,0o700)
    manifest={"backup_dir":str(backup),"from_mode":"bridge",
              "target_network":fw.NETWORK,
              "source_sha":run("git","-C",str(ROOT),"rev-parse","HEAD")}
    atomic_file(STATE,json.dumps(manifest,sort_keys=True)+"\n",0o600)
    try:
        # NEW dedicated label + interface, not Docker's shared default bridge.
        run("docker","network","create","--driver","bridge",
            "--opt","com.docker.network.bridge.name="+fw.BRIDGE,
            "--opt","com.docker.network.bridge.enable_icc=false",
            "--label",fw.LABEL+"="+fw.LABEL_VALUE,
            fw.NETWORK,timeout=25)
        fw.ensure()
        fw.verify()
        socket_negative_probe()
        atomic_file(GUARD_INSTALLED,
                    (ROOT/"scripts/browser-kernel-guard.py").read_text(),0o755)
        guard_verify()
        new_wrapper=patch_wrapper(original)
        atomic_file(WRAPPER,new_wrapper,0o755)
        atomic_file(DROPIN,DROPIN_TEXT,0o644)
        run("systemctl","daemon-reload")
        run("systemctl","restart","openjarvis.service",timeout=30)
        wait_health()
        guard_verify()
        # The same independent zero-model one-shot Playwright public read,
        # JPEG Frame and exact session CLOSE previously accepted by owner.
        acceptance=run("python3",str(ROOT/"scripts/accept-browser-direct-read-no-model.py"),
                       timeout=120)
        if "FIRBO_BROWSER_DIRECT_READ_NO_MODEL_E2E_PASS" not in acceptance:
            raise RuntimeError("owner_browser_e2e_not_accepted")
        guard_verify()
        print("FIRBO_BROWSER_KERNEL_PRIVATE_NETWORK_NEGATIVE_PASS")
        print("FIRBO_BROWSER_DIRECT_READ_NO_MODEL_E2E_PASS")
        print("FIRBO_BROWSER_KERNEL_EGRESS_RELEASE_PASS")
        print("FIRBO_BROWSER_FIREWALL_BACKUP_SAVED")
        print("FIRBO_BROWSER_EGRESS_GUARD_PERSISTENT_ON_OPENJARVIS_START")
    except (Exception,KeyboardInterrupt):
        print("FIRBO_BROWSER_KERNEL_RELEASE_FAILED_ROLLING_BACK")
        restore_state(manifest)
        raise

def main()->int:
    if len(sys.argv)<2 or sys.argv[1] not in ("--check","--apply","--rollback"):
        print("FIRBO_BROWSER_KERNEL_RELEASE_USAGE_ERROR")
        return 2
    operation=sys.argv[1]
    if operation in ("--apply","--rollback") and (
       len(sys.argv)!=3 or sys.argv[2]!=MODE_FLAG):
        print("FIRBO_BROWSER_OWNER_NO_ACTIVE_TASKS_CONFIRMATION_REQUIRED")
        return 2
    if os.geteuid()!=0:
        print("FIRBO_BROWSER_KERNEL_ROOT_REQUIRED")
        return 2
    fd=None
    try:
        fd=locked()
        if operation=="--check":
            before()
            print("FIRBO_BROWSER_KERNEL_PREFLIGHT_PASS")
            print("FIRBO_BROWSER_KERNEL_ISOLATION_UPGRADE_NEEDED")
        elif operation=="--apply":
            apply()
        else:
            manifest=json.loads(STATE.read_text())
            if manifest.get("target_network")!=fw.NETWORK:
                raise RuntimeError("rollback_manifest_wrong_network")
            restore_state(manifest)
        return 0
    except (RuntimeError,OSError,KeyError,ValueError,
            urllib.error.URLError,subprocess.TimeoutExpired):
        # Do not leak host network configuration, commands or user data.
        print("FIRBO_BROWSER_KERNEL_RELEASE_BLOCKED")
        return 1
    finally:
        if fd is not None:
            os.close(fd)

if __name__=="__main__":
    raise SystemExit(main())
