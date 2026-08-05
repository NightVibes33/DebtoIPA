#!/usr/bin/env python3
"""Constrained package-provided source compiler for stock iOS.

Supported app kinds:
- swiftui-app
- uikit-swift-app
- uikit-objc-app
- mixed-app

The compiler never executes Makefiles, maintainer scripts, shell scripts, or
package-provided build tools. Only declared source/resources are copied, scanned,
rewritten through an audited rule set, and compiled with Apple's toolchain.
"""
from __future__ import annotations

import json
import os
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from typing import Any, Iterable

from adapter_sdk import write_adapter_sdk

MAX_SOURCE_FILES = 600
MAX_SOURCE_BYTES = 30 * 1024 * 1024
MAX_RESOURCE_BYTES = 80 * 1024 * 1024
MAX_SINGLE_FILE_BYTES = 4 * 1024 * 1024

SOURCE_EXTENSIONS = {".swift", ".m", ".mm", ".h", ".c", ".cc", ".cpp", ".hpp"}
COMPILED_EXTENSIONS = {".swift", ".m", ".mm", ".c", ".cc", ".cpp"}
KINDS = {"swiftui-app", "uikit-swift-app", "uikit-objc-app", "mixed-app"}
DEVICES = {"universal", "iphone", "ipad"}

PUBLIC_FRAMEWORKS = {
    "Accelerate", "AppIntents", "AVFoundation", "BackgroundTasks", "CloudKit", "Combine",
    "CoreData", "CoreGraphics", "CoreImage", "CoreLocation", "CoreML", "CoreMotion",
    "CoreNFC", "CryptoKit", "EventKit", "FileProvider", "Foundation", "HealthKit",
    "LocalAuthentication", "MapKit", "Metal", "Network", "NetworkExtension", "Photos",
    "PhotosUI", "SafariServices", "Security", "StoreKit", "SwiftUI", "UIKit",
    "UniformTypeIdentifiers", "UserNotifications", "Vision", "WebKit", "WidgetKit",
}

PROHIBITED_IMPORTS = {
    "Cephei", "CepheiPrefs", "CepheiPreferences", "CydiaSubstrate", "MobileSubstrate",
    "Substrate", "ElleKit", "libhooker", "RocketBootstrap", "SpringBoardServices",
    "BackBoardServices", "FrontBoard", "AssertionServices", "RunningBoardServices",
}

PROHIBITED_PATTERNS = [
    (re.compile(r"%\s*(?:hook|ctor|group|init|orig|new)\b", re.I), "Logos hooks cannot run in a normal app."),
    (re.compile(r"\b(?:MSHookFunction|MSHookMessageEx|LHHookFunctions|substitute_hook_functions)\b"), "Process injection APIs are unavailable."),
    (re.compile(r"\b(?:task_for_pid|ptrace|mach_vm_write|vm_write|setuid|setgid|launchctl)\b"), "Root or process-control behavior is unavailable."),
    (re.compile(r"/System/Library/PrivateFrameworks/"), "Private frameworks are not accepted."),
    (re.compile(r"\b(?:dlopen|dlsym)\s*\([^\n]*(?:SpringBoard|MobileSubstrate|ElleKit|libhooker)", re.I), "Dynamic jailbreak loader access is unavailable."),
    (re.compile(r"\b(?:fork|vfork|posix_spawn|system|popen)\s*\("), "External process execution is unavailable in the normal app sandbox."),
    (re.compile(r"\b(?:IOServiceOpen|IOConnectCall|host_get_special_port)\b"), "Privileged IOKit or host access is unavailable."),
]

SWIFT_REWRITES = [
    (re.compile(r"^\s*import\s+(?:Cephei|CepheiPrefs|CepheiPreferences)\s*$", re.M), "", "Removed Cephei import; generated preferences adapter is used."),
    (re.compile(r"\bHBPreferences\s*\(\s*identifier:\s*([^\)]+)\)"), r"DebToIPAPreferences(suiteName: \1)", "Replaced HBPreferences initializer."),
    (re.compile(r"\bHBPreferences\s*\(\s*\)"), "DebToIPAPreferences.shared", "Replaced HBPreferences singleton."),
    (re.compile(r"CFNotificationCenterGetDarwinNotifyCenter\s*\(\s*\)"), "CFNotificationCenterGetLocalCenter()", "Replaced Darwin notification center with local center."),
    (re.compile(r'"/(?:private/)?var/mobile/Documents([^"\\]*)"'), r'DebToIPASandboxPaths.documents("\1").path', "Mapped legacy Documents path."),
    (re.compile(r'"/(?:private/)?var/mobile/Library/Preferences"'), r'DTICompat.preferencesDirectory.path', "Mapped preferences path."),
    (re.compile(r'"/(?:private/)?var/mobile/Library/Preferences/([^"\\]+)"'), r'DebToIPASandboxPaths.applicationSupport("\1").path', "Mapped preferences path."),
    (re.compile(r'"/var/jb/var/mobile/Library([^"\\]*)"'), r'DebToIPASandboxPaths.applicationSupport("\1").path', "Mapped rootless jailbreak path."),
]

