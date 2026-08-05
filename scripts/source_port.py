#!/usr/bin/env python3
"""Source-assisted stock-iOS rebuilds for DebToIPA.

This module never runs package build scripts. It accepts only source files and
resources from a constrained manifest, rejects known jailbreak/private APIs,
applies a small set of explicit compatibility rewrites, then invokes Apple's
command-line compiler directly on a macOS runner.
"""
from __future__ import annotations

import hashlib
import json
import plistlib
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

MANIFEST_LOCATIONS = (
    "DebToIPA/PortManifest.json",
    "usr/share/debtoipa/PortManifest.json",
    "Library/DebToIPA/PortManifest.json",
    "var/jb/Library/DebToIPA/PortManifest.json",
)
AUTO_SOURCE_ROOTS = (
    "DebToIPA/Sources",
    "usr/share/debtoipa/Sources",
    "Library/DebToIPA/Sources",
    "var/jb/Library/DebToIPA/Sources",
)
AUTO_RESOURCE_ROOTS = (
    "DebToIPA/Resources",
    "usr/share/debtoipa/Resources",
    "Library/DebToIPA/Resources",
    "var/jb/Library/DebToIPA/Resources",
)
SOURCE_EXTENSIONS = {".swift", ".m", ".mm", ".c", ".h"}
COMPILED_EXTENSIONS = {".swift", ".m", ".mm", ".c"}
MAX_SOURCE_FILES = 160
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_RESOURCE_BYTES = 50 * 1024 * 1024
MAX_SINGLE_FILE_BYTES = 2 * 1024 * 1024

PUBLIC_FRAMEWORKS = {
    "Accelerate", "ARKit", "AudioToolbox", "AVFoundation", "CloudKit",
    "Combine", "Contacts", "CoreAudio", "CoreData", "CoreGraphics",
    "CoreImage", "CoreLocation", "CoreMedia", "CoreMotion", "CoreText",
    "CoreVideo", "EventKit", "Foundation", "GameController", "GameKit",
    "LocalAuthentication", "MapKit", "Metal", "MetalKit", "Network",
    "PDFKit", "Photos", "PhotosUI", "QuartzCore", "QuickLook", "ReplayKit",
    "SafariServices", "SceneKit", "Security", "SpriteKit", "StoreKit",
    "SwiftUI", "UIKit", "UniformTypeIdentifiers", "UserNotifications",
    "VideoToolbox", "Vision", "WebKit",
}

PROHIBITED_IMPORTS = {
    "BackBoardServices", "Cephei", "CydiaSubstrate", "ElleKit", "FrontBoard",
    "FrontBoardServices", "libhooker", "MobileSubstrate", "Preferences",
    "RocketBootstrap", "SpringBoard", "SpringBoardServices", "substrate",
}

PROHIBITED_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"%\s*(?:hook|orig|end|ctor|group|init)\b"), "Logos hooks cannot run in a normal app process."),
    (re.compile(r"\b(?:MSHookFunction|MSHookMessageEx|LHHookFunctions?|substitute_hook_functions?)\b"), "Runtime hooking APIs require a jailbreak injection environment."),
    (re.compile(r"\b(?:dlopen|dlsym)\s*\("), "Runtime loading of private or jailbreak libraries is not accepted."),
    (re.compile(r"\b(?:fork|vfork|posix_spawn|system)\s*\("), "Launching helper processes is unavailable to a normal sandboxed iOS app."),
    (re.compile(r"(?:/var/jb/|/Library/MobileSubstrate/|/usr/lib/TweakInject/)"), "The source contains jailbreak-only filesystem paths."),
    (re.compile(r"\b(?:SBApplicationController|LSApplicationWorkspace|FBSSystemService|BKSTerminateApplicationForReasonAndReportWithDescription)\b"), "The source calls private SpringBoard or application-management APIs."),
    (re.compile(r"\btask_for_pid\b|\bvm_write\b|\bptrace\b"), "The source requests process-control capabilities unavailable to App Store-style apps."),
)

