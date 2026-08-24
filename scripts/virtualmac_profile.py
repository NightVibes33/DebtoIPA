#!/usr/bin/env python3
"""Profile Virtual Mac DEBs/source without pretending they can become stock IPAs.

Virtual Mac is a jailbreak VM stack, not a normal application bundle.  This
profiler identifies the package/source, records the runtime pieces it needs,
and evaluates whether a requested device/OS combination is in the upstream
hardware-virtualization support envelope.

It deliberately performs static inspection only: maintainer scripts and
package executables are never run.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import tarfile
from pathlib import Path
from typing import Any

VIRTUALMAC_PACKAGE = "com.mac.virtual"
VM_MARKERS = {
    b"Virtualization.framework": "Apple Virtualization framework",
    b"Hypervisor.framework": "Apple Hypervisor framework",
    b"ParavirtualizedGraphics.framework": "paravirtualized graphics stack",
    b"com.apple.security.virtualization": "virtualization entitlement",
    b"com.apple.Virtualization.VirtualMachine": "Virtualization XPC service",
    b"vmnet": "VM networking stack",
    b"install-launcher": "privileged installer launcher",
    b"VZKeyboardPassthrough": "SpringBoard keyboard passthrough tweak",
}
PACKAGE_PATH_MARKERS = {
    "var/root/VirtualMac": "shared VM/runtime payload",
    "var/jb/Applications/VirtualMac.app": "rootless application",
    "var/jb/Library/LaunchDaemons": "rootless launch daemons",
    "var/jb/basebin/LaunchDaemons": "Dopamine launch daemons",
    "var/jb/usr/libexec": "privileged helper executables",
    "var/root/VirtualMac/bootstrap-common/usr/lib/TweakInject": "tweak injection payload",
}
SOURCE_MARKERS = {
    "vz/uncache.py": "dyld shared-cache framework reconstruction",
    "vz/stamp_ios.py": "macOS framework iOS platform restamping",
    "vz/host/vmmhook.m": "VMM/Virtualization host hooks",
    "vz/host/vzxpchook.m": "Virtualization XPC hooks",
    "vz/host/installation_usb_shim.m": "userspace restore USB bridge",
    "scripts/build-ipad-deb.sh": "jailbreak DEB packager",
}


def _version(value: str | None) -> tuple[int, ...]:
    if not value:
        return (0,)
    found = re.findall(r"\d+", value)
    return tuple(int(x) for x in found[:3]) or (0,)


def _ar_members(data: bytes) -> list[tuple[str, bytes]]:
    if not data.startswith(b"!<arch>\n"):
        raise RuntimeError("Input is not a Debian ar archive")
    out: list[tuple[str, bytes]] = []
    pos = 8
    long_names = b""
    while pos + 60 <= len(data):
        header = data[pos : pos + 60]
        pos += 60
        if header[58:60] != b"`\n":
            raise RuntimeError("Malformed Debian archive header")
        name = header[:16].decode("utf-8", "replace").strip()
        size = int(header[48:58].decode("ascii", "replace").strip() or "0")
        if pos + size > len(data):
            raise RuntimeError("Truncated Debian archive")
        payload = data[pos : pos + size]
        pos += size + (size & 1)
        if name == "//":
            long_names = payload
            continue
        if name.startswith("#1/"):
            count = int(name[3:])
            name = payload[:count].decode("utf-8", "replace").rstrip("\0")
            payload = payload[count:]
        elif name.startswith("/") and name[1:].isdigit() and long_names:
            start = int(name[1:])
            end = long_names.find(b"/\n", start)
            name = long_names[start : end if end >= 0 else len(long_names)].decode("utf-8", "replace")
        else:
            name = name.rstrip("/")
        if name:
            out.append((name, payload))
    return out


def _parse_control(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    current: str | None = None
    for raw in text.splitlines():
        if raw.startswith((" ", "\t")) and current:
            fields[current] += "\n" + raw[1:]
            continue
        if ":" not in raw:
            current = None
            continue
        key, value = raw.split(":", 1)
        current = key.strip()
        fields[current] = value.strip()
    return fields


def _tar_member_bytes(archive: tarfile.TarFile, member: tarfile.TarInfo, limit: int = 8 * 1024 * 1024) -> bytes:
    if not member.isfile() or member.size <= 0 or member.size > limit:
        return b""
    handle = archive.extractfile(member)
    return handle.read(limit) if handle else b""


def inspect_deb(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    members = _ar_members(data)
    control_payload = next((body for name, body in members if name.startswith("control.tar")), None)
    data_payload = next((body for name, body in members if name.startswith("data.tar")), None)
    if control_payload is None or data_payload is None:
        raise RuntimeError("DEB is missing control.tar or data.tar")

    control: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(control_payload), mode="r:*") as archive:
        entry = next((m for m in archive.getmembers() if Path(m.name).name == "control"), None)
        if entry:
            control = _parse_control(_tar_member_bytes(archive, entry, 512 * 1024).decode("utf-8", "replace"))

    paths: list[str] = []
    runtime: dict[str, set[str]] = {}
    with tarfile.open(fileobj=io.BytesIO(data_payload), mode="r:*") as archive:
        for member in archive.getmembers():
            rel = member.name.lstrip("./")
            if rel:
                paths.append(rel)
            blob = _tar_member_bytes(archive, member)
            if not blob:
                continue
            hits = {description for marker, description in VM_MARKERS.items() if marker in blob}
            if hits:
                runtime[rel] = hits

    path_hits = {
        prefix: description
        for prefix, description in PACKAGE_PATH_MARKERS.items()
        if any(p == prefix or p.startswith(prefix + "/") for p in paths)
    }
    package = control.get("Package", "")
    is_virtualmac = package == VIRTUALMAC_PACKAGE or any(
        key in path_hits for key in ("var/root/VirtualMac", "var/jb/Applications/VirtualMac.app")
    )
    return {
        "kind": "deb",
        "path": str(path),
        "package": package,
        "name": control.get("Name", ""),
        "version": control.get("Version", ""),
        "architecture": control.get("Architecture", ""),
        "depends": control.get("Depends", ""),
        "isVirtualMac": is_virtualmac,
        "packagePaths": path_hits,
        "runtimeMarkers": {k: sorted(v) for k, v in sorted(runtime.items())},
        "payloadEntryCount": len(paths),
    }


def inspect_source(root: Path) -> dict[str, Any]:
    found = {
        relative: description
        for relative, description in SOURCE_MARKERS.items()
        if (root / relative).is_file()
    }
    content_hits: dict[str, list[str]] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > 2 * 1024 * 1024:
                continue
            blob = path.read_bytes()
        except OSError:
            continue
        hits = sorted({description for marker, description in VM_MARKERS.items() if marker in blob})
        if hits:
            content_hits[path.relative_to(root).as_posix()] = hits
    return {
        "kind": "source-tree",
        "path": str(root),
        "isVirtualMac": len(found) >= 3,
        "sourceMarkers": found,
        "runtimeMarkers": content_hits,
    }


def evaluate_target(*, is_virtualmac: bool, ios: str | None, chip: str | None) -> dict[str, Any]:
    chip_normalized = (chip or "").strip().lower().replace("apple ", "")
    ios_tuple = _version(ios)
    chip_supported = chip_normalized in {"m1", "m2"} if chip_normalized else None
    os_supported = ios_tuple < (16, 4) if ios else None

    reasons: list[str] = []
    if is_virtualmac:
        reasons.extend([
            "Virtual Mac requires a jailbreak package with privileged helpers, launch daemons, tweak injection, and extracted/patched Apple virtualization frameworks.",
            "A standalone stock-iOS IPA cannot provide the required VM runtime or private virtualization privileges.",
        ])
    if chip_supported is False:
        reasons.append(f"Chip {chip or 'unknown'} is outside upstream Virtual Mac's M1/M2 hardware support envelope.")
    if os_supported is False:
        reasons.append(f"iPadOS {ios} is 16.4 or newer; upstream documents removal of required Hypervisor kernel support in this range.")

    compatible = bool(is_virtualmac and chip_supported is True and os_supported is True)
    if is_virtualmac and (chip_supported is None or os_supported is None):
        target_status = "needs-device-details"
    elif compatible:
        target_status = "upstream-compatible"
    else:
        target_status = "incompatible"

    return {
        "targetStatus": target_status,
        "upstreamCompatible": compatible,
        "stockIpaSupported": False if is_virtualmac else None,
        "recommendedArtifact": "jailbreak-deb" if is_virtualmac else "normal-converter-routing",
        "recommendedPath": "source-build-or-current-upstream-deb" if is_virtualmac else "normal-converter-routing",
        "requiresJailbreak": True if is_virtualmac else None,
        "requiresHardwareVirtualization": True if is_virtualmac else None,
        "supportedChipFamilies": ["M1", "M2"] if is_virtualmac else [],
        "supportedOSRange": "iPadOS 14.0 through 16.3.1" if is_virtualmac else None,
        "reasons": reasons,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--deb", type=Path)
    source.add_argument("--source-tree", type=Path)
    parser.add_argument("--ios", default="")
    parser.add_argument("--chip", default="")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    profile = inspect_deb(args.deb) if args.deb else inspect_source(args.source_tree)
    profile["target"] = {"ios": args.ios or None, "chip": args.chip or None}
    profile["compatibility"] = evaluate_target(
        is_virtualmac=bool(profile.get("isVirtualMac")),
        ios=args.ios or None,
        chip=args.chip or None,
    )
    encoded = json.dumps(profile, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