OBJC_REWRITES = [
    (re.compile(r"#\s*import\s*[<\"](?:Cephei|CepheiPrefs|CepheiPreferences)/HBPreferences\.h[>\"]"), '#import "HBPreferences.h"', "Replaced Cephei header with local adapter."),
    (re.compile(r"CFNotificationCenterGetDarwinNotifyCenter\s*\(\s*\)"), "CFNotificationCenterGetLocalCenter()", "Replaced Darwin notification center with local center."),
]


class SourcePortError(RuntimeError):
    pass


@dataclass
class PortManifest:
    schema_version: int
    kind: str
    app_name: str
    bundle_identifier: str
    minimum_ios: str
    device: str
    source_roots: list[str]
    resource_roots: list[str]
    frameworks: list[str] = field(default_factory=list)
    requested_alternatives: list[str] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)
    app_group: str | None = None
    background_identifiers: list[str] = field(default_factory=list)
    preference_keys: list[dict[str, Any]] = field(default_factory=list)
    companion_service: bool = False


MANIFEST_LOCATIONS = [
    "usr/share/debtoipa/PortManifest.json",
    "DebToIPA/PortManifest.json",
    "Library/DebToIPA/PortManifest.json",
    "var/jb/Library/DebToIPA/PortManifest.json",
]

SOURCE_ROOT_CANDIDATES = [
    "usr/share/debtoipa/Sources",
    "DebToIPA/Sources",
    "Library/DebToIPA/Sources",
    "var/jb/Library/DebToIPA/Sources",
]


def _safe_path(root: Path, relative: str) -> Path:
    if not relative or relative.startswith("/") or "\0" in relative:
        raise SourcePortError(f"Unsafe package path: {relative!r}")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise SourcePortError(f"Package path escapes payload root: {relative}") from error
    return candidate


