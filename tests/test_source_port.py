import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "scripts" / "source_port.py"
SPEC = importlib.util.spec_from_file_location("source_port", SOURCE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules["source_port"] = MODULE
SPEC.loader.exec_module(MODULE)


def make_tree(source: str, kind: str = "swiftui-app"):
    temporary = tempfile.TemporaryDirectory()
    root = Path(temporary.name)
    package = root / "usr" / "share" / "debtoipa"
    sources = package / "Sources"
    sources.mkdir(parents=True)
    (package / "PortManifest.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "kind": kind,
                "appName": "Source Test",
                "bundleIdentifier": "com.example.sourcetest",
                "minimumIOS": "15.0",
                "sourceRoots": ["usr/share/debtoipa/Sources"],
                "resourceRoots": [],
            }
        ),
        encoding="utf-8",
    )
    filename = "App.swift" if kind == "swiftui-app" else "main.m"
    (sources / filename).write_text(source, encoding="utf-8")
    return temporary, root


class SourcePortTests(unittest.TestCase):
    def test_rewrites_common_jailbreak_preferences_and_cephei(self):
        temporary, root = make_tree(
            "import SwiftUI\nimport Cephei\n"
            '@main struct AppMain: App { var body: some Scene { WindowGroup { Text("Hi") } } }\n'
            'let path = "/var/mobile/Library/Preferences"\n'
        )
        self.addCleanup(temporary.cleanup)
        manifest = MODULE._read_manifest(root, {})
        self.assertIsNotNone(manifest)
        with tempfile.TemporaryDirectory() as output:
            prepared = MODULE.prepare_source_tree(root, manifest, Path(output))
            text = "\n".join(path.read_text() for path in prepared["compiled"])
        self.assertNotIn("import Cephei", text)
        self.assertIn("DTICompat.preferencesDirectory.path", text)
        self.assertTrue(any("Cephei" in item for item in prepared["rewrites"]))

    def test_rejects_logos_hook_source(self):
        temporary, root = make_tree(
            "import SwiftUI\n"
            '@main struct AppMain: App { var body: some Scene { WindowGroup { Text("Hi") } } }\n'
            "%hook SpringBoard\n"
        )
        self.addCleanup(temporary.cleanup)
        manifest = MODULE._read_manifest(root, {})
        with tempfile.TemporaryDirectory() as output:
            with self.assertRaisesRegex(MODULE.SourcePortError, "Logos hooks"):
                MODULE.prepare_source_tree(root, manifest, Path(output))

    def test_rejects_private_framework(self):
        temporary, root = make_tree(
            "import SwiftUI\n"
            '@main struct AppMain: App { var body: some Scene { WindowGroup { Text("Hi") } } }'
        )
        self.addCleanup(temporary.cleanup)
        manifest_path = root / "usr/share/debtoipa/PortManifest.json"
        data = json.loads(manifest_path.read_text())
        data["frameworks"] = ["SpringBoardServices"]
        manifest_path.write_text(json.dumps(data))
        with self.assertRaisesRegex(MODULE.SourcePortError, "unsupported or private"):
            MODULE._read_manifest(root, {})

    def test_objc_requires_application_main(self):
        temporary, root = make_tree(
            "#import <UIKit/UIKit.h>\nint helper(void) { return 0; }\n",
            "uikit-objc-app",
        )
        self.addCleanup(temporary.cleanup)
        manifest = MODULE._read_manifest(root, {})
        with tempfile.TemporaryDirectory() as output:
            with self.assertRaisesRegex(MODULE.SourcePortError, "UIApplicationMain"):
                MODULE.prepare_source_tree(root, manifest, Path(output))

    def test_auto_detects_recognized_source_root(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        source = root / "DebToIPA" / "Sources"
        source.mkdir(parents=True)
        (source / "App.swift").write_text(
            "import SwiftUI\n"
            '@main struct A: App { var body: some Scene { WindowGroup { Text("A") } } }'
        )
        manifest = MODULE._read_manifest(root, {"displayName": "Auto Source"})
        self.assertEqual(manifest.kind, "swiftui-app")
        self.assertEqual(manifest.app_name, "Auto Source")


if __name__ == "__main__":
    unittest.main()
