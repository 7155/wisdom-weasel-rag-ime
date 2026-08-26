from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.landing_forms import LandingFormService


class LandingFormServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        product = Path(__file__).resolve().parents[1] / "rag_ime"
        self.service = LandingFormService(
            state_root=root / "forms",
            catalog_path=product / "form_catalog.json",
            product_root=product,
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_catalog_lists_bundled_knowledge_qa(self) -> None:
        catalog = self.service.catalog()
        self.assertTrue(catalog["ok"])
        ids = [item["id"] for item in catalog["items"]]
        self.assertIn("knowledge-qa", ids)
        entry = next(item for item in catalog["items"] if item["id"] == "knowledge-qa")
        self.assertTrue(entry["actionable"])
        self.assertEqual(entry["installState"], "available")

    def test_validate_preview_apply_activate_and_rollback(self) -> None:
        validation = self.service.validate({"catalogId": "knowledge-qa"})
        self.assertTrue(validation["ok"])
        self.assertEqual(validation["form"]["id"], "knowledge-qa")
        self.assertTrue(validation["validationToken"])

        install_preview = self.service.preview(
            {"action": "install", "validationToken": validation["validationToken"]}
        )
        self.assertEqual(install_preview["requiredConfirm"], "apply")
        install_receipt = self.service.apply(
            {
                "previewToken": install_preview["previewToken"],
                "payloadSha256": install_preview["payloadSha256"],
                "confirmText": "apply",
            }
        )
        self.assertEqual(install_receipt["receipt"]["action"], "install")
        self.assertIsNone(self.service.active()["form"])

        activate_preview = self.service.preview(
            {"action": "activate", "formId": "knowledge-qa", "version": "1.0.0"}
        )
        activate_receipt = self.service.apply(
            {
                "previewToken": activate_preview["previewToken"],
                "payloadSha256": activate_preview["payloadSha256"],
                "confirmText": "apply",
            }
        )
        self.assertEqual(activate_receipt["receipt"]["action"], "activate")
        active = self.service.active()["form"]
        assert active is not None
        self.assertEqual(active["id"], "knowledge-qa")
        self.assertEqual(active["dockAppIds"], ["agent", "knowledge", "files", "app-center"])
        self.assertEqual(active["defaultLandingAppId"], "knowledge")

        deactivate_preview = self.service.preview({"action": "deactivate"})
        self.service.apply(
            {
                "previewToken": deactivate_preview["previewToken"],
                "payloadSha256": deactivate_preview["payloadSha256"],
                "confirmText": "apply",
            }
        )
        self.assertIsNone(self.service.active()["form"])

        # Re-activate then rollback to empty previous (deactivate left previous pointer).
        activate_preview = self.service.preview(
            {"action": "activate", "formId": "knowledge-qa", "version": "1.0.0"}
        )
        self.service.apply(
            {
                "previewToken": activate_preview["previewToken"],
                "payloadSha256": activate_preview["payloadSha256"],
                "confirmText": "apply",
            }
        )
        self.assertEqual(self.service.active()["form"]["id"], "knowledge-qa")

    def test_apply_rejects_wrong_confirm_text(self) -> None:
        validation = self.service.validate({"catalogId": "knowledge-qa"})
        preview = self.service.preview(
            {"action": "install", "validationToken": validation["validationToken"]}
        )
        with self.assertRaises(ValueError):
            self.service.apply(
                {
                    "previewToken": preview["previewToken"],
                    "payloadSha256": preview["payloadSha256"],
                    "confirmText": "yes",
                }
            )

    def test_invalid_dock_app_fails_validation(self) -> None:
        bad = Path(self._tmp.name) / "bad-form"
        bad.mkdir()
        (bad / "form.json").write_text(
            """
            {
              "schemaVersion": "rag-ime.landing-form.v1",
              "id": "bad",
              "displayName": "Bad",
              "version": "1.0.0",
              "dockAppIds": ["not-an-app"],
              "launchpadAppIds": ["agent"],
              "defaultLandingAppId": "agent",
              "defaultPersona": {"roleId": "companion-present-v1", "version": "1"},
              "knowledgeBindings": [],
              "policyPreset": "default"
            }
            """.strip(),
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            self.service.validate({"sourcePath": str(bad)})


if __name__ == "__main__":
    unittest.main()
