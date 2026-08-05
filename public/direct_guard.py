"""Whole-package compatibility guard for DebToIPA direct IPA mode.

Loaded after converter.py and before port_mode.py. It replaces convert_deb with a
conservative wrapper that audits the complete Debian payload, not only the main
app executable. Packages with jailbreak daemons, root payloads, private
entitlements/frameworks, process injection, or dynamically loaded absolute paths
are blocked from Direct IPA so Smart Auto can route them to Port Mode.
"""
import hashlib
import io
import json
import os
import plistlib
import tarfile
import tempfile
import zipfile
from pathlib import Path

_ORIGINAL_CONVERT_DEB = globals().get("convert_deb")

RISKY_PATH_PREFIXES = {
    "Library/MobileSubstrate/DynamicLibraries": "MobileSubstrate injection payload",
    "var/jb/Library/MobileSubstrate/DynamicLibraries": "rootless MobileSubstrate injection payload",
    "Library/LaunchDaemons": "system launch daemon",
    "var/jb/Library/LaunchDaemons": "rootless system launch daemon",
    "var/jb/basebin/LaunchDaemons": "bootstrap launch daemon",
    "var/jb/usr/libexec": "jailbreak helper executable",
    "var/jb/usr/sbin": "jailbreak system executable",
    "var/root": "root-owned runtime payload",
}

RUNTIME_MARKERS = {
    b"/var/root/": "absolute /var/root runtime dependency",
    b"/var/jb/": "absolute /var/jb runtime dependency",
    b"/Library/MobileSubstrate": "MobileSubstrate runtime dependency",
    b"MobileSubstrate": "MobileSubstrate injection dependency",
    b"ElleKit": "ElleKit injection dependency",
    b"libhooker": "libhooker injection dependency",
    b"Virtualization.framework": "private macOS Virtualization framework dependency",
    b"Hypervisor.framework": "private hypervisor framework dependency",
    b"ParavirtualizedGraphics.framework": "private paravirtualized graphics dependency",
    b"vmnet.framework": "private vmnet framework dependency",
    b"com.apple.private.": "private Apple entitlement or service dependency",
    b"com.apple.security.virtualization": "virtualization entitlement dependency",
    b"com.apple.vm.networking": "private VM networking entitlement dependency",
    b"com.apple.Virtualization.VirtualMachine": "private virtualization XPC service dependency",
    b"task_for_pid": "task-for-pid process control dependency",
    b"sandbox_extension_issue": "private sandbox-extension dependency",
}

MACHO_MAGICS = {
    b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xce",
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca",
}


def _ar_members(data):
    if not data.startswith(b"!<arch>\n"):
        raise RuntimeError("Input is not a valid Debian archive.")
    out, pos, long_names = [], 8, b""
    while pos + 60 <= len(data):
        header, pos = data[pos:pos + 60], pos + 60
        if header[58:60] != b"`\n":
            raise RuntimeError("Malformed Debian archive member.")
        name = header[:16].decode("utf-8", "replace").strip()
        try:
            size = int(header[48:58].decode().strip() or "0")
        except ValueError as exc:
            raise RuntimeError("Invalid Debian archive size.") from exc
        if pos + size > len(data):
            raise RuntimeError("Truncated Debian archive.")
        payload, pos = data[pos:pos + size], pos + size + (size & 1)
        if name == "//":
            long_names = payload
            continue
        if name.startswith("#1/"):
            count = int(name[3:])
            name, payload = payload[:count].decode("utf-8", "replace").rstrip("\0"), payload[count:]
        elif name.startswith("/") and name[1:].isdigit() and long_names:
            start = int(name[1:])
            end = long_names.find(b"/\n", start)
            name = long_names[start:end if end >= 0 else len(long_names)].decode("utf-8", "replace")
        else:
            name = name.rstrip("/")
        if name:
            out.append((name, payload))
    return out


def _extract_tar(payload, destination):
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
        base = destination.resolve()
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if target != base and base not in target.parents:
                raise RuntimeError(f"Unsafe path in payload: {member.name}")
        try:
            archive.extractall(destination, filter="data")
        except TypeError:
            archive.extractall(destination)


def _is_macho(data):
    return len(data) >= 4 and data[:4] in MACHO_MAGICS


def _version_tuple(value):
    try:
        parts = [int(piece) for piece in str(value).split(".")[:3]]
        return tuple(parts + [0] * (3 - len(parts)))
    except (TypeError, ValueError):
        return (0, 0, 0)


