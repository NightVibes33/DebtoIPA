"""Build a launchable stock-iOS compatibility-host IPA from a DebToIPA Port Project.

This module is loaded after port_mode.py. It never executes the original jailbreak
binary. Instead it injects the translated manifest and safe package resources into
a precompiled, unsigned Swift compatibility host.
"""
from __future__ import annotations

import io
import json
import plistlib
import re
import zipfile
from pathlib import Path, PurePosixPath

MACHO_MAGICS = {
    b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xce",
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca",
}
MAX_RESOURCE_FILE = 32 * 1024 * 1024
MAX_RESOURCE_TOTAL = 180 * 1024 * 1024


def _safe_component(value: str, fallback: str = "PortedApp") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value or "").strip("-.")
    return cleaned[:80] or fallback


def _is_macho(data: bytes) -> bool:
    return len(data) >= 4 and data[:4] in MACHO_MAGICS


def _is_code_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    lower = path.lower()
    if any(part in {"_CodeSignature", "SC_Info"} for part in parts):
        return True
    if lower.endswith((".dylib", ".so", ".a")):
        return True
    return False


def _find_port_manifest(names: list[str]) -> str:
    candidates = [name for name in names if name.endswith("/PortManifest.json")]
    if not candidates:
        raise RuntimeError("Port Project has no PortManifest.json.")
    return sorted(candidates, key=lambda item: item.count("/"))[0]


def _find_template_app(names: list[str]) -> str:
    candidates: set[str] = set()
    for name in names:
        match = re.match(r"^Payload/([^/]+\.app)/", name)
        if match:
            candidates.add(match.group(1))
    if len(candidates) != 1:
        raise RuntimeError("Compatibility host template must contain exactly one app bundle.")
    return next(iter(candidates))


def _version_tuple(value: object) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in str(value).split(".") if part != "")
    except Exception:
        return (0,)


def _max_version(first: object, second: object) -> str:
    a, b = _version_tuple(first), _version_tuple(second)
    best = first if a >= b else second
    return str(best or "15.0")


def _augment_manifest(manifest: dict, included: list[str], skipped: list[dict], original_report: dict) -> dict:
    plan = manifest.get("capabilityPlan") if isinstance(manifest.get("capabilityPlan"), dict) else {}
    redesign = list(plan.get("requiresRedesign") or [])
    impossible = list(plan.get("notEmulatable") or [])
    blockers = list(original_report.get("blockers") or [])
    feature_complete = not redesign and not impossible and not blockers
    manifest["hostBuild"] = {
        "schemaVersion": 1,
        "kind": "precompiled-stock-ios-compatibility-host",
        "launchable": True,
        "featureComplete": feature_complete,
        "originalBinaryExecuted": False,
        "includedResourceCount": len(included),
        "skippedResourceCount": len(skipped),
        "translatedCapabilities": list(plan.get("translatable") or []),
        "requiresRedesign": redesign,
        "notEmulatable": impossible,
        "originalBlockers": blockers,
        "warning": None if feature_complete else "This IPA launches safely, but unsupported jailbreak behavior is shown as unavailable until a public-API replacement is implemented.",
    }
    return manifest


