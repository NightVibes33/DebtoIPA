from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from capability_graph import analyze_payload
from adapter_sdk import write_adapter_sdk
from source_port import SourcePortError, _read_manifest, _scan_and_rewrite


class CapabilityGraphTests(unittest.TestCase):
    def test_daemon_hook_preferences_plan_prefers_source_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Library/LaunchDaemons").mkdir(parents=True)
            (root / "Library/LaunchDaemons/app.test.plist").write_text("<plist></plist>")
            source = root / "usr/share/debtoipa/Sources/App.swift"
            source.parent.mkdir(parents=True)
            source.write_text('import SwiftUI\nimport Cephei\n// SpringBoard\n@main struct A: App { var body: some Scene { WindowGroup { Text("x") } } }')
            graph = analyze_payload(root)
            ids = {item.id for item in graph.capabilities}
            self.assertIn("launch-daemon", ids)
            self.assertIn("springboard-hook", ids)
            self.assertIn("cephei-preferences", ids)
            self.assertIn(graph.recommendedProfile, {"source-rebuild", "app-extensions", "background-replacement"})
            self.assertGreaterEqual(graph.expectedRetainedFunctionality, 70)

    def test_binary_only_injection_is_not_claimed_usable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hook = root / "Library/MobileSubstrate/DynamicLibraries/Test.dylib"
            hook.parent.mkdir(parents=True)
            hook.write_bytes(b"not-a-real-mach-o")
            config = hook.with_suffix(".plist")
            config.write_text("SpringBoard MobileSubstrate")
            graph = analyze_payload(root)
            self.assertIn("cross-app-injection", {item.id for item in graph.capabilities})
            self.assertFalse(graph.facts["hasSource"])
            self.assertIn(graph.recommendedProfile, {"companion-service", "report-only"})

    def test_requested_background_profile_is_ranked_first(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "DebToIPA/Sources/App.swift"
            source.parent.mkdir(parents=True)
            source.write_text('import SwiftUI\n@main struct A: App { var body: some Scene { WindowGroup { Text("x") } } }')
            daemon = root / "Library/LaunchDaemons/x.plist"
            daemon.parent.mkdir(parents=True)
            daemon.write_text("<plist></plist>")
            graph = analyze_payload(root, requested_profile="background-replacement", requested_alternatives=["background-task"])
            self.assertEqual(graph.profiles[0].id, "background-replacement")
            self.assertEqual(graph.requestedProfile, "background-replacement")


class AdapterSDKTests(unittest.TestCase):
    def test_generates_all_normal_alternatives(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = write_adapter_sdk(
                root,
                bundle_id="app.test.converted",
                app_name="Converted",
                alternatives={
                    "preferences-adapter", "sandbox-path-adapter", "notification-adapter",
                    "background-task", "background-transfer", "push-notifications", "app-intents",
                    "settings-screen", "document-picker", "url-schemes", "local-proxy",
                    "native-library", "standalone-ui", "widget-extension", "share-extension",
                    "safari-web-extension", "network-extension", "file-provider", "content-blocker",
                    "companion-service",
                },
            )
            self.assertTrue((root / "Swift/BackgroundTaskAdapter.swift").is_file())
            self.assertTrue((root / "Swift/BackgroundTransferAdapter.swift").is_file())
            self.assertTrue((root / "Swift/SettingsView.swift").is_file())
            self.assertTrue((root / "Swift/DocumentPickerAdapter.swift").is_file())
            self.assertTrue((root / "Swift/PushSyncAdapter.swift").is_file())
            self.assertTrue((root / "Swift/URLRouter.swift").is_file())
            self.assertTrue((root / "Swift/LocalConnection.swift").is_file())
            self.assertTrue((root / "ObjectiveC/HBPreferences.m").is_file())
            self.assertTrue((root / "Extensions/Widget/Widget.swift").is_file())
            self.assertTrue((root / "Extensions/Share/ShareViewController.swift").is_file())
            self.assertTrue((root / "Extensions/Safari/SafariWebExtensionHandler.swift").is_file())
            self.assertTrue((root / "Extensions/Network/DebToIPAPacketTunnelProvider.swift").is_file())
            self.assertTrue((root / "Extensions/FileProvider/DebToIPAFileProviderExtension.swift").is_file())
            self.assertTrue((root / "Extensions/ContentBlocker/blockerList.json").is_file())
            self.assertTrue((root / "CompanionService/api/task.ts").is_file())
            self.assertEqual(set(manifest["extensions"]), {"widget", "share", "safari", "network", "file-provider", "content-blocker"})
            package = json.loads((root / "CompanionService/package.json").read_text())
            self.assertTrue(package["private"])


class SourcePolicyTests(unittest.TestCase):
    def test_swift_rewrites_cephei_and_paths(self) -> None:
        text = 'import Cephei\nlet p = HBPreferences(identifier: "app.test")\nlet path = "/var/mobile/Documents/test"\n'
        rewritten, rewrites, blockers = _scan_and_rewrite(Path("App.swift"), text)
        self.assertNotIn("import Cephei", rewritten)
        self.assertIn("DebToIPAPreferences", rewritten)
        self.assertIn("DebToIPASandboxPaths.documents", rewritten)
        self.assertFalse(blockers)
        self.assertGreaterEqual(len(rewrites), 2)

    def test_rejects_process_control(self) -> None:
        _, _, blockers = _scan_and_rewrite(Path("Bad.m"), "int x = task_for_pid(0, 1, 0);")
        self.assertTrue(blockers)

    def test_manifest_v2_parses_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "usr/share/debtoipa"
            (base / "Sources").mkdir(parents=True)
            (base / "Sources/App.swift").write_text('@main struct A {}')
            (base / "PortManifest.json").write_text(json.dumps({
                "schemaVersion": 2,
                "kind": "swiftui-app",
                "appName": "A",
                "bundleIdentifier": "app.test.a",
                "minimumIOS": "15.0",
                "device": "universal",
                "sourceRoots": ["usr/share/debtoipa/Sources"],
                "resourceRoots": [],
                "requestedAlternatives": ["widget-extension", "background-task"],
                "extensions": [],
            }))
            manifest = _read_manifest(root, {})
            self.assertIsNotNone(manifest)
            assert manifest
            self.assertIn("widget", manifest.extensions)
            self.assertIn("background-task", manifest.requested_alternatives)


if __name__ == "__main__":
    unittest.main()