def _read_manifest(payload_root: Path, options: dict[str, Any]) -> PortManifest | None:
    raw: dict[str, Any] | None = None
    for location in MANIFEST_LOCATIONS:
        path = _safe_path(payload_root, location)
        if path.is_file():
            try:
                parsed = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                raise SourcePortError(f"Invalid source-port manifest: {error}") from error
            if not isinstance(parsed, dict):
                raise SourcePortError("PortManifest.json must contain a JSON object.")
            raw = parsed
            break

    if raw is None:
        roots = [root for root in SOURCE_ROOT_CANDIDATES if _safe_path(payload_root, root).is_dir()]
        if not roots:
            return None
        source_files = [path for root in roots for path in _safe_path(payload_root, root).rglob("*") if path.suffix.lower() in SOURCE_EXTENSIONS]
        has_swift = any(path.suffix.lower() == ".swift" for path in source_files)
        has_objc = any(path.suffix.lower() in {".m", ".mm", ".h"} for path in source_files)
        kind = "mixed-app" if has_swift and has_objc else "swiftui-app" if has_swift else "uikit-objc-app"
        raw = {
            "schemaVersion": 2,
            "kind": kind,
            "appName": options.get("displayName") or Path(str(options.get("sourceName") or "Converted")).stem,
            "bundleIdentifier": options.get("bundleId") or "app.debtoipa.converted",
            "minimumIOS": options.get("minimumIos") or "15.0",
            "device": options.get("device") or "universal",
            "sourceRoots": roots,
            "resourceRoots": [],
            "requestedAlternatives": options.get("requestedAlternatives") or [],
            "extensions": [],
        }

    schema = int(raw.get("schemaVersion") or 0)
    if schema not in {1, 2}:
        raise SourcePortError("PortManifest schemaVersion must be 1 or 2.")
    kind = str(raw.get("kind") or "")
    if kind not in KINDS:
        raise SourcePortError(f"Unsupported source-port kind: {kind!r}")
    app_name = str(options.get("displayName") or raw.get("appName") or "Converted App")[:80]
    bundle_id = str(options.get("bundleId") or raw.get("bundleIdentifier") or "app.debtoipa.converted")
    minimum_ios = str(options.get("minimumIos") or raw.get("minimumIOS") or "15.0")
    device = str(options.get("device") or raw.get("device") or "universal")
    if not re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", bundle_id):
        raise SourcePortError("Source-port bundle identifier is invalid.")
    if not re.fullmatch(r"\d{1,2}(?:\.\d{1,2}){0,2}", minimum_ios):
        raise SourcePortError("Source-port minimum iOS version is invalid.")
    if device not in DEVICES:
        raise SourcePortError("Source-port device must be universal, iphone, or ipad.")

    def string_list(key: str) -> list[str]:
        value = raw.get(key) or []
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise SourcePortError(f"{key} must be an array of strings.")
        return list(dict.fromkeys(value))

    alternatives = string_list("requestedAlternatives")
    option_alternatives = options.get("requestedAlternatives") or []
    if isinstance(option_alternatives, list):
        alternatives = list(dict.fromkeys(alternatives + [str(value) for value in option_alternatives]))
    extensions = string_list("extensions")
    for alternative, extension in {
        "widget-extension": "widget",
        "share-extension": "share",
        "safari-web-extension": "safari",
        "content-blocker": "content-blocker",
        "network-extension": "network",
        "file-provider": "file-provider",
    }.items():
        if alternative in alternatives and extension not in extensions:
            extensions.append(extension)

    preference_keys = raw.get("preferenceKeys") or []
    if not isinstance(preference_keys, list) or not all(isinstance(item, dict) for item in preference_keys):
        raise SourcePortError("preferenceKeys must be an array of objects.")

    frameworks = string_list("frameworks")
    unknown_frameworks = set(frameworks) - PUBLIC_FRAMEWORKS
    if unknown_frameworks:
        raise SourcePortError("Manifest requests unsupported or private frameworks: " + ", ".join(sorted(unknown_frameworks)))

    return PortManifest(
        schema_version=schema,
        kind=kind,
        app_name=app_name,
        bundle_identifier=bundle_id,
        minimum_ios=minimum_ios,
        device=device,
        source_roots=string_list("sourceRoots"),
        resource_roots=string_list("resourceRoots"),
        frameworks=frameworks,
        requested_alternatives=alternatives,
        extensions=extensions,
        app_group=str(raw.get("appGroup") or f"group.{bundle_id}") if ("share" in extensions or raw.get("appGroup")) else None,
        background_identifiers=string_list("backgroundIdentifiers"),
        preference_keys=preference_keys,
        companion_service=bool(raw.get("companionService")) or "companion-service" in alternatives,
    )


def _collect_files(payload_root: Path, roots: Iterable[str], extensions: set[str] | None) -> list[Path]:
    files: list[Path] = []
    total = 0
    for root_name in roots:
        root = _safe_path(payload_root, root_name)
        if not root.is_dir():
            raise SourcePortError(f"Declared source/resource root is missing: {root_name}")
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
            raise SourcePortError("No compilable source files were found.")
        if len(files) > MAX_SOURCE_FILES or total > MAX_SOURCE_BYTES:
            raise SourcePortError("Source-port input exceeds source limits.")
    elif total > MAX_RESOURCE_BYTES:
        raise SourcePortError("Source-port resources exceed 80 MB.")
    return files


def _scan_and_rewrite(path: Path, text: str) -> tuple[str, list[str], list[str]]:
    blockers: list[str] = []
    rewrites: list[str] = []
    imports: list[str] = []
    suffix = path.suffix.lower()
    if suffix == ".swift":
        for pattern, replacement, note in SWIFT_REWRITES:
            new_text, count = pattern.subn(replacement, text)
            if count:
                text = new_text
                rewrites.append(note)
        imports = re.findall(r"^\s*import\s+([A-Za-z_][A-Za-z0-9_]*)", text, re.M)
    else:
        for pattern, replacement, note in OBJC_REWRITES:
            new_text, count = pattern.subn(replacement, text)
            if count:
                text = new_text
                rewrites.append(note)
        imports = re.findall(r"^\s*#\s*(?:import|include)\s*[<\"]([A-Za-z_][A-Za-z0-9_]*)[/\">]", text, re.M)

    for module in imports:
        if module in PROHIBITED_IMPORTS:
            blockers.append(f"{path.name} imports jailbreak/private module {module}.")
    for pattern, reason in PROHIBITED_PATTERNS:
        if pattern.search(text):
            blockers.append(f"{path.name}: {reason}")
    return text, sorted(set(rewrites)), sorted(set(blockers))