def audit_deb_package(input_path):
    source = Path(input_path)
    data = source.read_bytes()
    members = _ar_members(data)
    payload = next((body for name, body in members if name.startswith("data.tar")), None)
    if payload is None:
        raise RuntimeError("Debian archive has no data.tar payload.")

    findings = []
    runtime_hits = []
    macho_files = []
    app_candidates = []
    original_minimum_ios = None

    with tempfile.TemporaryDirectory(prefix="debtoipa-guard-") as temp:
        root = Path(temp)
        _extract_tar(payload, root)
        paths = sorted(str(path.relative_to(root)).replace(os.sep, "/") for path in root.rglob("*"))

        for prefix, reason in RISKY_PATH_PREFIXES.items():
            matches = [path for path in paths if path == prefix or path.startswith(prefix + "/")]
            if matches:
                findings.append({"kind": "package-path", "reason": reason, "path": prefix, "count": len(matches)})

        for app in root.rglob("*.app"):
            if not app.is_dir() or not (app / "Info.plist").is_file():
                continue
            app_candidates.append(str(app.relative_to(root)).replace(os.sep, "/"))
            try:
                with (app / "Info.plist").open("rb") as handle:
                    plist = plistlib.load(handle)
                current = plist.get("MinimumOSVersion") if isinstance(plist, dict) else None
                if current and (_version_tuple(current) > _version_tuple(original_minimum_ios)):
                    original_minimum_ios = str(current)
            except Exception:
                pass

        for path in root.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            try:
                size = path.stat().st_size
                if size <= 0 or size > 96 * 1024 * 1024:
                    continue
                blob = path.read_bytes()
            except OSError:
                continue
            if not _is_macho(blob):
                continue
            relative = str(path.relative_to(root)).replace(os.sep, "/")
            macho_files.append(relative)
            hits = sorted({description for marker, description in RUNTIME_MARKERS.items() if marker in blob})
            if hits:
                runtime_hits.append({"path": relative, "dependencies": hits})

        if runtime_hits:
            findings.append({
                "kind": "runtime-reference",
                "reason": "Mach-O files contain jailbreak-only, private-framework, private-entitlement, or root-path dependencies",
                "files": runtime_hits,
            })

        app_roots = [candidate.rstrip("/") + "/" for candidate in app_candidates]
        external_runtime_files = [
            relative for relative in macho_files
            if not any(relative.startswith(app_root) for app_root in app_roots)
        ]
        if external_runtime_files:
            findings.append({
                "kind": "external-runtime",
                "reason": "native helper executables exist outside the app bundle and would be omitted from a direct IPA",
                "files": external_runtime_files,
            })

    blockers = []
    for finding in findings:
        if finding["kind"] == "package-path":
            blockers.append(f"Package includes {finding['reason']} at {finding['path']}.")
        elif finding["kind"] == "runtime-reference":
            names = ", ".join(item["path"] for item in finding["files"][:8])
            blockers.append(f"Package Mach-O files use restricted runtime dependencies ({names}).")
        elif finding["kind"] == "external-runtime":
            names = ", ".join(finding["files"][:8])
            blockers.append(f"Package needs native helpers outside the app bundle that a direct IPA would omit: {names}.")

    return {
        "archiveMembers": [name for name, _ in members],
        "appCandidates": app_candidates,
        "machoFiles": macho_files,
        "findings": findings,
        "blockers": blockers,
        "originalMinimumOSVersion": original_minimum_ios,
    }


def _write_blocked_result(input_path, output_path, options_json, audit):
    options = json.loads(options_json or "{}")
    source = Path(input_path)
    source_name = str(options.get("sourceName") or source.name)
    base = Path(source_name).stem or "Converted"
    blockers = audit.get("blockers") or ["Whole-package compatibility audit blocked Direct IPA creation."]
    requested = str(options.get("minimumIos") or "")
    original = audit.get("originalMinimumOSVersion")
    warnings = []
    if original and requested and _version_tuple(requested) < _version_tuple(original):
        warnings.append(f"Requested minimum iOS {requested} is lower than the app's original minimum iOS {original}; DebToIPA will not downgrade it.")
    report = {
        "schemaVersion": 3,
        "engine": "DebToIPA whole-package compatibility guard",
        "source": {
            "name": source_name,
            "size": source.stat().st_size,
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "archiveMembers": audit.get("archiveMembers", []),
        },
        "target": options,
        "verdict": "blocked",
        "blockers": blockers,
        "warnings": warnings,
        "analysis": {"wholePackageAudit": audit},
        "error": "Direct IPA blocked before packaging because required runtime components are unavailable on stock iOS.",
    }
    with zipfile.ZipFile(output_path, "w", allowZip64=True) as archive:
        archive.writestr("compatibility-report.json", json.dumps(report, indent=2), compress_type=zipfile.ZIP_DEFLATED)
    return json.dumps({
        "verdict": "blocked",
        "artifactName": f"{base}-DebToIPA-result.zip",
        "blockers": blockers,
        "warnings": warnings,
    })


def guarded_convert_deb(input_path, output_path, options_json):
    audit = audit_deb_package(input_path)
    if audit.get("blockers"):
        return _write_blocked_result(input_path, output_path, options_json, audit)
    if _ORIGINAL_CONVERT_DEB is None:
        raise RuntimeError("DebToIPA direct converter was not loaded before the compatibility guard.")

    options = json.loads(options_json or "{}")
    original = audit.get("originalMinimumOSVersion")
    requested = str(options.get("minimumIos") or "")
    if original and _version_tuple(requested) < _version_tuple(original):
        options["minimumIos"] = original
    return _ORIGINAL_CONVERT_DEB(input_path, output_path, json.dumps(options))


if _ORIGINAL_CONVERT_DEB is not None:
    convert_deb = guarded_convert_deb