SWIFT_REWRITES: tuple[tuple[str, str, str], ...] = (
    ("import Cephei\n", "", "Removed the Cephei import and supplied an HBPreferences-compatible UserDefaults shim."),
    ("CFNotificationCenterGetDarwinNotifyCenter()", "CFNotificationCenterGetLocalCenter()", "Replaced Darwin notifications with in-process notifications."),
    ('"/var/mobile/Library/Preferences"', "DTICompat.preferencesDirectory.path", "Redirected the jailbreak preferences directory into the app sandbox."),
    ('"/var/mobile/Documents"', "DTICompat.documentsDirectory.path", "Redirected the mobile Documents path into the app sandbox."),
)

OBJC_REWRITES: tuple[tuple[str, str, str], ...] = (
    ("#import <Cephei/HBPreferences.h>\n", '#import "HBPreferences.h"\n', "Replaced Cephei HBPreferences with a UserDefaults-backed compatibility class."),
    ("#import <Cephei/HBPreferences.h>\r\n", '#import "HBPreferences.h"\r\n', "Replaced Cephei HBPreferences with a UserDefaults-backed compatibility class."),
    ("CFNotificationCenterGetDarwinNotifyCenter()", "CFNotificationCenterGetLocalCenter()", "Replaced Darwin notifications with in-process notifications."),
    ('@"/var/mobile/Library/Preferences"', "DTICompat.preferencesDirectory.path", "Redirected the jailbreak preferences directory into the app sandbox."),
    ('@"/var/mobile/Documents"', "DTICompat.documentsDirectory.path", "Redirected the mobile Documents path into the app sandbox."),
)

SWIFT_SHIM = r'''import Foundation

public enum DTICompat {
    public static let documentsDirectory = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
    public static let cachesDirectory = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
    public static let applicationSupportDirectory: URL = {
        let url = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }()
    public static let preferencesDirectory: URL = {
        let url = applicationSupportDirectory.appendingPathComponent("Preferences", isDirectory: true)
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }()
}

@objcMembers
public final class HBPreferences: NSObject {
    private let defaults: UserDefaults
    public init(identifier: String) {
        defaults = UserDefaults(suiteName: identifier) ?? .standard
        super.init()
    }
    public func object(forKey key: String) -> Any? { defaults.object(forKey: key) }
    public func set(_ value: Any?, forKey key: String) { defaults.set(value, forKey: key) }
    public func bool(forKey key: String) -> Bool { defaults.bool(forKey: key) }
    public func integer(forKey key: String) -> Int { defaults.integer(forKey: key) }
    public func string(forKey key: String) -> String? { defaults.string(forKey: key) }
    public func register(defaults values: [String: Any]) { defaults.register(defaults: values) }
}
'''

OBJC_SHIM_HEADER = r'''#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN
@interface DTICompat : NSObject
@property(class, nonatomic, readonly) NSURL *documentsDirectory;
@property(class, nonatomic, readonly) NSURL *preferencesDirectory;
@end

@interface HBPreferences : NSObject
- (instancetype)initWithIdentifier:(NSString *)identifier;
- (nullable id)objectForKey:(NSString *)key;
- (void)setObject:(nullable id)value forKey:(NSString *)key;
- (BOOL)boolForKey:(NSString *)key;
- (NSInteger)integerForKey:(NSString *)key;
- (nullable NSString *)stringForKey:(NSString *)key;
- (void)registerDefaults:(NSDictionary<NSString *, id> *)defaults;
@end
NS_ASSUME_NONNULL_END
'''