def _prepare_source_tree(payload_root: Path, manifest: PortManifest, destination: Path) -> dict[str, Any]:
    source_files = _collect_files(payload_root, manifest.source_roots, SOURCE_EXTENSIONS)
    destination.mkdir(parents=True, exist_ok=True)
    rewrites: list[str] = []
    blockers: list[str] = []
    compiled: list[Path] = []
    has_swift_main = False
    has_objc_main = False

    for source in source_files:
        text = source.read_text(encoding="utf-8", errors="strict")
        rewritten, file_rewrites, file_blockers = _scan_and_rewrite(source, text)
        rewrites.extend(file_rewrites)
        blockers.extend(file_blockers)
        relative = source.resolve().relative_to(payload_root.resolve())
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
    if manifest.kind in {"swiftui-app", "uikit-swift-app"} and not has_swift_main:
        raise SourcePortError("Swift source port requires an @main application entry point.")
    if manifest.kind == "uikit-objc-app" and not has_objc_main:
        raise SourcePortError("Objective-C source port requires main.m calling UIApplicationMain.")
    if manifest.kind == "mixed-app" and not (has_swift_main or has_objc_main):
        raise SourcePortError("Mixed source port requires a Swift @main or Objective-C UIApplicationMain entry point.")

    adapter_root = destination / "GeneratedAdapters"
    adapter_manifest = write_adapter_sdk(
        adapter_root,
        bundle_id=manifest.bundle_identifier,
        app_name=manifest.app_name,
        alternatives=manifest.requested_alternatives,
        app_group=manifest.app_group,
    )
    if any(path.suffix.lower() == ".swift" for path in compiled):
        compiled.extend(sorted((adapter_root / "Swift").glob("*.swift")))
    if any(path.suffix.lower() in {".m", ".mm", ".c", ".cc", ".cpp"} for path in compiled):
        compiled.extend([adapter_root / "ObjectiveC/HBPreferences.m", adapter_root / "ObjectiveC/SandboxInterpose.m"])

    return {
        "compiled": compiled,
        "rewrites": sorted(set(rewrites)),
        "sourceFiles": [str(path.relative_to(destination)) for path in compiled],
        "adapterRoot": adapter_root,
        "adapterManifest": adapter_manifest,
    }


def _discover_frameworks(manifest: PortManifest, prepared_files: list[Path]) -> list[str]:
    frameworks = set(manifest.frameworks)
    frameworks.update({"Foundation", "UIKit"})
    if manifest.kind == "swiftui-app":
        frameworks.add("SwiftUI")
    if any(value in manifest.requested_alternatives for value in {"background-task", "background-transfer"}):
        frameworks.add("BackgroundTasks")
    if "app-intents" in manifest.requested_alternatives:
        frameworks.add("AppIntents")
    for path in prepared_files:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if path.suffix.lower() == ".swift":
            modules = re.findall(r"^\s*import\s+([A-Za-z_][A-Za-z0-9_]*)", text, re.M)
        else:
            modules = re.findall(r"^\s*#\s*(?:import|include)\s*<([A-Za-z_][A-Za-z0-9_]*)/", text, re.M)
        for module in modules:
            if module in PUBLIC_FRAMEWORKS:
                frameworks.add(module)
            elif module not in {
      "Darwin", "Glibc", "ObjectiveC",
      "arpa", "dispatch", "mach", "net", "netinet", "objc", "os", "sys",
  }:
                raise SourcePortError(f"Source imports unsupported module {module}.")
    unknown = frameworks - PUBLIC_FRAMEWORKS
    if unknown:
        raise SourcePortError("Manifest requests unsupported frameworks: " + ", ".join(sorted(unknown)))
    return sorted(frameworks)


def _copy_resources(payload_root: Path, roots: list[str], app_bundle: Path) -> list[str]:
    copied: list[str] = []
    if not roots:
        return copied
    _collect_files(payload_root, roots, None)
    for root_name in roots:
        root = _safe_path(payload_root, root_name)
        for source in sorted(root.rglob("*")):
            if not source.is_file() or source.is_symlink():
                continue
            relative = source.relative_to(root)
            target = app_bundle / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(relative.as_posix())
    return copied


