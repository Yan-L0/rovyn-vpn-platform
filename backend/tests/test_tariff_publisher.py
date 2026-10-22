import importlib.util
from pathlib import Path


def load_publisher():
    path = Path(__file__).resolve().parents[2] / "infra" / "publish_tariff_policy.py"
    spec = importlib.util.spec_from_file_location("tariff_publisher", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_device_credentials_share_one_business_policy():
    publisher = load_publisher()
    subscriptions = [
        {
            "id": "paid",
            "quota": 25,
            "policy": {"mbps": 70},
            "providers": ["parent", "phone", "revoked", "tv"],
        }
    ]
    users = [
        {"uuid": value, "t_id": index, "username": "dev_" + value}
        for index, value in enumerate(["parent", "phone", "revoked", "tv"], start=1)
    ]
    doc = publisher.document(subscriptions, users)
    assert doc["groups"] == [
        {
            "id": "paid:initial",
            "emails": ["1", "2", "3", "4"],
            "mbps": 70,
            "quota": 25,
            "fup": False,
        }
    ]


def test_pending_creation_never_receives_unlimited_legacy_policy():
    publisher = load_publisher()
    users = [
        {"uuid": "pending", "t_id": 1, "username": "dev_new"},
        {"uuid": "diagnostic", "t_id": 2, "username": "accept_temp"},
        {"uuid": "prepaid", "t_id": 3, "username": "vpn_old"},
    ]
    subscriptions = [{"id": "old", "quota": 0, "policy": {}, "providers": ["prepaid"]}]
    groups = publisher.document(subscriptions, users)["groups"]
    assert {email for group in groups for email in group["emails"]} == {"2", "3"}


def test_renewal_epoch_changes_quota_identity_but_device_reconnect_does_not():
    publisher = load_publisher()
    users = [{"uuid": "phone", "t_id": 1, "username": "dev_phone"}]
    sub = {"id": "paid", "quota": 25, "policy": {"mbps": 70}, "providers": ["phone"]}
    first = publisher.document([sub], users)
    assert publisher.document([sub], users) == first
    sub["policy"]["epoch"] = "renewal"
    assert publisher.document([sub], users)["groups"][0]["id"] != first["groups"][0]["id"]