OBJC_SHIM_SOURCE = r'''#import "HBPreferences.h"

@implementation DTICompat
+ (NSURL *)documentsDirectory {
    return [[[NSFileManager defaultManager] URLsForDirectory:NSDocumentDirectory inDomains:NSUserDomainMask] firstObject];
}
+ (NSURL *)preferencesDirectory {
    NSURL *base = [[[NSFileManager defaultManager] URLsForDirectory:NSApplicationSupportDirectory inDomains:NSUserDomainMask] firstObject];
    NSURL *url = [base URLByAppendingPathComponent:@"Preferences" isDirectory:YES];
    [[NSFileManager defaultManager] createDirectoryAtURL:url withIntermediateDirectories:YES attributes:nil error:nil];
    return url;
}
@end

@implementation HBPreferences {
    NSUserDefaults *_defaults;
}
- (instancetype)initWithIdentifier:(NSString *)identifier {
    if ((self = [super init])) {
        _defaults = [[NSUserDefaults alloc] initWithSuiteName:identifier] ?: NSUserDefaults.standardUserDefaults;
    }
    return self;
}
- (id)objectForKey:(NSString *)key { return [_defaults objectForKey:key]; }
- (void)setObject:(id)value forKey:(NSString *)key { [_defaults setObject:value forKey:key]; }
- (BOOL)boolForKey:(NSString *)key { return [_defaults boolForKey:key]; }
- (NSInteger)integerForKey:(NSString *)key { return [_defaults integerForKey:key]; }
- (NSString *)stringForKey:(NSString *)key { return [_defaults stringForKey:key]; }
- (void)registerDefaults:(NSDictionary<NSString *,id> *)defaults { [_defaults registerDefaults:defaults]; }
@end
'''


class SourcePortError(RuntimeError):
    """A package contains source, but it cannot be safely rebuilt for stock iOS."""


@dataclass
class PortManifest:
    kind: str
    app_name: str
    bundle_identifier: str
    minimum_ios: str
    source_roots: list[str]
    resource_roots: list[str]
    frameworks: list[str]
    device: str = "universal"
    metadata: dict[str, Any] = field(default_factory=dict)


def _safe_path(root: Path, relative: str) -> Path:
    if not relative or "\0" in relative:
        raise SourcePortError("Manifest paths must be non-empty relative paths.")
    candidate = (root / relative).resolve()
    resolved_root = root.resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise SourcePortError(f"Manifest path escapes the Debian payload: {relative}")
    return candidate


