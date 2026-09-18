import copy
import unittest

from configure_call_recovery import make_template


class CallRecoveryTests(unittest.TestCase):
    def test_public_udp_cannot_escape_via_geoip_rule_or_vision(self):
        base = {"outbounds": [{"tag": "direct", "protocol": "freedom"}],
                "inbounds": [{"sniffing": {"enabled": True, "routeOnly": False}}]}
        routing = {"rules": [
            {"__name__": "Локальные сервисы напрямую", "type": "field",
             "domain": ["domain:subscription.example"], "outboundTag": "direct"},
            {"type": "field", "ip": ["geoip:ru"], "outboundTag": "direct"},
            {"type": "field", "network": "tcp,udp", "outboundTag": "proxy"}]}
        original = copy.deepcopy((base, routing))
        for reality in (True, False):
            config = make_template(base, routing, "test-backup", reality)
            rules = config["routing"]["rules"]
            self.assertEqual(rules[0]["outboundTag"], "direct")
            self.assertEqual(rules[1]["ip"], ["geoip:private"])
            self.assertEqual(rules[2]["network"], "udp")
            self.assertEqual(rules[2].get("outboundTag"), "backup" if reality else None)
            self.assertEqual(rules[-1]["balancerTag"], "resilient")
            self.assertEqual(config["routing"]["balancers"][0]["fallbackTag"], "backup")
            self.assertTrue(config["inbounds"][0]["sniffing"]["routeOnly"])
            self.assertEqual(config["remnawave"]["injectHosts"][0]["selector"]["values"], ["test-backup"])
        self.assertEqual((base, routing), original)


if __name__ == "__main__":
    unittest.main()