def _xcode_tools() -> tuple[str, str, str]:
    if shutil.which("xcrun") is None:
        raise SourcePortError("Xcode is required for source-assisted conversion.")
    sdk = subprocess.check_output(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"], text=True).strip()
    swiftc = subprocess.check_output(["xcrun", "--sdk", "iphoneos", "--find", "swiftc"], text=True).strip()
    clang = subprocess.check_output(["xcrun", "--sdk", "iphoneos", "--find", "clang"], text=True).strip()
    return sdk, swiftc, clang


def _compile_objc_objects(files: list[Path], build: Path, sdk: str, clang: str, target: str, include_paths: list[Path]) -> list[Path]:
    objects: list[Path] = []
    for index, source in enumerate(files):
        output = build / f"objc-{index}.o"
        command = [clang, "-target", target, "-isysroot", sdk, "-fobjc-arc", "-fmodules", "-c", str(source), "-o", str(output)]
        if source.suffix.lower() in {".mm", ".cc", ".cpp"}:
            command.extend(["-std=c++17"])
        for path in include_paths:
            command.extend(["-I", str(path)])
        subprocess.run(command, check=True)
        objects.append(output)
    return objects


def _compile_app(prepared: dict[str, Any], manifest: PortManifest, app_bundle: Path) -> dict[str, Any]:
    sdk, swiftc, clang = _xcode_tools()
    target = f"arm64-apple-ios{manifest.minimum_ios}"
    files: list[Path] = prepared["compiled"]
    swift_files = [path for path in files if path.suffix.lower() == ".swift"]
    native_files = [path for path in files if path.suffix.lower() in {".m", ".mm", ".c", ".cc", ".cpp"}]
    include_paths = sorted({path.parent for path in files if path.suffix.lower() in {".h", ".m", ".mm"}} | {prepared["adapterRoot"] / "ObjectiveC"})
    frameworks = _discover_frameworks(manifest, files)
    executable = app_bundle / re.sub(r"[^A-Za-z0-9_-]+", "", manifest.app_name)[:60]
    if not executable.name:
        executable = app_bundle / "ConvertedApp"
    build = app_bundle.parent / "CompileObjects"
    build.mkdir(parents=True, exist_ok=True)
    objects = _compile_objc_objects(native_files, build, sdk, clang, target, include_paths) if native_files else []
    framework_args = [item for framework in frameworks for item in ("-framework", framework)]

    if swift_files:
        command = [
            swiftc, "-target", target, "-sdk", sdk, "-parse-as-library", "-O",
            "-Xlinker", "-dead_strip", "-o", str(executable),
            *map(str, swift_files), *map(str, objects), *framework_args,
        ]
        for path in include_paths:
            command.extend(["-Xcc", f"-I{path}"])
        subprocess.run(command, check=True)
        compiler = "swiftc"
    else:
        command = [clang, "-target", target, "-isysroot", sdk, "-fobjc-arc", "-Wl,-dead_strip", "-o", str(executable), *map(str, objects), *framework_args]
        if any(path.suffix.lower() in {".mm", ".cc", ".cpp"} for path in native_files):
            command.append("-lc++")
        subprocess.run(command, check=True)
        compiler = "clang"
    os.chmod(executable, 0o755)
    return {"executable": executable, "compiler": compiler, "frameworks": frameworks, "target": target}


def _extension_info(kind: str, bundle_id: str, executable: str, app_group: str | None) -> dict[str, Any]:
    base: dict[str, Any] = {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleExecutable": executable,
        "CFBundleIdentifier": bundle_id,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": executable,
        "CFBundlePackageType": "XPC!",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1",
    }
    if kind == "widget":
        base["NSExtension"] = {"NSExtensionPointIdentifier": "com.apple.widgetkit-extension"}
    elif kind == "share":
        base["NSExtension"] = {
            "NSExtensionPointIdentifier": "com.apple.share-services",
            "NSExtensionPrincipalClass": "DebToIPAShareViewController",
            "NSExtensionAttributes": {"NSExtensionActivationRule": {"NSExtensionActivationSupportsText": True, "NSExtensionActivationSupportsFileWithMaxCount": 10}},
        }
    elif kind == "safari":
        base["NSExtension"] = {"NSExtensionPointIdentifier": "com.apple.Safari.web-extension", "NSExtensionPrincipalClass": "SafariWebExtensionHandler"}
    elif kind == "content-blocker":
        base["NSExtension"] = {"NSExtensionPointIdentifier": "com.apple.Safari.content-blocker", "NSExtensionPrincipalClass": "ContentBlockerRequestHandler"}
    elif kind == "network":
        base["NSExtension"] = {"NSExtensionPointIdentifier": "com.apple.networkextension.packet-tunnel", "NSExtensionPrincipalClass": "DebToIPAPacketTunnelProvider"}
    elif kind == "file-provider":
        base["NSExtension"] = {"NSExtensionPointIdentifier": "com.apple.fileprovider-nonui", "NSExtensionPrincipalClass": "DebToIPAFileProviderExtension"}
    if app_group:
        base["DebToIPAAppGroup"] = app_group
    return base


def _compile_extensions(prepared: dict[str, Any], manifest: PortManifest, app_bundle: Path) -> list[dict[str, Any]]:
    if not manifest.extensions:
        return []
    sdk, swiftc, _ = _xcode_tools()
    target = f"arm64-apple-ios{manifest.minimum_ios}"
    plugins = app_bundle / "PlugIns"
    plugins.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    extension_root: Path = prepared["adapterRoot"] / "Extensions"
    source_map = {
        "widget": extension_root / "Widget/Widget.swift",
        "share": extension_root / "Share/ShareViewController.swift",
        "safari": extension_root / "Safari/SafariWebExtensionHandler.swift",
        "network": extension_root / "Network/DebToIPAPacketTunnelProvider.swift",
        "file-provider": extension_root / "FileProvider/DebToIPAFileProviderExtension.swift",
        "content-blocker": extension_root / "ContentBlocker/ContentBlockerRequestHandler.swift",
    }
    frameworks_map = {
        "widget": ["WidgetKit", "SwiftUI", "Foundation"],
        "share": ["UIKit", "UniformTypeIdentifiers", "Foundation"],
        "safari": ["SafariServices", "Foundation"],
        "network": ["NetworkExtension", "Foundation"],
        "file-provider": ["FileProvider", "Foundation"],
        "content-blocker": ["Foundation"],
    }
    for kind in manifest.extensions:
        source = source_map.get(kind)
        if source is None or not source.is_file():
            raise SourcePortError(f"Generated source for {kind} extension is missing.")
        executable = f"DebToIPA{kind.title().replace('-', '')}Extension"
        appex = plugins / f"{executable}.appex"
        appex.mkdir()
        command = [swiftc, "-target", target, "-sdk", sdk, "-application-extension", "-parse-as-library", "-O"]
        if kind != "widget":
            command.extend(["-emit-library", "-module-name", executable])
        command.extend(["-o", str(appex / executable), str(source)])
        for framework in frameworks_map[kind]:
            command.extend(["-framework", framework])
        subprocess.run(command, check=True)
        if kind == "content-blocker":
            shutil.copy2(extension_root / "ContentBlocker/blockerList.json", appex / "blockerList.json")
        elif kind == "safari":
            shutil.copy2(extension_root / "Safari/manifest.json", appex / "manifest.json")
        os.chmod(appex / executable, 0o755)
        bundle_id = f"{manifest.bundle_identifier}.{kind.replace('-', '')}"
        info = _extension_info(kind, bundle_id, executable, manifest.app_group)
        (appex / "Info.plist").write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY, sort_keys=False))
        results.append({"kind": kind, "bundleIdentifier": bundle_id, "path": appex.relative_to(app_bundle).as_posix(), "executable": executable})
    return results