def _valid_bundle_id(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", value))


def _valid_version(value: str) -> bool:
    return bool(re.fullmatch(r"\d{1,2}(?:\.\d{1,2}){0,2}", value))


def _sanitize_app_name(value: str) -> str:
    cleaned = re.sub(r"[\x00-\x1f/:]+", " ", value).strip()
    return cleaned[:80] or "Converted App"


def _default_bundle_id(app_name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "", app_name).lower()[:40] or "portedapp"
    return f"app.debtoipa.{slug}"


def _read_manifest(payload_root: Path, options: dict[str, Any]) -> PortManifest | None:
    data: dict[str, Any] | None = None
    manifest_path: Path | None = None
    for location in MANIFEST_LOCATIONS:
        path = payload_root / location
        if path.is_file():
            manifest_path = path
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise SourcePortError(f"Invalid source-port manifest: {error}") from error
            if not isinstance(loaded, dict):
                raise SourcePortError("Source-port manifest must be a JSON object.")
            data = loaded
            break

    if data is None:
        roots = [location for location in AUTO_SOURCE_ROOTS if (payload_root / location).is_dir()]
        if not roots:
            return None
        extensions = {path.suffix.lower() for root in roots for path in (payload_root / root).rglob("*") if path.is_file()}
        if ".swift" in extensions:
            kind = "swiftui-app"
        elif extensions & {".m", ".mm"}:
            kind = "uikit-objc-app"
        else:
            raise SourcePortError("Source roots were found, but no Swift or Objective-C app sources were detected.")
        data = {
            "schemaVersion": 1,
            "kind": kind,
            "sourceRoots": roots,
            "resourceRoots": [location for location in AUTO_RESOURCE_ROOTS if (payload_root / location).is_dir()],
        }

    if int(data.get("schemaVersion", 0)) != 1:
        raise SourcePortError("Unsupported source-port manifest schema.")
    kind = str(data.get("kind", "")).strip()
    if kind not in {"swiftui-app", "uikit-objc-app"}:
        raise SourcePortError("Source-port kind must be swiftui-app or uikit-objc-app.")
    source_roots = data.get("sourceRoots") or []
    resource_roots = data.get("resourceRoots") or []
    frameworks = data.get("frameworks") or []
    if not isinstance(source_roots, list) or not source_roots or not all(isinstance(item, str) for item in source_roots):
        raise SourcePortError("sourceRoots must contain at least one relative directory.")
    if not isinstance(resource_roots, list) or not all(isinstance(item, str) for item in resource_roots):
        raise SourcePortError("resourceRoots must be a list of relative directories.")
    if not isinstance(frameworks, list) or not all(isinstance(item, str) for item in frameworks):
        raise SourcePortError("frameworks must be a list of Apple framework names.")
    unknown = sorted(set(frameworks) - PUBLIC_FRAMEWORKS)
    if unknown:
        raise SourcePortError("Manifest requests unsupported or private frameworks: " + ", ".join(unknown))

    inferred_name = Path(str(options.get("sourceName") or "Converted App")).stem
    app_name = _sanitize_app_name(str(options.get("displayName") or data.get("appName") or inferred_name))
    bundle_id = str(options.get("bundleId") or data.get("bundleIdentifier") or _default_bundle_id(app_name))
    if not _valid_bundle_id(bundle_id):
        raise SourcePortError("Source-port bundle identifier is invalid.")
    minimum_ios = str(options.get("minimumIos") or data.get("minimumIOS") or "15.0")
    if not _valid_version(minimum_ios):
        raise SourcePortError("Source-port minimum iOS version is invalid.")
    device = str(options.get("device") or data.get("device") or "universal")
    if device not in {"universal", "iphone", "ipad"}:
        raise SourcePortError("Source-port device must be universal, iphone, or ipad.")

    metadata = {
        "manifestPath": str(manifest_path.relative_to(payload_root)) if manifest_path else "auto-detected",
        "declaredFrameworks": frameworks,
    }
    return PortManifest(kind, app_name, bundle_id, minimum_ios, source_roots, resource_roots, frameworks, device, metadata)


def _collect_files(payload_root: Path, roots: Iterable[str], extensions: set[str] | None = None) -> list[Path]:
    files: list[Path] = []
    total = 0
    for root_name in roots:
        root = _safe_path(payload_root, root_name)
        if not root.is_dir() or root.is_symlink():
            raise SourcePortError(f"Declared source/resource root is missing or unsafe: {root_name}")
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise SourcePortError(f"Symlinks are not accepted in source-port inputs: {path.relative_to(payload_root)}")
            if not path.is_file():
                continue
            if extensions is not None and path.suffix.lower() not in extensions:
                continue
            size = path.stat().st_size
            if extensions is not None and size > MAX_SINGLE_FILE_BYTES:
                raise SourcePortError(f"Source-port file is too large: {path.relative_to(payload_root)}")
            total += size
            files.append(path)
    if extensions is not None:
        if not files:
            raise SourcePortError("No compilable source files were found in sourceRoots.")
        if len(files) > MAX_SOURCE_FILES or total > MAX_SOURCE_BYTES:
            raise SourcePortError("Source-port input exceeds the public source limits.")
    elif total > MAX_RESOURCE_BYTES:
        raise SourcePortError("Source-port resources exceed 50 MB.")
    return files


def _scan_and_rewrite(path: Path, text: str) -> tuple[str, list[str], list[str]]:
    blockers: list[str] = []
    rewrites: list[str] = []
    imports: list[str] = []
    suffix = path.suffix.lower()
    if suffix == ".swift":
        for old, new, note in SWIFT_REWRITES:
            if old in text:
                text = text.replace(old, new)
                rewrites.append(note)
        imports = re.findall(r"^\s*import\s+([A-Za-z_][A-Za-z0-9_]*)", text, re.M)
    elif suffix in {".m", ".mm", ".h", ".c"}:
        for old, new, note in OBJC_REWRITES:
            if old in text:
                text = text.replace(old, new)
                rewrites.append(note)
        imports = re.findall(r"^\s*#\s*(?:import|include)\s*[<\"]([A-Za-z_][A-Za-z0-9_]*)[/\">]", text, re.M)

    for module in imports:
        if module in PROHIBITED_IMPORTS:
            blockers.append(f"{path.name} imports jailbreak/private module {module}.")
    for pattern, reason in PROHIBITED_PATTERNS:
        if pattern.search(text):
            blockers.append(f"{path.name}: {reason}")
    return text, sorted(set(rewrites)), sorted(set(blockers))


def prepare_source_tree(payload_root: Path, manifest: PortManifest, destination: Path) -> dict[str, Any]:
    source_files = _collect_files(payload_root, manifest.source_roots, SOURCE_EXTENSIONS)
    destination.mkdir(parents=True, exist_ok=True)
    rewrites: list[str] = []
    blockers: list[str] = []
    compiled: list[Path] = []
    has_swift_main = False
    has_objc_main = False

    for source in source_files:
        text = source.read_text(encoding="utf-8")
        rewritten, file_rewrites, file_blockers = _scan_and_rewrite(source, text)
        rewrites.extend(file_rewrites)
        blockers.extend(file_blockers)
        relative = source.relative_to(payload_root)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rewritten, encoding="utf-8")
        if source.suffix.lower() in COMPILED_EXTENSIONS:
            compiled.append(target)
        if source.suffix.lower() == ".swift" and re.search(r"@main\b", rewritten):
            has_swift_main = True
        if source.name == "main.m" and re.search(r"\bUIApplicationMain\s*\(", rewritten):
            has_objc_main = True

    if blockers:
        raise SourcePortError("Source cannot be automatically ported: " + " | ".join(sorted(set(blockers))))
    if manifest.kind == "swiftui-app":
        if not has_swift_main:
            raise SourcePortError("Swift source port requires one @main application entry point.")
        shim = destination / "DebToIPACompat.swift"
        shim.write_text(SWIFT_SHIM, encoding="utf-8")
        compiled.append(shim)
    else:
        if not has_objc_main:
            raise SourcePortError("Objective-C source port requires main.m calling UIApplicationMain.")
        header = destination / "HBPreferences.h"
        implementation = destination / "DebToIPACompat.m"
        header.write_text(OBJC_SHIM_HEADER, encoding="utf-8")
        implementation.write_text(OBJC_SHIM_SOURCE, encoding="utf-8")
        compiled.append(implementation)

    return {
        "compiled": compiled,
        "rewrites": sorted(set(rewrites)),
        "sourceFiles": [str(path.relative_to(destination)) for path in compiled],
    }


