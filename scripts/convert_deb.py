#!/usr/bin/env python3
"""Extract an iOS .app from a Debian package and build a stock-iOS-oriented IPA.

This tool repairs packaging and metadata. It does not rewrite jailbreak-only code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

BLOCKED_REFERENCES = (
    b"/Library/MobileSubstrate",
    b"/var/jb/",
    b"/usr/lib/libsubstrate",
    b"CydiaSubstrate",
    b"SubstrateLoader",
    b"libhooker",
    b"ElleKit",
    b"Substitute",
    b"RocketBootstrap",
)
TWEAK_MARKERS = (
    "Library/MobileSubstrate/DynamicLibraries",
    "var/jb/Library/MobileSubstrate/DynamicLibraries",
    "Library/PreferenceBundles",
    "var/jb/Library/PreferenceBundles",
    "Library/LaunchDaemons",
    "var/jb/Library/LaunchDaemons",
)
ALLOWED_DYLIB_PREFIXES = (
    "/System/Library/",
    "/usr/lib/",
    "@rpath/",
    "@loader_path/",
    "@executable_path/",
)


def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, text=True, **kwargs)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_extract_tar(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r:*") as tar:
        destination_resolved = destination.resolve()
        for member in tar.getmembers():
            target = (destination / member.name).resolve()
            if destination_resolved not in target.parents and target != destination_resolved:
                raise RuntimeError(f"Unsafe path in Debian payload: {member.name}")
        tar.extractall(destination, filter="data")


def extract_deb(deb: Path, destination: Path) -> list[str]:
    members = run(["ar", "t", str(deb)], capture_output=True).stdout.splitlines()
    data_member = next((m for m in members if m.startswith("data.tar")), None)
    if not data_member:
        raise RuntimeError("Debian archive has no data.tar payload.")
    packed = destination.parent / data_member
    with packed.open("wb") as output:
        subprocess.run(["ar", "p", str(deb), data_member], check=True, stdout=output)
    if packed.suffix == ".zst":
        unpacked = destination.parent / "data.tar"
        with unpacked.open("wb") as output:
            subprocess.run(["zstd", "-dc", str(packed)], check=True, stdout=output)
        packed = unpacked
    safe_extract_tar(packed, destination)
    return members


def find_apps(root: Path) -> list[Path]:
    apps: list[Path] = []
    for candidate in root.rglob("*.app"):
        if not candidate.is_dir():
            continue
        if any(parent.suffix in {".app", ".appex"} for parent in candidate.parents if parent != root):
            continue
        if (candidate / "Info.plist").is_file():
            apps.append(candidate)
    return sorted(apps, key=lambda p: sum(f.stat().st_size for f in p.rglob("*") if f.is_file()), reverse=True)


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


DYLIB_LOAD_COMMANDS = {0xC, 0x80000018, 0x1F | 0x80000000, 0x20, 0x23 | 0x80000000}


def _parse_macho_slice(data: bytes, offset: int = 0, limit: int | None = None) -> list[str]:
    if limit is None:
        limit = len(data)
    magic = data[offset:offset + 4]
    formats = {
        b"\xcf\xfa\xed\xfe": ("<", True),
        b"\xfe\xed\xfa\xcf": (">", True),
        b"\xce\xfa\xed\xfe": ("<", False),
        b"\xfe\xed\xfa\xce": (">", False),
    }
    if magic not in formats:
        return []
    endian, is_64 = formats[magic]
    header_size = 32 if is_64 else 28
    if offset + header_size > limit:
        return []
    ncmds = struct.unpack_from(endian + "I", data, offset + 16)[0]
    cursor = offset + header_size
    libraries: list[str] = []
    for _ in range(ncmds):
        if cursor + 8 > limit:
            break
        cmd, cmdsize = struct.unpack_from(endian + "II", data, cursor)
        if cmdsize < 8 or cursor + cmdsize > limit:
            break
        if cmd in DYLIB_LOAD_COMMANDS and cmdsize >= 24:
            name_offset = struct.unpack_from(endian + "I", data, cursor + 8)[0]
            start = cursor + name_offset
            end = cursor + cmdsize
            if cursor <= start < end:
                raw = data[start:end].split(b"\0", 1)[0]
                name = raw.decode("utf-8", "replace").strip()
                if name:
                    libraries.append(name)
        cursor += cmdsize
    return libraries


def macho_linked_libraries(executable: Path) -> list[str]:
    data = executable.read_bytes()
    magic = data[:4]
    fat_formats = {
        b"\xca\xfe\xba\xbe": (">", False),
        b"\xbe\xba\xfe\xca": ("<", False),
        b"\xca\xfe\xba\xbf": (">", True),
        b"\xbf\xba\xfe\xca": ("<", True),
    }
    if magic not in fat_formats:
        return _parse_macho_slice(data)
    endian, fat64 = fat_formats[magic]
    if len(data) < 8:
        return []
    count = struct.unpack_from(endian + "I", data, 4)[0]
    cursor = 8
    stride = 32 if fat64 else 20
    libraries: list[str] = []
    for _ in range(min(count, 64)):
        if cursor + stride > len(data):
            break
        if fat64:
            _, _, slice_offset, slice_size, _, _ = struct.unpack_from(endian + "IIQQII", data, cursor)
        else:
            _, _, slice_offset, slice_size, _ = struct.unpack_from(endian + "IIIII", data, cursor)
        if slice_offset + slice_size <= len(data):
            libraries.extend(_parse_macho_slice(data, int(slice_offset), int(slice_offset + slice_size)))
        cursor += stride
    return sorted(set(libraries))


def linked_libraries(executable: Path) -> list[str]:
    parsed = macho_linked_libraries(executable)
    if parsed:
        return parsed
    for tool in ("otool", "llvm-otool", "llvm-otool-18", "llvm-otool-17", "llvm-otool-16"):
        if command_exists(tool):
            try:
                output = run([tool, "-L", str(executable)], capture_output=True).stdout.splitlines()[1:]
                return [line.strip().split(" (compatibility", 1)[0] for line in output if line.strip()]
            except Exception:
                pass
    return []


def executable_description(executable: Path) -> str:
    if command_exists("file"):
        try:
            return run(["file", "-b", str(executable)], capture_output=True).stdout.strip()
        except Exception:
            pass
    return "unknown"


def inspect_binary(executable: Path) -> tuple[list[str], list[str], dict[str, Any]]:
    blockers: list[str] = []
    warnings: list[str] = []
    description = executable_description(executable)
    if "Mach-O" not in description:
        blockers.append("The app executable is not a Mach-O iOS binary.")
    if "arm64" not in description and "universal binary" not in description:
        blockers.append("The app executable does not contain an ARM64 slice required by modern stock iOS devices.")

    data = executable.read_bytes()
    found_refs = [item.decode("utf-8", "ignore") for item in BLOCKED_REFERENCES if item in data]
    if found_refs:
        blockers.append("The executable references jailbreak-only loaders or rootless paths: " + ", ".join(found_refs))

    dylibs = linked_libraries(executable)
    unsupported = [item for item in dylibs if not item.startswith(ALLOWED_DYLIB_PREFIXES)]
    if unsupported:
        blockers.append("The executable links libraries unavailable on stock iOS: " + ", ".join(unsupported))
    if not dylibs:
        warnings.append("Linked-library inspection was unavailable; the binary was checked with architecture and string heuristics only.")

    return blockers, warnings, {"description": description, "linkedLibraries": dylibs, "blockedReferences": found_refs}


def update_plist(plist_path: Path, device: str, minimum_ios: str, bundle_id: str, display_name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    with plist_path.open("rb") as handle:
        plist = plistlib.load(handle)
    before = {
        "CFBundleIdentifier": plist.get("CFBundleIdentifier"),
        "CFBundleDisplayName": plist.get("CFBundleDisplayName"),
        "CFBundleName": plist.get("CFBundleName"),
        "UIDeviceFamily": plist.get("UIDeviceFamily"),
        "MinimumOSVersion": plist.get("MinimumOSVersion"),
        "CFBundleExecutable": plist.get("CFBundleExecutable"),
    }
    if bundle_id:
        plist["CFBundleIdentifier"] = bundle_id
    if display_name:
        plist["CFBundleDisplayName"] = display_name
        plist["CFBundleName"] = display_name[:16]
    plist["UIDeviceFamily"] = {"iphone": [1], "ipad": [2], "universal": [1, 2]}[device]
    plist["MinimumOSVersion"] = minimum_ios
    plist["CFBundleSupportedPlatforms"] = ["iPhoneOS"]
    plist["LSRequiresIPhoneOS"] = True
    with plist_path.open("wb") as handle:
        plistlib.dump(plist, handle, fmt=plistlib.FMT_BINARY, sort_keys=False)
    after = {key: plist.get(key) for key in before}
    return before, after


def remove_stale_signatures(app: Path) -> list[str]:
    removed: list[str] = []
    for child in list(app.rglob("*")):
        if child.name in {"_CodeSignature", "SC_Info"} and child.is_dir():
            shutil.rmtree(child)
            removed.append(str(child.relative_to(app)))
        elif child.name == "embedded.mobileprovision" and child.is_file():
            child.unlink()
            removed.append(str(child.relative_to(app)))
    return removed


def normalize_permissions(root: Path) -> None:
    for path in root.rglob("*"):
        try:
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                path.chmod(0o755)
            elif stat.S_ISREG(mode):
                executable = bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
                path.chmod(0o755 if executable else 0o644)
        except OSError:
            pass


def create_ipa(staging: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    run(["zip", "-qry", "-y", str(output), "Payload"], cwd=staging)


def package_markers(root: Path) -> list[str]:
    hits: list[str] = []
    normalized = {str(p.relative_to(root)) for p in root.rglob("*")}
    for marker in TWEAK_MARKERS:
        if marker in normalized or any(path.startswith(marker + "/") for path in normalized):
            hits.append(marker)
    return hits


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deb", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--device", choices=["universal", "iphone", "ipad"], default="universal")
    parser.add_argument("--minimum-ios", default="15.0")
    parser.add_argument("--bundle-id", default="")
    parser.add_argument("--display-name", default="")
    args = parser.parse_args()

    report: dict[str, Any] = {
        "schemaVersion": 1,
        "source": {"name": args.deb.name},
        "target": {"device": args.device, "minimumIOS": args.minimum_ios, "bundleIDOverride": args.bundle_id or None, "displayNameOverride": args.display_name or None},
        "verdict": "blocked",
        "blockers": [],
        "warnings": [],
        "changes": {},
    }
    exit_code = 2
    try:
        if not args.deb.is_file():
            raise RuntimeError("Input .deb does not exist.")
        report["source"]["sha256"] = sha256(args.deb)
        report["source"]["size"] = args.deb.stat().st_size
        with tempfile.TemporaryDirectory(prefix="debtoipa-") as temp:
            temp_root = Path(temp)
            extracted = temp_root / "root"
            extracted.mkdir()
            report["source"]["archiveMembers"] = extract_deb(args.deb, extracted)
            markers = package_markers(extracted)
            report["analysis"] = {"packageMarkers": markers}
            apps = find_apps(extracted)
            report["analysis"]["appCandidates"] = [str(p.relative_to(extracted)) for p in apps]
            if not apps:
                if markers:
                    report["blockers"].append("This is a jailbreak tweak/package and contains no standalone .app bundle to package as an IPA.")
                else:
                    report["blockers"].append("No standalone iOS .app bundle with an Info.plist was found in the Debian payload.")
                raise RuntimeError("No convertible app bundle found.")
            if len(apps) > 1:
                report["warnings"].append(f"Multiple app bundles were found; selected the largest candidate: {apps[0].name}")

            source_app = apps[0]
            staging = temp_root / "staging"
            payload = staging / "Payload"
            payload.mkdir(parents=True)
            destination_app = payload / source_app.name
            shutil.copytree(source_app, destination_app, symlinks=True)

            plist_path = destination_app / "Info.plist"
            before, after = update_plist(plist_path, args.device, args.minimum_ios, args.bundle_id, args.display_name)
            executable_name = after.get("CFBundleExecutable")
            if not executable_name or not isinstance(executable_name, str):
                report["blockers"].append("Info.plist has no valid CFBundleExecutable value.")
                raise RuntimeError("Missing app executable metadata.")
            executable = destination_app / executable_name
            if not executable.is_file():
                report["blockers"].append(f"The declared app executable does not exist: {executable_name}")
                raise RuntimeError("Missing app executable.")

            blockers, warnings, binary = inspect_binary(executable)
            report["blockers"].extend(blockers)
            report["warnings"].extend(warnings)
            report["analysis"]["selectedApp"] = str(source_app.relative_to(extracted))
            report["analysis"]["binary"] = binary
            report["changes"] = {
                "plistBefore": before,
                "plistAfter": after,
                "removedSigningArtifacts": remove_stale_signatures(destination_app),
                "ipaLayout": f"Payload/{destination_app.name}",
            }
            normalize_permissions(staging)
            executable.chmod(0o755)

            if report["blockers"]:
                raise RuntimeError("Stock-iOS compatibility checks found blockers.")
            create_ipa(staging, args.output)
            report["output"] = {"name": args.output.name, "size": args.output.stat().st_size, "sha256": sha256(args.output), "signed": False}
            report["verdict"] = "packaged"
            report["warnings"].append("The IPA is unsigned. Install it on a normal device only after signing it with your Apple development/sideloading certificate.")
            if args.device == "universal" and before.get("UIDeviceFamily") == [2]:
                report["warnings"].append("The source declared iPad-only support. UIDeviceFamily was expanded, but the app UI or code may still be iPad-specific.")
            exit_code = 0
    except Exception as error:
        report["error"] = str(error)
    finally:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