def _build_info_plist(manifest: PortManifest, executable: str) -> dict[str, Any]:
    info: dict[str, Any] = {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleDisplayName": manifest.app_name,
        "CFBundleExecutable": executable,
        "CFBundleIdentifier": manifest.bundle_identifier,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": manifest.app_name,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1",
        "LSRequiresIPhoneOS": True,
        "MinimumOSVersion": manifest.minimum_ios,
        "UILaunchScreen": {},
        "UIDeviceFamily": [1, 2] if manifest.device == "universal" else [1] if manifest.device == "iphone" else [2],
        "UISupportedInterfaceOrientations": ["UIInterfaceOrientationPortrait", "UIInterfaceOrientationLandscapeLeft", "UIInterfaceOrientationLandscapeRight"],
    }
    background_modes: list[str] = []
    if any(value in manifest.requested_alternatives for value in {"background-task", "background-transfer"}):
        identifiers = manifest.background_identifiers or [f"{manifest.bundle_identifier}.refresh", f"{manifest.bundle_identifier}.processing"]
        info["BGTaskSchedulerPermittedIdentifiers"] = identifiers
        background_modes.extend(["fetch", "processing"])
    if "push-notifications" in manifest.requested_alternatives:
        background_modes.append("remote-notification")
    if background_modes:
        info["UIBackgroundModes"] = list(dict.fromkeys(background_modes))
    if "url-schemes" in manifest.requested_alternatives:
        scheme = re.sub(r"[^a-z0-9+.-]", "", manifest.bundle_identifier.lower().replace(".", "-"))[:60] or "debtoipa"
        info["CFBundleURLTypes"] = [{"CFBundleURLName": manifest.bundle_identifier, "CFBundleURLSchemes": [scheme]}]
    return info