def _discover_frameworks(manifest: PortManifest, prepared_files: list[Path]) -> list[str]:
    frameworks = set(manifest.frameworks)
    frameworks.update({"Foundation", "UIKit"})
    if manifest.kind == "swiftui-app":
        frameworks.add("SwiftUI")
    for path in prepared_files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if path.suffix.lower() == ".swift":
            modules = re.findall(r"^\s*import\s+([A-Za-z_][A-Za-z0-9_]*)", text, re.M)
        else:
            modules = re.findall(r"^\s*#\s*(?:import|include)\s*<([A-Za-z_][A-Za-z0-9_]*)/", text, re.M)
        for module in modules:
            if module in PUBLIC_FRAMEWORKS:
                frameworks.add(module)
            elif module not in {"Darwin", "Glibc", "ObjectiveC"}:
                raise SourcePortError(f"Source imports unsupported module {module}.")
    return sorted(frameworks)


def _copy_resources(payload_root: Path, roots: list[str], app_bundle: Path) -> list[str]:
    copied: list[str] = []
    _collect_files(payload_root, roots, None) if roots else []
    for root_name in roots:
        root = _safe_path(payload_root, root_name)
        for source in sorted(root.rglob("*")):
            if not source.is_file():
                continue
            relative = source.relative_to(root)
            target = app_bundle / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(relative.as_posix())
    return sorted(set(copied))


def _write_info_plist(app_bundle: Path, manifest: PortManifest, executable_name: str) -> None:
    family = {"iphone": [1], "ipad": [2], "universal": [1, 2]}[manifest.device]
    plist = {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleDisplayName": manifest.app_name,
        "CFBundleExecutable": executable_name,
        "CFBundleIdentifier": manifest.bundle_identifier,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": manifest.app_name[:16],
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1",
        "CFBundleSupportedPlatforms": ["iPhoneOS"],
        "LSRequiresIPhoneOS": True,
        "MinimumOSVersion": manifest.minimum_ios,
        "UIDeviceFamily": family,
        "UILaunchScreen": {},
    }
    (app_bundle / "Info.plist").write_bytes(plistlib.dumps(plist, fmt=plistlib.FMT_BINARY, sort_keys=False))


