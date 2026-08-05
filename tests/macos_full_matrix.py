#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "runner_full_auto.py"
MACHO = {
    b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xce",
    b"\xca\xfe\xba\xbe", b"\xbe\xba\fe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca",
}


def xcrun(tool: str) -> str:
    return subprocess.check_output(["xcrun", "--sdk", "iphoneos", "--find", tool], text=True).strip()


def sdk_path() -> str:
    return subprocess.check_output(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"], text=True).strip()


def make_deb(root: Path, name: str, payload: Path) -> Path:
    work = root / f"{name}-deb-work"
    control = work / "control"
    control.mkdir(parents=True)
    (control / "control").write_text(
        f"Package: app.debtoipa.{name.lower()}\n"
        "Version: 1.0\nArchitecture: iphoneos-arm64\n"
        "Description: DebToIPA full conversion smoke fixture\n",
        encoding="utf-8",
    )
    with tarfile.open(work / "data.tar.gz", "w:gz") as archive:
        archive.add(payload, arcname=".")
    with tarfile.open(work / "control.tar.gz", "w:gz") as archive:
        archive.add(control, arcname=".")
    (work / "debian-binary").write_text("2.0\n", encoding="ascii")
    deb = root / f"{name}.deb"
    subprocess.run(["ar", "-r", str(deb), "debian-binary", "control.tar.gz", "data.tar.gz"], cwd=work, check=True, stdout=subprocess.DEVNULL)
    return deb


def app_info(name: str, bundle: str, executable: str) -> dict:
    return {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleDisplayName": name,
        "CFBundleExecutable": executable,
        "CFBundleIdentifier": bundle,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": name,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1",
        "LSRequiresIPhoneOS": True,
        "MinimumOSVersion": "15.0",
        "UIDeviceFamily": [1, 2],
        "UILaunchScreen": {},
    }


def compile_objc_app(directory: Path, name: str, bundle: str, framework_search: Path | None = None, link_cephei: bool = False) -> Path:
    directory.mkdir(parents=True)
    source = directory.parent / f"{name}-main.m"
    cephei_lines = '#import <Cephei/HBPreferences.h>\n' if link_cephei else ""
    cephei_use = 'HBPreferences *prefs = [[HBPreferences alloc] initWithIdentifier:@"app.test"]; [prefs setBool:YES forKey:@"enabled"];' if link_cephei else ""
    source.write_text(f'''#import <UIKit/UIKit.h>
{cephei_lines}
@interface AppDelegate : UIResponder <UIApplicationDelegate>
@property(nonatomic, strong) UIWindow *window;
@end
@implementation AppDelegate
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options {{
    {cephei_use}
    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    UIViewController *controller = [UIViewController new];
    controller.view.backgroundColor = UIColor.systemBackgroundColor;
    self.window.rootViewController = controller;
    [self.window makeKeyAndVisible];
    return YES;
}}
@end
int main(int argc, char **argv) {{ @autoreleasepool {{ return UIApplicationMain(argc, argv, nil, NSStringFromClass(AppDelegate.class)); }} }}
''', encoding="utf-8")
    clang = xcrun("clang")
    command = [clang, "-target", "arm64-apple-ios15.0", "-isysroot", sdk_path(), "-fobjc-arc", "-Wl,-headerpad_max_install_names", "-framework", "UIKit", "-framework", "Foundation", "-o", str(directory / name), str(source)]
    if framework_search:
        command.extend(["-F", str(framework_search)])
    if link_cephei:
        command.extend(["-framework", "Cephei"])
    subprocess.run(command, check=True)
    os.chmod(directory / name, 0o755)
    (directory / "Info.plist").write_bytes(plistlib.dumps(app_info(name, bundle, name), fmt=plistlib.FMT_BINARY, sort_keys=False))
    return directory


def compile_fake_cephei(root: Path) -> Path:
    framework = root / "Library/Frameworks/Cephei.framework"
    headers = framework / "Headers"
    headers.mkdir(parents=True)
    header = headers / "HBPreferences.h"
    header.write_text('''#import <Foundation/Foundation.h>
@interface HBPreferences : NSObject
- (instancetype)initWithIdentifier:(NSString *)identifier;
- (void)setBool:(BOOL)value forKey:(NSString *)key;
@end
''', encoding="utf-8")
    module = framework / "Modules/module.modulemap"
    module.parent.mkdir(parents=True)
    module.write_text('framework module Cephei { umbrella header "HBPreferences.h" export * }\n', encoding="utf-8")
    impl = root / "FakeCephei.m"
    impl.write_text('''#import "HBPreferences.h"
@implementation HBPreferences
- (instancetype)initWithIdentifier:(NSString *)identifier { return [super init]; }
- (void)setBool:(BOOL)value forKey:(NSString *)key {}
@end
''', encoding="utf-8")
    clang = xcrun("clang")
    subprocess.run([
        clang, "-target", "arm64-apple-ios15.0", "-isysroot", sdk_path(), "-fobjc-arc", "-dynamiclib",
        "-install_name", "/Library/Frameworks/Cephei.framework/Cephei",
        "-framework", "Foundation", "-I", str(headers), "-o", str(framework / "Cephei"), str(impl),
    ], check=True)
    return root / "Library/Frameworks"


def make_source_payload(root: Path, name: str, kind: str, files: dict[str, str], alternatives: list[str], extensions: list[str] | None = None) -> Path:
    payload = root / f"{name}-payload"
    base = payload / "usr/share/debtoipa"
    sources = base / "Sources"
    sources.mkdir(parents=True)
    for relative, content in files.items():
        path = sources / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    manifest = {
        "schemaVersion": 2,
        "kind": kind,
        "appName": name,
        "bundleIdentifier": f"app.debtoipa.matrix.{name.lower()}",
        "minimumIOS": "15.0",
        "device": "universal",
        "sourceRoots": ["usr/share/debtoipa/Sources"],
        "resourceRoots": [],
        "requestedAlternatives": alternatives,
        "extensions": extensions or [],
        "companionService": "companion-service" in alternatives,
    }
    (base / "PortManifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return payload


def run_case(root: Path, deb: Path, job: str, profile: str = "automatic", alternatives: list[str] | None = None, expect_code: int = 0) -> Path:
    output = root / f"output-{job}"
    command = [
        sys.executable, str(RUNNER), "--deb", str(deb), "--output-dir", str(output),
        "--job-id", job, "--source-name", deb.name, "--device", "universal",
        "--minimum-ios", "15.0", "--bundle-id", "", "--display-name", "", "--profile", profile,
    ]
    for alternative in alternatives or []:
        command.extend(["--alternative", alternative])
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != expect_code:
        raise AssertionError(f"{job}: expected exit {expect_code}, got {result.returncode}")
    return output


def validate_ipa(path: Path, *, expected_result: str, require_extensions: set[str] | None = None) -> dict:
    summary = json.loads((path.parent / "runner-summary.json").read_text())
    assert summary["resultKind"] == expected_result, summary
    assert summary["compatibilityHostGenerated"] is False
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        plists = [name for name in names if name.startswith("Payload/") and name.count("/") == 2 and name.endswith("Info.plist")]
        assert len(plists) == 1, plists
        info = plistlib.loads(archive.read(plists[0]))
        executable = info["CFBundleExecutable"]
        assert executable != "DebToIPACompatibilityHost"
        binary = archive.read(plists[0].rsplit("/", 1)[0] + "/" + executable)
        assert binary[:4] in MACHO, binary[:4]
        if require_extensions:
            extension_names = {
                kind: f"DebToIPA{kind.title().replace('-', '')}Extension"
                for kind in require_extensions
            }
            for kind, extension_name in extension_names.items():
                prefix = plists[0].rsplit("/", 1)[0] + f"/PlugIns/{extension_name}.appex/"
                assert any(name.startswith(prefix) for name in names), (kind, names)
                executable_path = prefix + extension_name
                assert executable_path in names, (kind, executable_path)
                assert archive.read(executable_path)[:4] in MACHO, (kind, archive.read(executable_path)[:4])
    return summary


def main() -> int:
    if sys.platform != "darwin" or shutil.which("xcrun") is None:
        raise SystemExit("macOS with Xcode is required.")
    with tempfile.TemporaryDirectory(prefix="debtoipa-full-matrix-") as temporary:
        root = Path(temporary)

        # 1. Compatible original ARM64 app.
        direct_payload = root / "Direct-payload"
        direct_app = direct_payload / "Applications/Direct.app"
        compile_objc_app(direct_app, "Direct", "app.debtoipa.matrix.direct")
        direct_deb = make_deb(root, "Direct", direct_payload)
        direct_output = run_case(root, direct_deb, "direct", profile="direct-ipa")
        direct_ipa = next(direct_output.glob("*.ipa"))
        validate_ipa(direct_ipa, expected_result="real-ipa")

        # 2. Original binary linked to Cephei, repaired to the audited embedded adapter.
        shim_payload = root / "Shim-payload"
        framework_search = compile_fake_cephei(root / "FakeFrameworks")
        shim_app = shim_payload / "Applications/Shim.app"
        compile_objc_app(shim_app, "Shim", "app.debtoipa.matrix.shim", framework_search, True)
        shim_deb = make_deb(root, "Shim", shim_payload)
        shim_output = run_case(root, shim_deb, "shim", profile="binary-shims")
        shim_ipa = next(shim_output.glob("*.ipa"))
        validate_ipa(shim_ipa, expected_result="binary-shimmed")
        shim_report = json.loads((shim_output / "binary-shim-report.json").read_text())
        assert shim_report["replacedDependencies"], shim_report
        assert "@rpath/DebToIPAAdapters.framework/DebToIPAAdapters" in shim_report["dependenciesAfter"]

        # 3. SwiftUI source with every normal-iOS app adapter and extension alternative.
        swift_alternatives = [
            "preferences-adapter", "sandbox-path-adapter", "notification-adapter",
            "background-task", "background-transfer", "push-notifications",
            "app-intents", "settings-screen", "document-picker", "url-schemes",
            "local-proxy", "native-library", "standalone-ui", "companion-service",
            "widget-extension", "share-extension", "safari-web-extension",
            "content-blocker", "network-extension", "file-provider",
        ]
        extension_kinds = {"widget", "share", "safari", "content-blocker", "network", "file-provider"}
        swift_payload = make_source_payload(root, "SwiftAlternatives", "swiftui-app", {
            "App.swift": '''import SwiftUI
import Cephei
@main struct SwiftAlternativesApp: App {
    let preferences = HBPreferences(identifier: "app.debtoipa.matrix.swift")
    let legacyPath = "/var/mobile/Documents/state.json"
    var body: some Scene { WindowGroup { DebToIPAStandaloneRootView { DebToIPASettingsView() } } }
}
''',
        }, swift_alternatives)
        swift_deb = make_deb(root, "SwiftAlternatives", swift_payload)
        swift_output = run_case(root, swift_deb, "swift-alternatives", profile="app-extensions", alternatives=swift_alternatives)
        swift_ipa = next(swift_output.glob("*.ipa"))
        swift_summary = validate_ipa(swift_ipa, expected_result="source-ported", require_extensions=extension_kinds)
        assert swift_summary["stockIOSCompileVerified"] is True
        assert (swift_output / "CompanionService/api/task.ts").is_file()
        generated = swift_output / "GeneratedAdapters"
        for relative in [
            "Swift/BackgroundTransferAdapter.swift", "Swift/PushSyncAdapter.swift",
            "Swift/SettingsView.swift", "Swift/DocumentPickerAdapter.swift",
            "Swift/URLRouter.swift", "Swift/LocalConnection.swift",
            "Swift/NativeTool.swift", "Swift/StandaloneRootView.swift",
            "Signing/Entitlements.plist",
        ]:
            assert (generated / relative).is_file(), relative
        source_report = json.loads((swift_output / "source-port-report.json").read_text())
        assert any("HBPreferences" in item for item in source_report["rewrites"]), source_report["rewrites"]
        assert {item["kind"] for item in source_report["extensions"]} == extension_kinds
        with zipfile.ZipFile(swift_ipa) as archive:
            info_name = next(name for name in archive.namelist() if name.startswith("Payload/") and name.count("/") == 2 and name.endswith("Info.plist"))
            app_plist = plistlib.loads(archive.read(info_name))
            assert "remote-notification" in app_plist["UIBackgroundModes"]
            assert app_plist["CFBundleURLTypes"][0]["CFBundleURLSchemes"]

        # 4. Objective-C source: HBPreferences header rewrite and Share Extension.
        objc_payload = make_source_payload(root, "ObjCAlternatives", "uikit-objc-app", {
            "main.m": '''#import <UIKit/UIKit.h>
#import <Cephei/HBPreferences.h>
@interface AppDelegate : UIResponder <UIApplicationDelegate>
@property(nonatomic, strong) UIWindow *window;
@end
@implementation AppDelegate
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options {
    HBPreferences *prefs = [[HBPreferences alloc] initWithIdentifier:@"app.debtoipa.matrix.objc"];
    [prefs setBool:YES forKey:@"enabled"];
    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    self.window.rootViewController = [UIViewController new];
    [self.window makeKeyAndVisible];
    return YES;
}
@end
int main(int argc, char **argv) { @autoreleasepool { return UIApplicationMain(argc, argv, nil, NSStringFromClass(AppDelegate.class)); } }
''',
        }, ["preferences-adapter", "share-extension", "notification-adapter"], ["share"])
        objc_deb = make_deb(root, "ObjCAlternatives", objc_payload)
        objc_output = run_case(root, objc_deb, "objc-alternatives", profile="app-extensions")
        objc_ipa = next(objc_output.glob("*.ipa"))
        validate_ipa(objc_ipa, expected_result="source-ported", require_extensions={"share"})

        # 5. Binary-only SpringBoard/Logos hook must fail honestly and produce no fake app.
        blocked_payload = root / "Blocked-payload"
        hook = blocked_payload / "Library/MobileSubstrate/DynamicLibraries/Blocked.xm"
        hook.parent.mkdir(parents=True)
        hook.write_text("%hook SpringBoard\n- (void)applicationDidFinishLaunching:(id)x {}\n%end\n")
        blocked_deb = make_deb(root, "Blocked", blocked_payload)
        blocked_output = run_case(root, blocked_deb, "blocked", profile="automatic", expect_code=2)
        blocked_summary = json.loads((blocked_output / "runner-summary.json").read_text())
        assert blocked_summary["resultKind"] == "unsupported", blocked_summary
        assert not list(blocked_output.glob("*.ipa")), list(blocked_output.glob("*.ipa"))
        assert (blocked_output / "capability-plan.json").is_file()
        assert (blocked_output / "GeneratedPortProject/AdapterManifest.json").is_file()

    print("Full DebToIPA matrix passed: direct, binary shim, every generated Swift/extension alternative, Objective-C extension, and honest blocker.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