def _zip_payload(root: Path, destination: Path) -> None:
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                info = zipfile.ZipInfo(relative)
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, os.readlink(path))
            elif path.is_file():
                info = zipfile.ZipInfo.from_file(path, relative, strict_timestamps=False)
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, path.read_bytes())


prepare_source_tree = _prepare_source_tree


def build_source_port(payload_root: Path, output_directory: Path, source_name: str, options: dict[str, Any]) -> dict[str, Any] | None:
    manifest = _read_manifest(payload_root, options)
    if manifest is None:
        return None
    output_directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="debtoipa-source-port-") as temporary:
        stage = Path(temporary)
        prepared = _prepare_source_tree(payload_root, manifest, stage / "Prepared")
        payload = stage / "Package/Payload"
        payload.mkdir(parents=True)
        app_name = re.sub(r"[^A-Za-z0-9_-]+", "", manifest.app_name)[:60] or "ConvertedApp"
        app_bundle = payload / f"{app_name}.app"
        app_bundle.mkdir()
        compile_result = _compile_app(prepared, manifest, app_bundle)
        resources = _copy_resources(payload_root, manifest.resource_roots, app_bundle)
        extensions = _compile_extensions(prepared, manifest, app_bundle)
        info = _build_info_plist(manifest, compile_result["executable"].name)
        (app_bundle / "Info.plist").write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY, sort_keys=False))

        destination = output_directory / f"{Path(source_name).stem}-SourcePort-unsigned.ipa"
        package_root = stage / "Package"
        if shutil.which("ditto"):
            subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", "Payload", str(destination)], cwd=package_root, check=True)
        else:
            _zip_payload(package_root, destination)

        adapter_output = output_directory / "GeneratedAdapters"
        shutil.copytree(prepared["adapterRoot"], adapter_output, dirs_exist_ok=True)
        if manifest.companion_service and (prepared["adapterRoot"] / "CompanionService").is_dir():
            shutil.copytree(prepared["adapterRoot"] / "CompanionService", output_directory / "CompanionService", dirs_exist_ok=True)

        report: dict[str, Any] = {
            "schemaVersion": 2,
            "resultKind": "source-ported",
            "kind": manifest.kind,
            "appName": manifest.app_name,
            "bundleIdentifier": manifest.bundle_identifier,
            "minimumIOS": manifest.minimum_ios,
            "device": manifest.device,
            "compiler": compile_result["compiler"],
            "target": compile_result["target"],
            "frameworks": compile_result["frameworks"],
            "sourceFiles": prepared["sourceFiles"],
            "rewrites": prepared["rewrites"],
            "requestedAlternatives": manifest.requested_alternatives,
            "adapterManifest": prepared["adapterManifest"],
            "resources": resources,
            "extensions": extensions,
            "companionServiceGenerated": manifest.companion_service,
            "stockIOSCompileVerified": True,
            "behavioralParityVerified": False,
            "limitations": [
                "Successful compilation proves ARM64 iPhoneOS compatibility and bundle structure, not exact behavioral parity.",
                "Extensions, push, App Groups, Network Extension, File Provider, and other capabilities require appropriate signing entitlements.",
                "Root access, process injection, private entitlements, kernel access, and unrestricted continuous daemons are not reproduced.",
            ],
        }
        (output_directory / "source-port-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        return {"ipa": destination, "report": report}