def _zip_payload(stage: Path, destination: Path) -> None:
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(stage.rglob("*")):
            relative = path.relative_to(stage).as_posix()
            if path.is_dir():
                continue
            info = zipfile.ZipInfo.from_file(path, relative, strict_timestamps=False)
            info.create_system = 3
            mode = path.stat().st_mode
            info.external_attr = (stat.S_IFREG | (mode & 0o777)) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())


def build_source_port(payload_root: Path, output_dir: Path, source_name: str, options: dict[str, Any]) -> dict[str, Any] | None:
    manifest = _read_manifest(payload_root, options)
    if manifest is None:
        return None
    if shutil.which("xcrun") is None:
        raise SourcePortError("Source-assisted conversion requires a macOS runner with Xcode.")

    with tempfile.TemporaryDirectory(prefix="debtoipa-source-port-") as temporary:
        workspace = Path(temporary)
        prepared_root = workspace / "prepared"
        prepared = prepare_source_tree(payload_root, manifest, prepared_root)
        compiled_files: list[Path] = prepared["compiled"]
        frameworks = _discover_frameworks(manifest, compiled_files)
        stage = workspace / "stage"
        app_bundle = stage / "Payload" / f"{re.sub(r'[^A-Za-z0-9_-]+', '', manifest.app_name) or 'PortedApp'}.app"
        app_bundle.mkdir(parents=True)
        executable_name = re.sub(r"[^A-Za-z0-9_-]+", "", manifest.app_name) or "PortedApp"
        executable = app_bundle / executable_name
        sdk = subprocess.check_output(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"], text=True).strip()
        target = f"arm64-apple-ios{manifest.minimum_ios}"

        if manifest.kind == "swiftui-app":
            command = [
                "xcrun", "--sdk", "iphoneos", "swiftc",
                "-parse-as-library", "-target", target, "-sdk", sdk,
                "-O", "-whole-module-optimization", "-emit-executable",
                *[str(path) for path in compiled_files], "-o", str(executable),
            ]
        else:
            command = [
                "xcrun", "--sdk", "iphoneos", "clang",
                "-target", target, "-isysroot", sdk, "-fobjc-arc", "-O2",
                "-I", str(prepared_root),
                *[str(path) for path in compiled_files if path.suffix.lower() in {".m", ".mm", ".c"}],
                "-o", str(executable),
            ]
        for framework in frameworks:
            command.extend(["-framework", framework])
        process = subprocess.run(command, text=True, capture_output=True)
        compiler_log = (process.stdout + "\n" + process.stderr).strip()
        if process.returncode:
            raise SourcePortError("Xcode could not compile the source port: " + compiler_log[-4000:])
        executable.chmod(0o755)
        _write_info_plist(app_bundle, manifest, executable_name)
        resources = _copy_resources(payload_root, manifest.resource_roots, app_bundle)

        output_dir.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(source_name).stem) or "Ported"
        ipa = output_dir / f"{stem}-SourcePort-unsigned.ipa"
        _zip_payload(stage, ipa)
        binary = executable.read_bytes()
        report = {
            "schemaVersion": 1,
            "resultKind": "source-ported",
            "kind": manifest.kind,
            "appName": manifest.app_name,
            "bundleIdentifier": manifest.bundle_identifier,
            "minimumIOS": manifest.minimum_ios,
            "device": manifest.device,
            "frameworks": frameworks,
            "rewrites": prepared["rewrites"],
            "sourceFiles": prepared["sourceFiles"],
            "resources": resources,
            "compiler": command[:4],
            "compilerLogTail": compiler_log[-2000:],
            "executable": executable_name,
            "executableSha256": hashlib.sha256(binary).hexdigest(),
            "ipa": ipa.name,
            "ipaSize": ipa.stat().st_size,
            "sourceDerived": True,
            "originalBinaryPackaged": False,
            "compileVerified": True,
            **manifest.metadata,
        }
        (output_dir / "source-port-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        return {"ipa": ipa, "report": report}
