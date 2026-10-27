"""Offline FIRBO Browser OS egress guards. No real Docker/network/firewall writes."""
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
GUARD=ROOT/"scripts/browser-kernel-guard.py"
INSTALLER=ROOT/"scripts/deploy-browser-kernel-egress.py"

def imported(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

fw=imported(GUARD,"firbo_browser_os_kernel_guard_test")
release=imported(INSTALLER,"firbo_browser_os_release_test")
SYNTHETIC={
 "Name":fw.NETWORK,"Driver":"bridge","Internal":False,"EnableIPv6":False,
 "Options":{
  "com.docker.network.bridge.name":fw.BRIDGE,
  "com.docker.network.bridge.enable_icc":"false",
 },
 "Labels":{fw.LABEL:fw.LABEL_VALUE},
 "IPAM":{"Config":[{"Gateway":"172.29.0.1","Subnet":"172.29.0.0/16"}]},
}

class GuardTests(unittest.TestCase):
    def test_all_kernel_paths_are_scoped_to_new_dedicated_interface(self):
        self.assertNotEqual(fw.BRIDGE,"docker0")
        self.assertTrue(len(fw.BRIDGE)<=15)
        self.assertEqual(fw.JUMP,("-i",fw.BRIDGE,"-j",fw.CHAIN))
        self.assertEqual(fw.HOST_DROP,("-i",fw.BRIDGE,"-j","DROP"))
        self.assertEqual(fw.V6_DROP,("-i",fw.BRIDGE,"-j","DROP"))
        self.assertNotEqual(fw.NETWORK,"bridge")
        self.assertLess(len(fw.CHAIN),28)
        src=GUARD.read_text()
        for forbidden in ("iptables -P","iptables -F INPUT",
                          "iptables -F DOCKER-USER","docker network prune",
                          "docker system prune","docker compose down",
                          "iptables-restore","nft add rule","--network host"):
            self.assertNotIn(forbidden,src)
        self.assertIn('ipt("-I","DOCKER-USER","1",*JUMP)',src)
        self.assertIn('ipt("-I","INPUT","1",*HOST_DROP)',src)
        self.assertIn('v6ipt("-I","INPUT","1",*V6_DROP)',src)
        self.assertIn('v6ipt("-I","FORWARD","1",*V6_DROP)',src)

    def test_bogon_drop_rules_precede_all_approved_public_ports(self):
        rules=fw.expected()
        self.assertEqual(len(rules),len(fw.BOGONS)+len(fw.ALLOWED_PORTS)+1)
        for cidr in ("10.0.0.0/8","172.16.0.0/12","192.168.0.0/16",
                     "169.254.0.0/16","127.0.0.0/8","100.64.0.0/10",
                     "198.18.0.0/15","203.0.113.0/24"):
            self.assertIn(("-d",cidr,"-j","DROP"),rules)
        self.assertTrue(all(rule[-2:]==("-j","DROP")
            for rule in rules[:len(fw.BOGONS)]))
        self.assertTrue(all(rule[-2:]==("-j","RETURN")
            for rule in rules[len(fw.BOGONS):-1]))
        self.assertEqual(rules[-1],("-j","DROP"))
        self.assertEqual(fw.ALLOWED_PORTS,(
            ("tcp","80"),("tcp","443"),("tcp","53"),
            ("udp","53"),("udp","443"),
        ))

    def test_network_identity_rejects_foreign_bridge_icc_and_ipv6(self):
        for key,value in [
          ("Name","other-product"),("Driver","overlay"),
          ("EnableIPv6",True),("Internal",True),
        ]:
            bad=json.loads(json.dumps(SYNTHETIC));bad[key]=value
            with patch.object(fw,"run",return_value=json.dumps([bad])):
                with self.assertRaises(RuntimeError):fw.network_record()
        for key,value in [
            ("com.docker.network.bridge.name","docker0"),
            ("com.docker.network.bridge.enable_icc","true"),
        ]:
            bad=json.loads(json.dumps(SYNTHETIC));bad["Options"][key]=value
            with patch.object(fw,"run",return_value=json.dumps([bad])):
                with self.assertRaises(RuntimeError):fw.network_record()
        bad=json.loads(json.dumps(SYNTHETIC))
        bad["Labels"][fw.LABEL]="another-vendor"
        with patch.object(fw,"run",return_value=json.dumps([bad])):
            with self.assertRaises(RuntimeError):fw.network_record()
        with patch.object(fw,"run",return_value=json.dumps([SYNTHETIC])):
            self.assertEqual(fw.network_record()["Name"],fw.NETWORK)

    def test_fw_verify_never_accepts_missing_or_nonfirst_kernel_jumps(self):
        with patch.object(fw.os,"geteuid",return_value=0),\
             patch.object(fw,"network_record",return_value=SYNTHETIC),\
             patch.object(fw,"docker_iptables_backend",return_value=True),\
             patch.object(fw,"assert_policy") as verify_rules,\
             patch.object(fw,"v6present",return_value=True),\
             patch.object(fw,"v6_first_rule",side_effect=lambda chain:
                f"-A {chain} -i {fw.BRIDGE} -j DROP"),\
             patch.object(fw,"present",return_value=True),\
             patch.object(fw,"first_rule",side_effect=lambda chain:{
               "DOCKER-USER":"-A DOCKER-USER -j RETURN",
               "INPUT":f"-A INPUT -i {fw.BRIDGE} -j DROP"
             }[chain]):
            with self.assertRaises(RuntimeError):fw.verify()
            verify_rules.assert_not_called()
        with patch.object(fw.os,"geteuid",return_value=0),\
             patch.object(fw,"network_record",return_value=SYNTHETIC),\
             patch.object(fw,"docker_iptables_backend",return_value=True),\
             patch.object(fw,"assert_policy"),\
             patch.object(fw,"v6present",return_value=True),\
             patch.object(fw,"v6_first_rule",side_effect=lambda chain:
                f"-A {chain} -i {fw.BRIDGE} -j DROP"),\
             patch.object(fw,"present",return_value=True),\
             patch.object(fw,"first_rule",side_effect=lambda chain:{
               "DOCKER-USER":f"-A DOCKER-USER -i {fw.BRIDGE} -j {fw.CHAIN}",
               "INPUT":f"-A INPUT -i {fw.BRIDGE} -j DROP"
             }[chain]):
            fw.verify()

    def test_policy_rejects_extra_and_reordered_rules(self):
        base=[
          f"-A {fw.CHAIN} -d {cidr} -j DROP" for cidr in fw.BOGONS
        ]+[
          f"-A {fw.CHAIN} -p {proto} -m {proto} --dport {port} -j RETURN"
          for proto,port in fw.ALLOWED_PORTS
        ]+[f"-A {fw.CHAIN} -j DROP"]
        with patch.object(fw,"present",return_value=True),\
             patch.object(fw,"policy_rules",return_value=base):
            fw.assert_policy()
        for candidate in [
          base+[f"-A {fw.CHAIN} -j ACCEPT"],
          base[len(fw.BOGONS):]+base[:len(fw.BOGONS)],
          base[:-1]+[f"-A {fw.CHAIN} -j RETURN"],
        ]:
            with patch.object(fw,"present",return_value=True),\
                 patch.object(fw,"policy_rules",return_value=candidate):
                with self.assertRaises(RuntimeError):fw.assert_policy()

    def test_ensure_never_modifies_shared_docker_chains_or_default_policy(self):
        calls=[]
        def ipt(*args,checked=True):
            calls.append(args)
            if args==("-S",fw.CHAIN):return ""
            return ""
        with patch.object(fw.os,"geteuid",return_value=0),\
             patch.object(fw,"network_record",return_value=SYNTHETIC),\
             patch.object(fw,"docker_iptables_backend",return_value=True),\
             patch.object(fw,"ipt",side_effect=ipt),\
             patch.object(fw,"v6ipt",side_effect=lambda *a,**kw: calls.append(("v6",*a))),\
             patch.object(fw,"v6present",return_value=False),\
             patch.object(fw,"present",return_value=False),\
             patch.object(fw,"verify",return_value=None):
            fw.ensure()
        self.assertIn(("-N",fw.CHAIN),calls)
        self.assertIn(("-I","DOCKER-USER","1",*fw.JUMP),calls)
        self.assertIn(("-I","INPUT","1",*fw.HOST_DROP),calls)
        self.assertIn(("v6","-I","INPUT","1",*fw.V6_DROP),calls)
        self.assertIn(("v6","-I","FORWARD","1",*fw.V6_DROP),calls)
        for call in calls:
            if call[:1] in (("-I",),("-A",),("-N",)):
                self.assertTrue(
                    call[1] in (fw.CHAIN,"INPUT","DOCKER-USER"),call
                )
        self.assertFalse(any(call[:2] in [
            ("-F","INPUT"),("-F","DOCKER-USER"),("-P","FORWARD")
        ] for call in calls))

class DeploymentTests(unittest.TestCase):
    def test_existing_root_browser_wrapper_changes_only_single_network_line(self):
        slash=chr(92)
        original=chr(10).join([
          "#!/usr/bin/env bash","set -euo pipefail",
          "exec /usr/bin/docker run --rm -i --init "+slash,
          "  --network bridge "+slash,
          "  --read-only "+slash,
          "  --cap-drop ALL "+slash,
          "  --security-opt no-new-privileges "+slash,
          "  --security-opt seccomp=/root/seccomp.json "+slash,
          "  firbo-browser-mcp:0.2.0",
        ])+chr(10)
        updated=release.patch_wrapper(original)
        self.assertIn("  --network "+fw.NETWORK+" "+slash,updated)
        self.assertNotIn("  --network bridge "+slash,updated)
        self.assertIn(release.GUARD_COMMAND,updated)
        self.assertEqual(updated.count(release.GUARD_COMMAND),1)
        self.assertIn("--security-opt seccomp=/root/seccomp.json",updated)
        with self.assertRaises(RuntimeError):
            release.patch_wrapper(updated)
        with self.assertRaises(RuntimeError):
            release.patch_wrapper("exec /usr/bin/docker run --network bridge")

    def test_non_destructive_check_and_no_unknown_checkout(self):
        s=INSTALLER.read_text()
        self.assertIn("FIRBO_BROWSER_KERNEL_PREFLIGHT_PASS",s)
        self.assertIn("PINNED_IMAGE_POLICY",s)
        self.assertIn("FIRBO_BROWSER_KERNEL_EGRESS_RELEASE_PASS",s)
        self.assertIn("FIRBO_BROWSER_KERNEL_RELEASE_FAILED_ROLLING_BACK",s)
        self.assertIn("FIRBO_BROWSER_KERNEL_ROLLBACK_COMPLETE",s)
        self.assertIn("FIRBO_BROWSER_EGRESS_GUARD_PERSISTENT_ON_OPENJARVIS_START",s)
        self.assertIn("ExecStartPre=+",s)
        self.assertIn("FIRBO_BROWSER_KERNEL_PRIVATE_NETWORK_NEGATIVE_PASS",s)
        for forbidden in (
          "docker system prune","docker compose down",
          "docker network prune","--network host",
          "iptables -P", "iptables -F DOCKER-USER",
          "ufw disable","systemctl stop docker",
          "DROP DATABASE","ALTER TABLE",
        ):
            self.assertNotIn(forbidden,s)
        self.assertIn('if image_policy_hash()!=PINNED_IMAGE_POLICY',s)
        self.assertIn('if STATE.exists() or GUARD_INSTALLED.exists() or DROPIN.exists()',s)
        self.assertIn("MODE_FLAG",s)
        self.assertIn("fw.ensure()",s)
        self.assertIn("fw.verify()",s)
        self.assertIn("socket_negative_probe()",s)
        self.assertIn("accept-browser-direct-read-no-model.py",s)

    def test_owner_only_cutover_does_not_impersonate_owner_confirmation(self):
        self.assertEqual(release.MODE_FLAG,
          "--owner-confirms-no-active-browser-tasks")
        self.assertFalse(any([
          "POST https://" in INSTALLER.read_text(),
          "OPENAI_API_KEY" in INSTALLER.read_text(),
          "SUPABASE_SERVICE_ROLE_KEY" in INSTALLER.read_text()
        ]))

if __name__=="__main__":
    unittest.main()