def build_host_ipa_from_port_result(port_result_path: str, template_ipa_path: str, options_json: str) -> str:
    """Rewrite an existing Port Project result ZIP to include a launchable host IPA."""
    options = json.loads(options_json or "{}")
    result_path = Path(port_result_path)
    template_path = Path(template_ipa_path)
    if not result_path.is_file():
        raise RuntimeError("Port Project result is missing.")
    if not template_path.is_file():
        raise RuntimeError("Compatibility host template is unavailable.")

    with zipfile.ZipFile(result_path, "r") as port_zip:
        port_names = port_zip.namelist()
        report = json.loads(port_zip.read("compatibility-report.json"))
        if report.get("verdict") != "port-project":
            return json.dumps({
                "verdict": report.get("verdict", "blocked"),
                "artifactName": result_path.name,
                "blockers": report.get("blockers", []),
                "warnings": report.get("warnings", []),
            })
        manifest_name = _find_port_manifest(port_names)
        project_root = manifest_name.rsplit("/", 1)[0]
        manifest = json.loads(port_zip.read(manifest_name))

        included: list[str] = []
        skipped: list[dict] = []
        safe_resources: list[tuple[str, bytes]] = []
        total = 0
        prefix = project_root + "/PortPayload/"
        for name in port_names:
            if not name.startswith(prefix) or name.endswith("/"):
                continue
            relative = name[len(prefix):]
            if not relative or relative.startswith("../") or "/../" in relative:
                skipped.append({"path": relative, "reason": "unsafe path"})
                continue
            data = port_zip.read(name)
            if len(data) > MAX_RESOURCE_FILE:
                skipped.append({"path": relative, "reason": "resource exceeds per-file mobile limit"})
                continue
            if _is_code_path(relative) or _is_macho(data):
                skipped.append({"path": relative, "reason": "native code cannot be embedded as executable stock-iOS behavior"})
                continue
            if total + len(data) > MAX_RESOURCE_TOTAL:
                skipped.append({"path": relative, "reason": "resource payload exceeds mobile host limit"})
                continue
            safe_resources.append((relative, data))
            included.append(relative)
            total += len(data)

        manifest = _augment_manifest(manifest, included, skipped, report)
        manifest_bytes = json.dumps(manifest, indent=2, sort_keys=False).encode()
        index_bytes = json.dumps({"included": included, "skipped": skipped}, indent=2).encode()
        original_entries = [(name, port_zip.read(name)) for name in port_names if not name.endswith("/")]

    with zipfile.ZipFile(template_path, "r") as template:
        template_names = template.namelist()
        app_name = _find_template_app(template_names)
        plist_name = f"Payload/{app_name}/Info.plist"
        if plist_name not in template_names:
            raise RuntimeError("Compatibility host template has no Info.plist.")
        plist = plistlib.loads(template.read(plist_name))
        display_name = str(options.get("displayName") or manifest.get("name") or "Ported App")
        bundle_id = str(options.get("bundleId") or manifest.get("bundleIdentifier") or "com.debtoipa.compatibilityhost")
        plist["CFBundleIdentifier"] = bundle_id
        plist["CFBundleDisplayName"] = display_name
        plist["CFBundleName"] = display_name[:16]
        plist["MinimumOSVersion"] = _max_version(
            plist.get("MinimumOSVersion", "15.0"),
            manifest.get("minimumIOS", options.get("minimumIos", "15.0")),
        )
        plist["UIDeviceFamily"] = {
            "iphone": [1], "ipad": [2], "universal": [1, 2]
        }.get(str(options.get("device") or "universal"), [1, 2])
        plist_bytes = plistlib.dumps(plist, fmt=plistlib.FMT_BINARY, sort_keys=False)

        host_buffer = io.BytesIO()
        with zipfile.ZipFile(host_buffer, "w", allowZip64=True) as output:
            for info in template.infolist():
                name = info.filename
                if name == plist_name:
                    output.writestr(info, plist_bytes)
                    continue
                if name.startswith(f"Payload/{app_name}/DebToIPA/"):
                    continue
                if name.endswith("embedded.mobileprovision") or "/_CodeSignature/" in name:
                    continue
                output.writestr(info, template.read(name))
            root = f"Payload/{app_name}/DebToIPA"
            output.writestr(root + "/PortManifest.json", manifest_bytes, compress_type=zipfile.ZIP_DEFLATED)
            output.writestr(root + "/PortFileIndex.json", index_bytes, compress_type=zipfile.ZIP_DEFLATED)
            for relative, data in safe_resources:
                output.writestr(root + "/PortPayload/" + relative, data, compress_type=zipfile.ZIP_DEFLATED)
        host_bytes = host_buffer.getvalue()

    base = _safe_component(Path(str(options.get("sourceName") or report.get("source", {}).get("name") or "PortedApp")).stem)
    ipa_name = f"{base}-CompatibilityHost-unsigned.ipa"
    report["schemaVersion"] = max(int(report.get("schemaVersion") or 0), 4)
    report["verdict"] = "host-packaged"
    report["output"] = {
        "name": ipa_name,
        "size": len(host_bytes),
        "signed": False,
        "kind": "compatibility-host",
        "launchable": True,
        "featureComplete": bool(manifest["hostBuild"]["featureComplete"]),
        "originalBinaryExecuted": False,
    }
    report.setdefault("warnings", [])
    if not manifest["hostBuild"]["featureComplete"]:
        report["warnings"].append(manifest["hostBuild"]["warning"])
    report["hostBuild"] = manifest["hostBuild"]

    rebuilt = result_path.with_suffix(".host.tmp")
    with zipfile.ZipFile(rebuilt, "w", allowZip64=True) as output:
        output.writestr("compatibility-report.json", json.dumps(report, indent=2), compress_type=zipfile.ZIP_DEFLATED)
        output.writestr(ipa_name, host_bytes, compress_type=zipfile.ZIP_STORED)
        for name, data in original_entries:
            if name == "compatibility-report.json":
                continue
            output.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
    rebuilt.replace(result_path)

    return json.dumps({
        "verdict": "host-packaged",
        "artifactName": f"{base}-DebToIPA-result.zip",
        "blockers": [],
        "warnings": list(report.get("warnings") or []),
        "hostBuild": manifest["hostBuild"],
    })
