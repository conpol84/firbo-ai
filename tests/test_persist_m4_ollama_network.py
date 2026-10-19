"""Offline regressions for the exact, existing M4 Ollama Docker network.

No Docker, Hostinger, API provider or production filesystem touched.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

TARGET=Path(__file__).resolve().parents[1]/"scripts"/"persist_m4_ollama_network.py"
spec=importlib.util.spec_from_file_location("m4_network",TARGET)
assert spec and spec.loader
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
network="firbo-local-20261004t015324z-iu1u23xn"


class PersistM4NetworkTests(unittest.TestCase):
    def test_patch_keeps_all_existing_keys_and_services(self):
        before='''services:
  firbo-api:
    environment:
      FIRBO_OLLAMA_EMBED_URL: http://firbo-ollama:11434/api/embed
  unrelated-worker:
    image: busybox

networks:
  audit:
    external: true
    name: existing-audit
'''
        candidate=module.patch_memory_overlay(before,network)
        self.assertIn('      - default\n',candidate)
        self.assertIn('      - firbo_ollama_external\n',candidate)
        self.assertIn('    name: '+network,candidate)
        self.assertIn('  unrelated-worker:\n    image: busybox\n',candidate)
        self.assertIn('  audit:\n    external: true\n    name: existing-audit',candidate)
        self.assertIn('FIRBO_OLLAMA_EMBED_URL',candidate)

    def test_patch_works_when_overlay_has_no_top_level_networks(self):
        original='services:\n  firbo-api:\n    environment:\n      MEMORY: enabled\n'
        proposed=module.patch_memory_overlay(original,network)
        self.assertIn('networks:\n  firbo_ollama_external:',proposed)
        self.assertIn('  firbo-api:\n    networks:\n',proposed)

    def test_refuses_ambiguous_overlay_and_duplicate_network(self):
        for source in [
            'services:\n  worker:\n    image: busybox\n',
            'services:\n  firbo-api:\n    networks:\n      - default\n',
            'services:\n  firbo-api:\n    network_mode: host\n',
            'services:\n  firbo-api:\n    environment:\n      XX: firbo_ollama_external\n',
            'services:\n  firbo-api:\nservices:\n  firbo-api:\n',
        ]:
            with self.subTest(source=source):
                with self.assertRaises(module.Blocked):
                    module.patch_memory_overlay(source,network)
        with self.assertRaises(module.Blocked):
            module.patch_memory_overlay('services:\n  firbo-api:\n', 'hostinger_default')

    def test_compose_cli_normalizes_external_network_fields(self):
        """Compose JSON may omit redundant external:true or emit empty defaults."""
        base={
            "name":"hostinger",
            "services":{
                "firbo-api":{"networks":{"default":None}},
                "redis":{"networks":{"default":None}},
            },
            "networks":{"default":{"name":"hostinger_default"}},
        }
        import copy
        for representation in (
            {"name":network},
            {"name":network,"external":True},
            {"name":network,"external":True,"labels":{},"ipam":{}},
            {"name":network,"external":True,"attachable":False,"driver":None},
        ):
            with self.subTest(representation=representation):
                result=copy.deepcopy(base)
                result["services"]["firbo-api"]["networks"]["firbo_ollama_external"]=None
                result["networks"]["firbo_ollama_external"]=representation
                module.verify_only_network_change(base,result,network)

    def test_rejects_non_external_or_reconfigured_network(self):
        import copy
        base={
            "services":{"firbo-api":{"networks":{"default":None}}},
            "networks":{"default":{"name":"hostinger_default"}},
        }
        for forbidden in (
            {"name":network,"external":False},
            {"name":"different_network","external":True},
            {"name":network,"external":True,"driver":"bridge"},
            {"name":network,"external":True,"labels":{"owner":"tampered"}},
            {"name":network,"external":True,"ipam":{"driver":"default"}},
            {"name":network,"external":True,"unknown":"unexpected"},
        ):
            with self.subTest(forbidden=forbidden):
                candidate=copy.deepcopy(base)
                candidate["services"]["firbo-api"]["networks"]["firbo_ollama_external"]=None
                candidate["networks"]["firbo_ollama_external"]=forbidden
                with self.assertRaises(module.Blocked):
                    module.verify_only_network_change(base,candidate,network)

    def test_semantic_diff_only_permits_exact_new_network(self):
        before={
            "name":"hostinger",
            "services":{
                "firbo-api":{"networks":{"default":None},"environment":{"SAFE":"unchanged"}},
                "omniroute":{"networks":{"default":None}},
            },
            "networks":{"default":{"name":"hostinger_default"}},
        }
        after={
            "name":"hostinger",
            "services":{
                "firbo-api":{"networks":{"default":None,"firbo_ollama_external":None},
                             "environment":{"SAFE":"unchanged"}},
                "omniroute":{"networks":{"default":None}},
            },
            "networks":{"default":{"name":"hostinger_default"},
                        "firbo_ollama_external":{"external":True,"name":network}},
        }
        module.verify_only_network_change(before,after,network)
        self.assertNotIn("firbo_ollama_external",before["networks"])
        for offender in [
            lambda o: o["services"]["omniroute"].update({"environment":{"SECRET":"changed"}}),
            lambda o: o["services"]["firbo-api"]["networks"].pop("default"),
            lambda o: o["services"]["firbo-api"].update({"ports":["8080:8080"]}),
            lambda o: o["networks"]["firbo_ollama_external"].update({"name":"unexpected"}),
        ]:
            import copy
            modified=copy.deepcopy(after)
            offender(modified)
            with self.assertRaises(module.Blocked):
                module.verify_only_network_change(before,modified,network)


if __name__=="__main__":
    unittest.main()
