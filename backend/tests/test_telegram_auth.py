import hashlib
import hmac
import json
import sys
import unittest
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vpn_platform.security.telegram import TelegramAuthError, TelegramInitDataVerifier

TOKEN = "123456:unit-test-token"  # noqa: S105 -- deterministic fixture, not a credential
NOW = 1_750_000_000


def signed_init_data(**overrides):
    values = {
        "auth_date": str(NOW),
        "query_id": "AAE-test-query",
        "signature": "telegram-ed25519-signature",
        "user": json.dumps(
            {
                "id": 42,
                "first_name": "Ada",
                "last_name": "Lovelace",
                "username": "ada",
                "language_code": "ru",
            },
            separators=(",", ":"),
        ),
    }
    values.update(overrides)
    check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


class TelegramInitDataVerifierTests(unittest.TestCase):
    def setUp(self):
        self.verifier = TelegramInitDataVerifier(TOKEN, max_age_seconds=300)

    def test_accepts_valid_signed_payload(self):
        identity = self.verifier.verify(signed_init_data(), now=NOW + 10)
        self.assertEqual(identity.telegram_id, 42)
        self.assertEqual(identity.first_name, "Ada")
        self.assertEqual(identity.username, "ada")

    def test_signature_field_is_covered_by_bot_token_hash(self):
        payload = signed_init_data().replace(
            "telegram-ed25519-signature",
            "tampered-ed25519-signature",
        )
        with self.assertRaisesRegex(TelegramAuthError, "signature"):
            self.verifier.verify(payload, now=NOW)

    def test_rejects_tampered_user(self):
        payload = signed_init_data().replace("%22id%22%3A42", "%22id%22%3A43")
        with self.assertRaisesRegex(TelegramAuthError, "signature"):
            self.verifier.verify(payload, now=NOW)

    def test_rejects_expired_payload(self):
        with self.assertRaisesRegex(TelegramAuthError, "expired"):
            self.verifier.verify(signed_init_data(), now=NOW + 301)

    def test_rejects_far_future_payload(self):
        with self.assertRaisesRegex(TelegramAuthError, "future"):
            self.verifier.verify(signed_init_data(), now=NOW - 31)

    def test_rejects_duplicate_fields(self):
        payload = f"{signed_init_data()}&auth_date={NOW}"
        with self.assertRaisesRegex(TelegramAuthError, "duplicate"):
            self.verifier.verify(payload, now=NOW)

    def test_rejects_non_object_user(self):
        with self.assertRaisesRegex(TelegramAuthError, "object"):
            self.verifier.verify(signed_init_data(user="[]"), now=NOW)


if __name__ == "__main__":
    unittest.main()
