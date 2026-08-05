#!/usr/bin/env python3
"""Static capability analysis and stock-iOS alternative planning for DebToIPA.

The analyzer never executes package code. It inspects extracted payload paths,
source text, Mach-O load commands, and embedded metadata, then produces an
explicit conversion plan. A plan distinguishes automatic replacements from
source-required redesigns and capabilities that stock iOS cannot provide.
"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

MACHO_MAGICS = {
    b"\xcf\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xce",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf",
    b"\xbf\xba\xfe\xca",
}

TEXT_SUFFIXES = {
    ".swift", ".m", ".mm", ".h", ".c", ".cc", ".cpp", ".hpp",
    ".plist", ".json", ".xml", ".strings", ".entitlements", ".xm", ".x",
    ".sh", ".py", ".js", ".ts",
}

PROFILE_ORDER = [
    "direct-ipa",
    "binary-shims",
    "source-rebuild",
    "app-extensions",
    "background-replacement",
    "companion-service",
    "report-only",
]


@dataclass(frozen=True)
class Alternative:
    id: str
    title: str
    fidelity: str
    automation: str
    requires_source: bool = False
    requires_entitlement: str | None = None
    notes: str = ""


@dataclass
class Capability:
    id: str
    title: str
    severity: str
    evidence: list[str] = field(default_factory=list)
    alternatives: list[Alternative] = field(default_factory=list)
    selected_alternative: str | None = None
    stock_ios_status: str = "unknown"


@dataclass
class Profile:
    id: str
    title: str
    score: int
    usable: bool
    reason: str
    retained_functionality: int
    requires_real_device_test: bool = True


@dataclass
class CapabilityGraph:
    schemaVersion: int
    packageRoot: str
    facts: dict[str, Any]
    capabilities: list[Capability]
    profiles: list[Profile]
    recommendedProfile: str
    requestedProfile: str
    requestedAlternatives: list[str]
    expectedRetainedFunctionality: int
    hardBlockers: list[str]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ALTERNATIVES: dict[str, list[Alternative]] = {
    "cephei-preferences": [
        Alternative(
            "preferences-adapter",
            "Sandboxed preferences adapter",
            "high",
            "automatic",
            notes="Maps common HBPreferences methods to UserDefaults or an App Group suite.",
        ),
        Alternative(
            "settings-screen",
            "Native settings screen",
            "high",
            "generated",
            requires_source=True,
            notes="Generates a SwiftUI/UIKit settings surface from declared preference keys.",
        ),
    ],
    "root-paths": [
        Alternative(
            "sandbox-path-adapter",
            "Sandbox path adapter",
            "medium",
            "automatic",
            notes="Maps common /var/mobile paths into Documents, Library, Application Support, and Caches.",
        ),
        Alternative(
            "document-picker",
            "Document picker access",
            "high",
            "generated",
            requires_source=True,
            notes="Uses user-selected security-scoped files instead of unrestricted filesystem access.",
        ),
        Alternative(
            "file-provider",
            "File Provider extension",
            "high",
            "generated",
            requires_source=True,
            requires_entitlement="com.apple.developer.fileprovider.testing-mode",
            notes="Requires Apple-approved File Provider capabilities for distribution.",
        ),
    ],
    "darwin-notifications": [
        Alternative(
            "notification-adapter",
            "In-app notification adapter",
            "high",
            "automatic",
            notes="Maps same-process events to NotificationCenter and App Group state.",
        ),
        Alternative(
            "push-notifications",
            "Push-triggered synchronization",
            "medium",
            "generated",
            requires_source=True,
            requires_entitlement="aps-environment",
        ),
    ],
    "launch-daemon": [
        Alternative(
            "background-task",
            "BGTaskScheduler replacement",
            "medium",
            "generated",
            requires_source=True,
            notes="Work is opportunistic and time-limited; it is not a continuously running daemon.",
        ),
        Alternative(
            "background-transfer",
            "Background URLSession",
            "high",
            "generated",
            requires_source=True,
            notes="Best replacement for uploads, downloads, and network synchronization.",
        ),
        Alternative(
            "companion-service",
            "Companion web service",
            "medium",
            "generated",
            notes="Moves continuous or scheduled server-safe work off-device.",
        ),
    ],
    "springboard-hook": [
        Alternative(
            "widget-extension",
            "Widget or Live Activity",
            "medium",
            "generated",
            requires_source=True,
            notes="Replaces glanceable SpringBoard UI without process injection.",
        ),
        Alternative(
            "standalone-ui",
            "Standalone application UI",
            "medium",
            "generated",
            requires_source=True,
        ),
    ],
    "cross-app-injection": [
        Alternative(
            "share-extension",
            "Share extension",
            "medium",
            "generated",
            requires_source=True,
        ),
        Alternative(
            "app-intents",
            "App Intents and Shortcuts",
            "medium",
            "generated",
            requires_source=True,
        ),
        Alternative(
            "url-schemes",
            "Universal links and URL schemes",
            "low",
            "generated",
            requires_source=True,
        ),
    ],
    "preference-bundle": [
        Alternative(
            "settings-screen",
            "In-app settings screen",
            "high",
            "generated",
            requires_source=True,
        ),
    ],
    "command-line-tools": [
        Alternative(
            "native-library",
            "Compile tool logic into the app",
            "high",
            "generated",
            requires_source=True,
        ),
        Alternative(
            "app-intents",
            "App Intents and Shortcuts",
            "medium",
            "generated",
            requires_source=True,
        ),
        Alternative(
            "companion-service",
            "Companion web service",
            "medium",
            "generated",
        ),
    ],
    "safari-injection": [
        Alternative(
            "safari-web-extension",
            "Safari Web Extension",
            "high",
            "generated",
            requires_source=True,
        ),
        Alternative(
            "content-blocker",
            "Safari content blocker",
            "high",
            "generated",
            requires_source=True,
        ),
    ],
    "network-filter": [
        Alternative(
            "network-extension",
            "Network Extension",
            "high",
            "generated",
            requires_source=True,
            requires_entitlement="com.apple.developer.networking.networkextension",
            notes="Requires Apple approval for many Network Extension modes.",
        ),
        Alternative(
            "local-proxy",
            "In-app local proxy",
            "low",
            "generated",
            requires_source=True,
        ),
    ],
    "private-entitlements": [
        Alternative(
            "public-api-redesign",
            "Public API redesign",
            "variable",
            "manual",
            requires_source=True,
            notes="Private entitlements cannot be granted to a normal third-party app.",
        ),
    ],
    "private-frameworks": [
        Alternative(
            "public-api-redesign",
            "Public framework replacement",
            "variable",
            "manual",
            requires_source=True,
        ),
    ],
    "root-process-control": [
        Alternative(
            "companion-service",
            "Companion service for permitted work",
            "low",
            "generated",
            notes="Root process control itself has no stock-iOS equivalent.",
        ),
    ],
}

CAPABILITY_TITLES = {
    "cephei-preferences": "Cephei / HBPreferences",
    "root-paths": "Root or global filesystem paths",
    "darwin-notifications": "Darwin cross-process notifications",
    "launch-daemon": "Launch daemon or continuous background service",
    "springboard-hook": "SpringBoard or system UI injection",
    "cross-app-injection": "Cross-app process injection",
    "preference-bundle": "Jailbreak preference bundle",
    "command-line-tools": "Command-line helper executables",
    "safari-injection": "Safari injection",
    "network-filter": "System-wide network filtering",
    "private-entitlements": "Private or unavailable entitlements",
    "private-frameworks": "Private frameworks",
    "root-process-control": "Root/process-control behavior",
}

PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("cephei-preferences", re.compile(r"\b(?:HBPreferences|Cephei(?:Prefs|Preferences)?)\b", re.I), "warning"),
    ("root-paths", re.compile(r"/(?:var/(?:jb/)?mobile|private/var|Library/MobileSubstrate|Applications)/", re.I), "warning"),
    ("darwin-notifications", re.compile(r"CFNotificationCenterGetDarwinNotifyCenter|rocketbootstrap|notify_(?:post|register)", re.I), "warning"),
    ("springboard-hook", re.compile(r"SpringBoard|SB[A-Z][A-Za-z0-9_]+|%hook\s+SB|com\.apple\.springboard", re.I), "blocker"),
    ("cross-app-injection", re.compile(r"MobileSubstrate|CydiaSubstrate|ElleKit|libhooker|SubstrateLoader|MSHook", re.I), "blocker"),
    ("safari-injection", re.compile(r"MobileSafari|SafariServices.*private|com\.apple\.mobilesafari", re.I), "warning"),
    ("network-filter", re.compile(r"NEPacketTunnelProvider|NEFilterDataProvider|com\.apple\.networkextension|pfctl", re.I), "warning"),
    ("private-frameworks", re.compile(r"/System/Library/PrivateFrameworks/|#\s*import\s*<[^>]*Private", re.I), "blocker"),
    ("root-process-control", re.compile(r"\b(?:task_for_pid|ptrace|posix_spawn|fork\s*\(|kill\s*\(|setuid|setgid|launchctl)\b", re.I), "blocker"),
]

PRIVATE_ENTITLEMENT_PREFIXES = (
    "com.apple.private.",
    "com.apple.system.",
    "com.apple.springboard.",
    "platform-application",
    "get-task-allow",
    "task_for_pid-allow",
    "dynamic-codesigning",
)


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def _is_macho(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size >= 4 and path.read_bytes()[:4] in MACHO_MAGICS
    except OSError:
        return False


def _run_text(command: list[str]) -> str:
    try:
        return subprocess.check_output(command, text=True, stderr=subprocess.DEVNULL, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""


def _read_text(path: Path, limit: int = 2_000_000) -> str:
    try:
        if path.stat().st_size > limit:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _add_evidence(found: dict[str, tuple[str, list[str]]], cap: str, severity: str, evidence: str) -> None:
    current = found.get(cap)
    if current is None:
        found[cap] = (severity, [evidence])
        return
    old_severity, items = current
    if evidence not in items and len(items) < 20:
        items.append(evidence)
    severity_rank = {"info": 0, "warning": 1, "blocker": 2}
    found[cap] = (severity if severity_rank[severity] > severity_rank[old_severity] else old_severity, items)


def _inspect_entitlements(path: Path, root: Path, found: dict[str, tuple[str, list[str]]]) -> None:
    if path.suffix.lower() not in {".plist", ".entitlements"}:
        return
    try:
        value = plistlib.loads(path.read_bytes())
    except Exception:
        return
    if not isinstance(value, dict):
        return
    for key, enabled in value.items():
        text = str(key)
        if enabled and any(text.startswith(prefix) or text == prefix for prefix in PRIVATE_ENTITLEMENT_PREFIXES):
            _add_evidence(found, "private-entitlements", "blocker", f"{_safe_relative(path, root)}: {text}")


def _inspect_macho(path: Path, root: Path, found: dict[str, tuple[str, list[str]]], dependencies: list[dict[str, Any]]) -> None:
    relative = _safe_relative(path, root)
    linked: list[str] = []
    if shutil.which("otool"):
        output = _run_text(["otool", "-L", str(path)])
        for line in output.splitlines()[1:]:
            value = line.strip().split(" (", 1)[0]
            if value:
                linked.append(value)
    strings = ""
    if shutil.which("strings") and path.stat().st_size <= 80 * 1024 * 1024:
        strings = _run_text(["strings", "-a", str(path)])
    dependencies.append({"path": relative, "linkedLibraries": linked[:100]})
    combined = "\n".join(linked) + "\n" + strings
    for cap, pattern, severity in PATTERNS:
        match = pattern.search(combined)
        if match:
            _add_evidence(found, cap, severity, f"{relative}: {match.group(0)[:160]}")


def _iter_files(root: Path) -> Iterable[Path]:
    count = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            continue
        if path.is_file():
            count += 1
            if count > 30_000:
                break
            yield path


def _select_alternative(capability_id: str, requested: set[str], has_source: bool) -> str | None:
    options = ALTERNATIVES.get(capability_id, [])
    for option in options:
        if option.id in requested and (has_source or not option.requires_source):
            return option.id
    for option in options:
        if option.automation in {"automatic", "generated"} and (has_source or not option.requires_source):
            return option.id
    return options[0].id if options else None


def _profile_scores(
    *,
    has_app: bool,
    has_source: bool,
    capabilities: list[Capability],
    requested_profile: str,
) -> list[Profile]:
    ids = {cap.id for cap in capabilities}
    hard = {cap.id for cap in capabilities if cap.severity == "blocker"}
    binary_shim_supported = ids.issubset({"cephei-preferences", "root-paths", "darwin-notifications", "preference-bundle"})
    source_blocked = bool(hard & {"root-process-control", "private-entitlements"})
    extension_needed = bool(ids & {"springboard-hook", "cross-app-injection", "safari-injection", "preference-bundle", "network-filter"})
    background_needed = "launch-daemon" in ids
    companion_needed = bool(ids & {"launch-daemon", "command-line-tools", "root-process-control"})

    profiles = [
        Profile(
            "direct-ipa",
            "Compatible original application",
            100 if has_app and not capabilities else 15 if has_app else 0,
            bool(has_app and not capabilities),
            "Preserves the original ARM64 app executable when no stock-iOS blockers are detected.",
            100 if has_app and not capabilities else 35 if has_app else 0,
        ),
        Profile(
            "binary-shims",
            "Original binary with audited shims",
            90 if has_app and binary_shim_supported and capabilities else 20 if has_app else 0,
            bool(has_app and binary_shim_supported and capabilities),
            "Repairs known dependency paths and embeds audited preference/filesystem adapters.",
            85 if has_app and binary_shim_supported and capabilities else 30 if has_app else 0,
        ),
        Profile(
            "source-rebuild",
            "Source rebuild against public iOS APIs",
            95 if has_source and not source_blocked else 45 if has_source else 0,
            bool(has_source and not source_blocked),
            "Recompiles Swift, Objective-C, C, or C++ source with generated stock-iOS adapters.",
            92 if has_source and not source_blocked else 50 if has_source else 0,
        ),
        Profile(
            "app-extensions",
            "Application plus normal iOS extensions",
            92 if has_source and extension_needed and not source_blocked else 25 if extension_needed else 0,
            bool(has_source and extension_needed and not source_blocked),
            "Uses widgets, Share Extensions, Safari extensions, App Intents, or settings UI instead of injection.",
            80 if has_source and extension_needed and not source_blocked else 25,
        ),
        Profile(
            "background-replacement",
            "Background task and transfer replacement",
            88 if has_source and background_needed and not source_blocked else 20 if background_needed else 0,
            bool(has_source and background_needed and not source_blocked),
            "Replaces launch daemons with BGTaskScheduler, background transfers, and optional push synchronization.",
            75 if has_source and background_needed and not source_blocked else 20,
        ),
        Profile(
            "companion-service",
            "Normal iOS client with companion service",
            70 if companion_needed else 10,
            bool(companion_needed),
            "Moves continuous, scheduled, or server-safe work to a generated service and keeps the iOS app sandboxed.",
            65 if companion_needed else 10,
        ),
        Profile(
            "report-only",
            "Port project and blocker report",
            1,
            True,
            "Produces an explicit conversion plan without fabricating a runnable replacement.",
            0,
        ),
    ]
    if requested_profile and requested_profile != "automatic":
        for profile in profiles:
            if profile.id == requested_profile:
                profile.score += 40
    return sorted(profiles, key=lambda item: (-item.score, PROFILE_ORDER.index(item.id)))


def analyze_payload(
    payload_root: Path,
    *,
    requested_profile: str = "automatic",
    requested_alternatives: Iterable[str] = (),
) -> CapabilityGraph:
    root = payload_root.resolve()
    requested = {str(value) for value in requested_alternatives if value}
    found: dict[str, tuple[str, list[str]]] = {}
    source_files: list[str] = []
    app_bundles: list[str] = []
    macho_dependencies: list[dict[str, Any]] = []
    launch_daemons: list[str] = []
    preference_bundles: list[str] = []
    command_tools: list[str] = []
    total_files = 0

    for path in _iter_files(root):
        total_files += 1
        relative = _safe_relative(path, root)
        lower = relative.lower()
        if path.suffix.lower() in {".swift", ".m", ".mm", ".c", ".cc", ".cpp"}:
            source_files.append(relative)
        if "/launchdaemons/" in f"/{lower}" and path.suffix.lower() == ".plist":
            launch_daemons.append(relative)
            _add_evidence(found, "launch-daemon", "blocker", relative)
        if "/preferencebundles/" in f"/{lower}" or lower.endswith(".bundle/info.plist") and "preferences" in lower:
            preference_bundles.append(relative)
            _add_evidence(found, "preference-bundle", "warning", relative)
        if any(segment in lower for segment in ("/mobilesubstrate/dynamiclibraries/", "/ellekit/", "/libhooker/")):
            _add_evidence(found, "cross-app-injection", "blocker", relative)
        if path.parent.name.endswith(".app") and path.name == "Info.plist":
            app_bundles.append(_safe_relative(path.parent, root))
        if _is_macho(path):
            _inspect_macho(path, root, found, macho_dependencies)
            if "/usr/bin/" in f"/{lower}" or "/usr/libexec/" in f"/{lower}":
                command_tools.append(relative)
                _add_evidence(found, "command-line-tools", "warning", relative)
        if path.suffix.lower() in TEXT_SUFFIXES:
            text = _read_text(path)
            if text:
                for cap, pattern, severity in PATTERNS:
                    match = pattern.search(text)
                    if match:
                        _add_evidence(found, cap, severity, f"{relative}: {match.group(0)[:160]}")
                if path.suffix.lower() in {".xm", ".x"} or "%hook" in text:
                    _add_evidence(found, "springboard-hook", "blocker", relative)
            _inspect_entitlements(path, root, found)

    has_source = bool(source_files)
    has_app = bool(app_bundles)
    capabilities: list[Capability] = []
    for cap_id, (severity, evidence) in sorted(found.items()):
        options = ALTERNATIVES.get(cap_id, [])
        selected = _select_alternative(cap_id, requested, has_source)
        if severity == "blocker" and not has_source and cap_id not in {"cephei-preferences", "root-paths"}:
            status = "unavailable-without-source"
        elif selected:
            status = "replacement-planned"
        else:
            status = "no-stock-ios-equivalent"
        capabilities.append(
            Capability(
                id=cap_id,
                title=CAPABILITY_TITLES.get(cap_id, cap_id.replace("-", " ").title()),
                severity=severity,
                evidence=evidence,
                alternatives=options,
                selected_alternative=selected,
                stock_ios_status=status,
            )
        )

    profiles = _profile_scores(
        has_app=has_app,
        has_source=has_source,
        capabilities=capabilities,
        requested_profile=requested_profile,
    )
    recommended = next((profile for profile in profiles if profile.usable), profiles[-1])
    hard_blockers = [
        f"{cap.title}: {cap.stock_ios_status}"
        for cap in capabilities
        if cap.severity == "blocker" and cap.stock_ios_status.startswith("unavailable")
    ]
    warnings: list[str] = []
    if recommended.id == "companion-service":
        warnings.append("A companion service cannot recreate root, kernel, or cross-process injection privileges; it only relocates permitted workload.")
    if any(option.requires_entitlement for cap in capabilities for option in cap.alternatives if option.id == cap.selected_alternative):
        warnings.append("One or more selected alternatives require Apple-granted capabilities before distribution.")

    facts = {
        "fileCount": total_files,
        "hasStandaloneApp": has_app,
        "standaloneApps": app_bundles[:20],
        "hasSource": has_source,
        "sourceFileCount": len(source_files),
        "sourceFiles": source_files[:200],
        "launchDaemons": launch_daemons[:50],
        "preferenceBundles": preference_bundles[:50],
        "commandTools": command_tools[:50],
        "machoFiles": macho_dependencies[:100],
    }
    return CapabilityGraph(
        schemaVersion=2,
        packageRoot=str(root),
        facts=facts,
        capabilities=capabilities,
        profiles=profiles,
        recommendedProfile=recommended.id,
        requestedProfile=requested_profile or "automatic",
        requestedAlternatives=sorted(requested),
        expectedRetainedFunctionality=recommended.retained_functionality,
        hardBlockers=hard_blockers,
        warnings=warnings,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--profile", default="automatic")
    parser.add_argument("--alternative", action="append", default=[])
    args = parser.parse_args()
    graph = analyze_payload(
        args.payload,
        requested_profile=args.profile,
        requested_alternatives=args.alternative,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(graph.to_dict(), indent=2), encoding="utf-8")
    print(json.dumps(graph.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
