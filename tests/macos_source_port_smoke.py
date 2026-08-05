#!/usr/bin/env python3
from __future__ import annotations

import json
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


def make_deb(root: Path, name: str, kind: str, files: dict[str, str]) -> Path:
    package = root / name
    payload = package / "payload"
    control = package / "control"
    work = package / "work"
    payload.mkdir(parents=True)
    control.mkdir()
    work.mkdir()

    base = payload / "usr" / "share" / "debtoipa"
    sources = base / "Sources"
    sources.mkdir(parents=True)
    manifest = {
        "schemaVersion": 1,
        "kind": kind,
        "appName": name,
        "bundleIdentifier": f"app.debtoipa.smoke.{name.lower()}",
        "minimumIOS": "15.0",
        "sourceRoots": ["usr/share/debtoipa/Sources"],
        "resourceRoots": [],
    }
    (base / "PortManifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for relative, content in files.items():
        path = sources / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    (control / "control").write_text(
        f"Package: app.debtoipa.{name.lower()}\n"
        "Version: 1.0\nArchitecture: iphoneos-arm64\n"
        "Description: DebToIPA source smoke\n",
        encoding="utf-8",
    )
    with tarfile.open(work / "data.tar.gz", "w:gz") as archive:
        archive.add(payload, arcname=".")
    with tarfile.open(work / "control.tar.gz", "w:gz") as archive:
        archive.add(control, arcname=".")
    (work / "debian-binary").write_text("2.0\n", encoding="ascii")
    deb = root / f"{name}.deb"
    subprocess.run(
        ["ar", "-r", str(deb), "debian-binary", "control.tar.gz", "data.tar.gz"],
        cwd=work,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    return deb


def verify_result(output: Path, expected_name: str, expected_rewrite: str) -> None:
    summary = json.loads((output / "runner-summary.json").read_text())
    assert summary["resultKind"] == "source-ported", summary
    assert summary["stockIOSCompileVerified"] is True
    assert summary["behavioralParityVerified"] is False
    assert summary["compatibilityHostGenerated"] is False

    source_report = json.loads((output / "source-port-report.json").read_text())
    assert source_report["compileVerified"] is True
    assert source_report["sourceDerived"] is True
    assert any(expected_rewrite in item for item in source_report["rewrites"]), source_report

    ipas = list(output.glob("*.ipa"))
    assert len(ipas) == 1, ipas
    with zipfile.ZipFile(ipas[0]) as archive:
        plist_names = [name for name in archive.namelist() if name.endswith(".app/Info.plist")]
        assert len(plist_names) == 1
        plist = plistlib.loads(archive.read(plist_names[0]))
        executable = plist["CFBundleExecutable"]
        assert executable != "DebToIPACompatibilityHost"
        binary = archive.read(plist_names[0].rsplit("/", 1)[0] + "/" + executable)
        assert binary[:4] in {
            b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf",
            b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
            b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca",
        }
        assert expected_name in (plist.get("CFBundleDisplayName") or "")


def run_case(root: Path, deb: Path, job: str) -> Path:
    output = root / f"output-{job}"
    command = [
        sys.executable, str(RUNNER), "--deb", str(deb), "--output-dir", str(output),
        "--job-id", job, "--source-name", deb.name, "--device", "universal",
        "--minimum-ios", "15.0", "--bundle-id", "", "--display-name", "",
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    return output


def main() -> int:
    if sys.platform != "darwin" or shutil.which("xcrun") is None:
        raise SystemExit("This smoke test requires macOS with Xcode.")
    with tempfile.TemporaryDirectory(prefix="debtoipa-macos-smoke-") as temporary:
        root = Path(temporary)
        swift = make_deb(root, "SwiftPort", "swiftui-app", {
            "App.swift": """import SwiftUI
import Cephei

@main struct SwiftPortApp: App {
    private let preferences = HBPreferences(identifier: "app.debtoipa.swiftport")
    private let legacyPath = "/var/mobile/Library/Preferences"
    var body: some Scene {
        WindowGroup {
            Text(legacyPath + ":" + String(preferences.integer(forKey: "launches")))
        }
    }
}
""",
        })
        swift_output = run_case(root, swift, "swift-source-smoke")
        verify_result(swift_output, "SwiftPort", "Cephei")

        objc = make_deb(root, "ObjCPort", "uikit-objc-app", {
            "main.m": """#import <UIKit/UIKit.h>
#import \"AppDelegate.h\"
int main(int argc, char * argv[]) {
    @autoreleasepool { return UIApplicationMain(argc, argv, nil, NSStringFromClass(AppDelegate.class)); }
}
""",
            "AppDelegate.h": """#import <UIKit/UIKit.h>
@interface AppDelegate : UIResponder <UIApplicationDelegate>
@property(nonatomic, strong) UIWindow *window;
@end
""",
            "AppDelegate.m": """#import \"AppDelegate.h\"
#import <Cephei/HBPreferences.h>

@implementation AppDelegate
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options {
    HBPreferences *preferences = [[HBPreferences alloc] initWithIdentifier:@"app.debtoipa.objcport"];
    [preferences setObject:@"ready" forKey:@"state"];
    NSString *legacyPath = @"/var/mobile/Library/Preferences";
    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    UIViewController *controller = [UIViewController new];
    controller.view.backgroundColor = UIColor.systemBackgroundColor;
    UILabel *label = [[UILabel alloc] initWithFrame:controller.view.bounds];
    label.text = [legacyPath stringByAppendingFormat:@":%@", [preferences stringForKey:@"state"]];
    label.textAlignment = NSTextAlignmentCenter;
    [controller.view addSubview:label];
    self.window.rootViewController = controller;
    [self.window makeKeyAndVisible];
    return YES;
}
@end
""",
        })
        objc_output = run_case(root, objc, "objc-source-smoke")
        verify_result(objc_output, "ObjCPort", "Cephei")

    print("Swift and Objective-C source-port IPAs, including compatibility rewrites, compiled and validated on iPhoneOS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
