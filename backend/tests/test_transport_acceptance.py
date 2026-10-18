"""Check the acceptance verifier without API calls or external UDP traffic."""
import importlib.util
import struct
from pathlib import Path

import pytest

source = Path(__file__).resolve().parents[2] / "infra" / "accept_device_isolation.py"
spec = importlib.util.spec_from_file_location("transport_acceptance", source)
assert spec is not None and spec.loader is not None
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


class FakeUDP:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.sent = []

    def sendto(self, packet, target):
        self.sent.append(packet)

    def recv(self, size):
        reply = next(self.replies)
        if reply == "timeout":
            raise TimeoutError()
        transaction = self.sent[-1][-12:]
        if reply == "wrong":
            transaction = bytes([transaction[0] ^ 1]) + transaction[1:]
        header = b"\x00\x00\x00\x01" + b"\x00" * 6
        return header + struct.pack("!HHI", 0x101, 0, 0x2112A442) + transaction


@pytest.mark.parametrize("first", ["timeout", "wrong"])
def test_udp_probe_retries_and_requires_its_own_transaction(first):
    probe = object.__new__(acceptance.DatagramProbe)
    probe.target = ("127.0.0.1", 1)
    probe.udp = FakeUDP([first, "valid"])
    assert probe.probe() is True
    assert len(probe.udp.sent) == 2
    assert probe.udp.sent[0] == probe.udp.sent[1]


def test_unresponsive_revoked_path_still_fails_all_retries():
    probe = object.__new__(acceptance.DatagramProbe)
    probe.target = ("127.0.0.1", 1)
    probe.udp = FakeUDP(["timeout"] * 3)
    assert probe.probe() is False
    assert len(probe.udp.sent) == 3
