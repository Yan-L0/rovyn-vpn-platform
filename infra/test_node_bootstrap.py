import copy
import unittest
from unittest.mock import patch

from configure_node_bootstrap import MANAGED_TAGS, apply_updates, plan_updates


class NodeBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.hosts = [{"uuid": str(i), "tags": [tag], "address": "node.example",
                       "sni": "tls.example", "overrideSniFromAddress": False,
                       "keepSniBlank": False, "port": 443}
                      for i, tag in enumerate(sorted(MANAGED_TAGS))]

    def test_plan_preserves_tls_and_ignores_unmanaged_hosts(self):
        self.hosts.append({"uuid": "other", "tags": [], "address": "other.example"})
        before = copy.deepcopy(self.hosts)
        planned = plan_updates(self.hosts, "node.example", "8.8.8.8")
        self.assertEqual(len(planned), 3)
        self.assertTrue(all(h["sni"] == "tls.example" for h in planned))
        self.assertEqual(self.hosts, before)

    def test_refuses_unsafe_tls_or_unexpected_address(self):
        for field, value in [("sni", ""), ("overrideSniFromAddress", True),
                             ("keepSniBlank", True), ("address", "other.example")]:
            with self.subTest(field=field):
                hosts = copy.deepcopy(self.hosts)
                hosts[0][field] = value
                with self.assertRaises(ValueError):
                    plan_updates(hosts, "node.example", "8.8.8.8")

    def test_refuses_partial_or_duplicate_scope(self):
        for hosts in (self.hosts[:2], self.hosts + [self.hosts[0]]):
            with self.assertRaises(ValueError):
                plan_updates(hosts, "node.example", "8.8.8.8")
        with self.assertRaises(ValueError):
            plan_updates(self.hosts, "node.example", "127.0.0.1")

    def test_failed_update_restores_attempted_hosts(self):
        originals = plan_updates(self.hosts, "node.example", "8.8.8.8")
        with patch("configure_node_bootstrap.api") as api:
            api.side_effect = [None, TimeoutError(), None, None]
            with self.assertRaises(TimeoutError):
                apply_updates("secret", originals, "8.8.8.8")
            payloads = [call.args[3] for call in api.call_args_list]
        self.assertEqual([p["address"] for p in payloads],
                         ["8.8.8.8", "8.8.8.8", "node.example", "node.example"])
        self.assertTrue(all(set(p) == {"uuid", "address"} for p in payloads))

    def test_rollback_attempts_every_host_even_after_error(self):
        originals = plan_updates(self.hosts, "node.example", "8.8.8.8")
        with patch("configure_node_bootstrap.api") as api:
            api.side_effect = [None, TimeoutError(), TimeoutError(), None]
            with self.assertRaisesRegex(RuntimeError, "rollback incomplete"):
                apply_updates("secret", originals, "8.8.8.8")
            self.assertEqual(api.call_count, 4)


if __name__ == "__main__":
    unittest.main()
