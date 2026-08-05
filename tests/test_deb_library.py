from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "sync_deb_library.py"
SPEC = importlib.util.spec_from_file_location("sync_deb_library", MODULE_PATH)
assert SPEC and SPEC.loader
library = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(library)


class DebLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.direct_source = {
            "id": "open",
            "name": "Open Repo",
            "baseUrl": "https://repo.example/",
            "homepage": "https://repo.example/",
            "policy": "direct",
            "mirrorPolicy": "license-only",
        }

    def test_parse_control_stanzas_handles_continuations(self) -> None:
        text = (
            "Package: com.example.demo\n"
            "Name: Demo\n"
            "Version: 1.0\n"
            "Description: First line\n"
            " second line\n\n"
            "Package: com.example.two\n"
            "Version: 2.0\n"
        )
        stanzas = library.parse_control_stanzas(text)
        self.assertEqual(len(stanzas), 2)
        self.assertEqual(stanzas[0]["Description"], "First line\nsecond line")
        self.assertEqual(stanzas[1]["Package"], "com.example.two")

    def test_free_application_can_load_from_original_repo(self) -> None:
        item = library.classify_package(
            self.direct_source,
            {
                "Package": "com.example.demo",
                "Name": "Demo App",
                "Version": "1.0",
                "Architecture": "iphoneos-arm64",
                "Section": "Applications",
                "Description": "A standalone utility",
                "Filename": "debs/demo.deb",
                "License": "MIT",
            },
        )
        self.assertEqual(item["downloadPolicy"], "direct")
        self.assertEqual(item["conversion"]["class"], "application-candidate")
        self.assertGreaterEqual(item["conversion"]["score"], 60)
        self.assertTrue(item["bundleEligible"])
        self.assertEqual(item["downloadUrl"], "https://repo.example/debs/demo.deb")

    def test_commercial_package_is_not_downloaded(self) -> None:
        item = library.classify_package(
            self.direct_source,
            {
                "Package": "com.example.paid",
                "Version": "1.0",
                "Architecture": "iphoneos-arm64",
                "Section": "Tweaks",
                "Tag": "cydia::commercial",
                "Filename": "paid.deb",
            },
        )
        self.assertEqual(item["downloadPolicy"], "purchase-required")
        self.assertIsNone(item["downloadUrl"])
        self.assertIn("commercial", item["riskFlags"])

    def test_crack_metadata_is_blocked(self) -> None:
        item = library.classify_package(
            self.direct_source,
            {
                "Package": "com.example.cracktool",
                "Name": "Premium Unlocked Crack Tool",
                "Version": "1.0",
                "Architecture": "iphoneos-arm64",
                "Section": "Tweaks",
                "Filename": "crack.deb",
            },
        )
        self.assertEqual(item["downloadPolicy"], "blocked")
        self.assertEqual(item["conversion"]["score"], 0)
        self.assertIn("suspected-piracy", item["riskFlags"])

    def test_catalog_only_source_never_exposes_download_url(self) -> None:
        source = dict(self.direct_source, policy="catalog-only")
        item = library.classify_package(
            source,
            {
                "Package": "com.example.catalog",
                "Version": "1.0",
                "Architecture": "iphoneos-arm64",
                "Section": "Applications",
                "Filename": "catalog.deb",
            },
        )
        self.assertEqual(item["downloadPolicy"], "source-only")
        self.assertIsNone(item["downloadUrl"])


if __name__ == "__main__":
    unittest.main()
