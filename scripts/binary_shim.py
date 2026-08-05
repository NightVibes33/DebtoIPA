#!/usr/bin/env python3
"""Audited binary-shim conversion for narrow, known jailbreak dependencies."""
from __future__ import annotations

import hashlib
import json
import os
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from typing import Any

from adapter_sdk import build_binary_adapter_framework, write_adapter_sdk

MACHO_MAGICS = {
    b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xce",
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca",
}

REPLACEABLE_DEPENDENCIES = (
    "Cephei.framework/Cephei",
    "CepheiPrefs.framework/CepheiPrefs",
    "CepheiPreferences.framework/CepheiPreferences",
    "/usr/lib/libcephei.dylib",
)

FORBIDDEN_DEPENDENCY_MARKERS = (
    "CydiaSubstrate",
    "MobileSubstrate",
    "SubstrateLoader",
    "ElleKit",
    "libhooker",
    "RocketBootstrap",
    "SpringBoardServices",
    "/System/Library/PrivateFrameworks/",
)


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=check)


def _dependencies(binary: Path) -> list[str]:
    if shutil.which("otool") is None:
        raise RuntimeError("otool is required for binary-shim conversion.")
    output = _run(["otool", "-L", str(binary)]).stdout
    values: list[str] = []
    for line in output.splitlines()[1:]:
        value = line.strip().split(" (", 1)[0]
        if value:
            values.append(value)
    return values


def _architectures(binary: Path) -> list[str]:
    if shutil.which("lipo") is None:
        return []
    result = _run(["lipo", "-archs", str(binary)], check=False)
    return result.stdout.strip().split() if result.returncode == 0 else []


def _find_app(payload_root: Path) -> Path | None:
    candidates: list[tuple[int, Path]] = []
    for app in payload_root.rglob("*.app"):
        if not app.is_dir() or any(parent.suffix == ".app" for parent in app.parents):
            continue
        info = app / "Info.plist"
        try:
            plist = plistlib.loads(info.read_bytes())
            executable = app / str(plist.get("CFBundleExecutable") or "")
            if executable.read_bytes()[:4] not in MACHO_MAGICS:
                continue
        except Exception:
            continue
        relative = app.relative_to(payload_root).as_posix().lower()
        score = 100 if "/applications/" in f"/{relative}" else 0
        candidates.append((score - len(app.parts), app))
    return max(candidates, default=(0, None), key=lambda item: item[0])[1]


def can_binary_shim(payload_root: Path) -> dict[str, Any]:
    app = _find_app(payload_root)
    if app is None:
        return {"eligible": False, "reason": "No standalone application bundle was found."}
    plist = plistlib.loads((app / "Info.plist").read_bytes())
    binary = app / str(plist["CFBundleExecutable"])
    dependencies = _dependencies(binary)
    forbidden = [value for value in dependencies if any(marker.lower() in value.lower() for marker in FORBIDDEN_DEPENDENCY_MARKERS)]
    replaceable = [value for value in dependencies if any(marker.lower() in value.lower() for marker in REPLACEABLE_DEPENDENCIES)]
    architectures = _architectures(binary)
    if architectures and "arm64" not in architectures and "arm64e" not in architectures:
        return {"eligible": False, "reason": "The original executable has no ARM64 slice.", "architectures": architectures}
    if forbidden:
        return {"eligible": False, "reason": "The executable still links injection/private dependencies.", "forbidden": forbidden}
    if not replaceable:
        return {"eligible": False, "reason": "No supported binary-shim dependency was found.", "dependencies": dependencies}
    return {
        "eligible": True,
        "app": app,
        "binary": binary,
        "plist": plist,
        "dependencies": dependencies,
        "replaceable": replaceable,
        "architectures": architectures,
    }


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


