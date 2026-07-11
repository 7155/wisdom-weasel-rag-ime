from __future__ import annotations

import unittest

from rag_ime.foreground_privacy import assess_foreground_write, storage_receipt


class ForegroundPrivacyTests(unittest.TestCase):
    def test_missing_and_invalid_dispositions_fail_closed(self) -> None:
        missing = assess_foreground_write({})
        invalid = assess_foreground_write({"privacyDisposition": "probably-safe"})

        self.assertEqual(missing["disposition"], "unknown")
        self.assertEqual(missing["reason"], "missing_privacy_disposition")
        self.assertFalse(missing["storeAllowed"])
        self.assertEqual(invalid["disposition"], "unknown")
        self.assertEqual(invalid["reason"], "invalid_privacy_disposition")
        self.assertEqual(storage_receipt(missing, stored=False)["outcome"], "no_store")

    def test_explicit_allowed_is_required_for_storage(self) -> None:
        assessment = assess_foreground_write(
            {"privacyDisposition": "allowed", "app": "com.apple.TextEdit"}
        )

        self.assertEqual(assessment["disposition"], "allowed")
        self.assertTrue(assessment["storeAllowed"])

    def test_secure_flags_override_explicit_allowed(self) -> None:
        assessment = assess_foreground_write(
            {"privacyDisposition": "allowed", "foregroundText": {"secureInput": True}}
        )

        self.assertEqual(assessment["disposition"], "sensitive")
        self.assertEqual(assessment["reason"], "sensitive_foreground_flag")
        self.assertFalse(assessment["storeAllowed"])

        metadata = assess_foreground_write(
            {"privacyDisposition": "allowed", "rimeContext": {"fieldType": "current-password"}}
        )
        self.assertEqual(metadata["disposition"], "sensitive")
        self.assertEqual(metadata["reason"], "sensitive_foreground_flag")

    def test_sensitive_app_denylist_overrides_explicit_allowed(self) -> None:
        cases = (
            {"app": "com.1password.1password"},
            {"frontAppBundleId": "com.example.mobilebank"},
            {"foregroundText": {"bundleId": "org.example.bitwarden"}},
            {"rimeContext": {"frontmostApp": "Safari Private Browsing"}},
            {"app": "Microsoft Edge InPrivate"},
        )
        for app_fields in cases:
            with self.subTest(app_fields=app_fields):
                assessment = assess_foreground_write(
                    {"privacyDisposition": "allowed", **app_fields}
                )
                self.assertEqual(assessment["disposition"], "sensitive")
                self.assertEqual(assessment["reason"], "sensitive_app_denylist")
                self.assertFalse(assessment["storeAllowed"])


if __name__ == "__main__":
    unittest.main()