def build_binary_shimmed_ipa(
    payload_root: Path,
    output_directory: Path,
    *,
    source_name: str,
    minimum_ios: str,
    bundle_id: str = "",
    display_name: str = "",
    device: str = "universal",
) -> dict[str, Any]:
    eligibility = can_binary_shim(payload_root)
    if not eligibility.get("eligible"):
        raise RuntimeError(str(eligibility.get("reason") or "Binary shim is unavailable."))
    output_directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="debtoipa-binary-shim-") as temporary:
        stage = Path(temporary)
        payload = stage / "Payload"
        payload.mkdir()
        source_app: Path = eligibility["app"]
        app = payload / source_app.name
        shutil.copytree(source_app, app, symlinks=True)
        shutil.rmtree(app / "_CodeSignature", ignore_errors=True)
        (app / "embedded.mobileprovision").unlink(missing_ok=True)

        info_path = app / "Info.plist"
        info = plistlib.loads(info_path.read_bytes())
        if bundle_id:
            info["CFBundleIdentifier"] = bundle_id
        if display_name:
            info["CFBundleDisplayName"] = display_name
            info["CFBundleName"] = display_name
        if minimum_ios:
            info["MinimumOSVersion"] = minimum_ios
        if device == "iphone":
            info["UIDeviceFamily"] = [1]
        elif device == "ipad":
            info["UIDeviceFamily"] = [2]
        else:
            info["UIDeviceFamily"] = [1, 2]
        info_path.write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY, sort_keys=False))

        adapter_root = stage / "AdapterSDK"
        app_bundle_id = str(info.get("CFBundleIdentifier") or "app.debtoipa.converted")
        adapter_manifest = write_adapter_sdk(
            adapter_root,
            bundle_id=app_bundle_id,
            app_name=str(info.get("CFBundleDisplayName") or info.get("CFBundleName") or app.stem),
            alternatives={"preferences-adapter", "sandbox-path-adapter", "notification-adapter"},
        )
        frameworks = app / "Frameworks"
        framework = build_binary_adapter_framework(adapter_root, frameworks, minimum_ios=minimum_ios)
        binary = app / str(info["CFBundleExecutable"])
        changed: list[dict[str, str]] = []
        for old in eligibility["replaceable"]:
            new = "@rpath/DebToIPAAdapters.framework/DebToIPAAdapters"
            result = _run(["install_name_tool", "-change", old, new, str(binary)], check=False)
            if result.returncode != 0:
                raise RuntimeError(f"install_name_tool could not replace {old}: {result.stderr.strip()}")
            changed.append({"from": old, "to": new})
        deps_after = _dependencies(binary)
        if "@rpath/DebToIPAAdapters.framework/DebToIPAAdapters" not in deps_after:
            raise RuntimeError("The patched executable does not reference the embedded adapter framework.")
        if any(old in deps_after for old in eligibility["replaceable"]):
            raise RuntimeError("One or more original jailbreak dependencies remain after patching.")
        rpaths = _run(["otool", "-l", str(binary)]).stdout
        if "@executable_path/Frameworks" not in rpaths:
            result = _run(["install_name_tool", "-add_rpath", "@executable_path/Frameworks", str(binary)], check=False)
            if result.returncode != 0:
                raise RuntimeError("The executable lacks header space for the required embedded-framework rpath.")

        name = f"{Path(source_name).stem}-BinaryShim-unsigned.ipa"
        destination = output_directory / name
        if shutil.which("ditto"):
            subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", "Payload", str(destination)], cwd=stage, check=True)
        else:
            _zip_payload(stage, destination)
        report = {
            "schemaVersion": 1,
            "resultKind": "binary-shimmed",
            "sourceApp": source_app.relative_to(payload_root).as_posix(),
            "executable": str(info["CFBundleExecutable"]),
            "executableSha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            "replacedDependencies": changed,
            "embeddedFramework": framework.name,
            "adapterManifest": adapter_manifest,
            "dependenciesAfter": deps_after,
            "limitations": [
                "The shim covers common HBPreferences methods and legacy filesystem path mapping only.",
                "It does not provide SpringBoard injection, root access, private frameworks, RocketBootstrap semantics, or unavailable entitlements.",
                "A real-device launch and feature test is still required after signing.",
            ],
        }
        (output_directory / "binary-shim-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        return {"ipa": destination, "report": report}
