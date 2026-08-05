#!/usr/bin/env python3
"""Build IPAs that preserve an original app executable from the input DEB.

DebToIPA never substitutes a generated compatibility shell.

Exit codes:
- 0: an original app IPA was produced and static compatibility checks found no blockers;
- 3: an original app IPA was preserved, but stock-iOS blockers remain;
- 2: no standalone original app IPA could be produced.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import io
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
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
COMPATIBILITY_HOST_EXECUTABLE = "DebToIPACompatibilityHost"
MACHO = {
    b"\xcf\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xce",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf",
    b"\xbf\xba\xfe\xca",
}


def load_engine() -> dict[str, Any]:
    ns: dict[str, Any] = {
        "__name__": "debtoipa_runner_engine",
        "__file__": str(PUBLIC / "converter.py"),
    }

    def run(path: Path, source: str | None = None) -> None:
        text = source if source is not None else path.read_text(encoding="utf-8")
        exec(compile(text, str(path), "exec"), ns)

    run(PUBLIC / "converter.py")
    run(PUBLIC / "direct_guard.py")
    encoded = (PUBLIC / "port_mode.py.gz.b64").read_text(encoding="utf-8").strip()
    run(
        PUBLIC / "port_mode.py",
        gzip.decompress(base64.b64decode(encoded)).decode("utf-8"),
    )
    return ns


def validate_ipa_bytes(data: bytes) -> dict[str, Any]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        plists = [
            name
            for name in names
            if name.startswith("Payload/")
            and name.count("/") == 2
            and name.endswith(".app/Info.plist")
        ]
        if len(plists) != 1:
            raise RuntimeError(
                f"IPA must contain exactly one top-level app; found {len(plists)}."
            )
        plist_name = plists[0]
        plist = plistlib.loads(archive.read(plist_name))
        executable = plist.get("CFBundleExecutable")
        if not isinstance(executable, str) or not executable:
            raise RuntimeError("IPA has no CFBundleExecutable.")
        if executable == COMPATIBILITY_HOST_EXECUTABLE:
            raise RuntimeError(
                "Refusing DebToIPA's generic compatibility host because it is "
                "not the uploaded app."
            )
        executable_path = f"{plist_name.rsplit('/', 1)[0]}/{executable}"
        if executable_path not in names:
            raise RuntimeError(f"IPA is missing original executable {executable}.")
        binary = archive.read(executable_path)
        if binary[:4] not in MACHO:
            raise RuntimeError("IPA executable is not Mach-O.")
        return {
            "bundleIdentifier": plist.get("CFBundleIdentifier"),
            "displayName": plist.get("CFBundleDisplayName")
            or plist.get("CFBundleName"),
            "minimumIOS": plist.get("MinimumOSVersion"),
            "executable": executable,
            "executableSha256": hashlib.sha256(binary).hexdigest(),
            "entryCount": len(names),
        }


def read_report(result_zip: Path) -> dict[str, Any]:
    with zipfile.ZipFile(result_zip) as archive:
        return json.loads(archive.read("compatibility-report.json"))


def extract_ipas(result_zip: Path, output_dir: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    with zipfile.ZipFile(result_zip) as archive:
        for name in archive.namelist():
            if "/" in name or not name.lower().endswith(".ipa"):
                continue
            data = archive.read(name)
            destination = output_dir / Path(name).name
            destination.write_bytes(data)
            results.append(
                {
                    "name": destination.name,
                    "size": len(data),
                    "validation": validate_ipa_bytes(data),
                }
            )
    return results


def extract_deb_payload(deb: Path, destination: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="debtoipa-ar-") as temporary:
        members = Path(temporary)
        subprocess.run(["ar", "x", str(deb.resolve())], cwd=members, check=True)
        payload = next(iter(sorted(members.glob("data.tar*"))), None)
        if payload is None:
            raise RuntimeError("Debian package has no data.tar payload.")
        listing = subprocess.check_output(["tar", "-tf", str(payload)], text=True)
        for item in listing.splitlines():
            path = Path(item)
            if path.is_absolute() or ".." in path.parts:
                raise RuntimeError(f"Unsafe path in Debian payload: {item}")
        destination.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["tar", "-xf", str(payload), "-C", str(destination)], check=True
        )


def find_original_apps(root: Path) -> list[Path]:
    found: list[tuple[int, Path]] = []
    for app in root.rglob("*.app"):
        if not app.is_dir() or any(parent.suffix == ".app" for parent in app.parents):
            continue
        plist_path = app / "Info.plist"
        if not plist_path.is_file():
            continue
        try:
            plist = plistlib.loads(plist_path.read_bytes())
            executable = plist.get("CFBundleExecutable")
            binary = app / str(executable)
            if (
                not executable
                or executable == COMPATIBILITY_HOST_EXECUTABLE
                or not binary.is_file()
                or binary.read_bytes()[:4] not in MACHO
            ):
                continue
        except Exception:
            continue
        relative = app.relative_to(root).as_posix().lower()
        score = (
            100 if "/applications/" in f"/{relative}" else 0
        ) - len(app.relative_to(root).parts)
        found.append((score, app))
    return [
        app
        for _, app in sorted(found, key=lambda value: (-value[0], str(value[1])))
    ]


def version(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError:
        return (0,)


def zip_fallback(root: Path, destination: Path) -> None:
    with zipfile.ZipFile(
        destination, "w", zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                info = zipfile.ZipInfo(relative)
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, os.readlink(path))
            elif path.is_file():
                info = zipfile.ZipInfo.from_file(
                    path, relative, strict_timestamps=False
                )
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, path.read_bytes())


def package_original_app(
    app: Path,
    output_dir: Path,
    source_name: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="debtoipa-original-") as temporary:
        stage = Path(temporary)
        payload = stage / "Payload"
        payload.mkdir()
        staged = payload / app.name
        shutil.copytree(app, staged, symlinks=True)
        shutil.rmtree(staged / "_CodeSignature", ignore_errors=True)
        (staged / "embedded.mobileprovision").unlink(missing_ok=True)

        plist_path = staged / "Info.plist"
        plist = plistlib.loads(plist_path.read_bytes())
        requested = str(options.get("minimumIos") or "")
        current = str(plist.get("MinimumOSVersion") or "0")
        if requested and version(requested) > version(current):
            plist["MinimumOSVersion"] = requested
        if options.get("bundleId"):
            plist["CFBundleIdentifier"] = str(options["bundleId"])
        if options.get("displayName"):
            plist["CFBundleDisplayName"] = str(options["displayName"])
            plist["CFBundleName"] = str(options["displayName"])
        if options.get("device") == "iphone":
            plist["UIDeviceFamily"] = [1]
        elif options.get("device") == "ipad":
            plist["UIDeviceFamily"] = [2]
        plist_path.write_bytes(
            plistlib.dumps(plist, fmt=plistlib.FMT_BINARY, sort_keys=False)
        )

        stem = Path(source_name).stem
        suffix = "" if app.stem.lower() in stem.lower() else f"-{app.stem}"
        destination = output_dir / f"{stem}{suffix}-Original-unsigned.ipa"
        if shutil.which("ditto"):
            subprocess.run(
                [
                    "ditto",
                    "-c",
                    "-k",
                    "--sequesterRsrc",
                    "--keepParent",
                    "Payload",
                    str(destination),
                ],
                cwd=stage,
                check=True,
            )
        else:
            zip_fallback(stage, destination)
        return {
            "name": destination.name,
            "size": destination.stat().st_size,
            "kind": "original-app-bundle",
            "sourceAppPath": app.as_posix(),
            "validation": validate_ipa_bytes(destination.read_bytes()),
        }


def append_ipas(
    result_zip: Path, output_dir: Path, ipas: list[dict[str, Any]]
) -> None:
    with zipfile.ZipFile(
        result_zip, "a", zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        existing = set(archive.namelist())
        for item in ipas:
            path = output_dir / item["name"]
            if path.name not in existing:
                archive.write(path, path.name)


def classify_result(
    has_original_ipa: bool, blockers: list[Any]
) -> tuple[str, str, bool, int]:
    if has_original_ipa and not blockers:
        return "packaged", "real-ipa", True, 0
    if has_original_ipa:
        return "original-packaged-blocked", "original-blocked", False, 3
    return "blocked-no-standalone-app", "unsupported", False, 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deb", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--source-name", required=True)
    parser.add_argument(
        "--device",
        choices=["universal", "iphone", "ipad"],
        default="universal",
    )
    parser.add_argument("--minimum-ios", default="15.0")
    parser.add_argument("--bundle-id", default="")
    parser.add_argument("--display-name", default="")
    args = parser.parse_args()

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    result_zip = output / f"DebToIPA-{args.job_id}.zip"
    options = {
        "sourceName": args.source_name,
        "mode": "auto",
        "device": args.device,
        "minimumIos": args.minimum_ios,
        "bundleId": args.bundle_id,
        "displayName": args.display_name,
    }
    summary: dict[str, Any] = {
        "schemaVersion": 3,
        "jobId": args.job_id,
        "sourceName": args.source_name,
        "runner": "github-macos",
        "verdict": "failed",
        "resultKind": "unsupported",
        "stage": "initializing",
        "ipas": [],
        "compatibilityHostGenerated": False,
        "originalBinaryPackaged": False,
        "originalBinaryExecuted": False,
        "featureComplete": False,
    }

    try:
        engine = load_engine()
        convert = engine.get("convert_deb_with_port")
        if not args.deb.is_file() or not callable(convert):
            raise RuntimeError("Input package or converter is missing.")

        raw = json.loads(
            convert(str(args.deb), str(result_zip), json.dumps(options))
        )
        report = read_report(result_zip)
        summary["initialVerdict"] = raw.get("verdict") or report.get("verdict")
        summary["warnings"] = list(report.get("warnings") or [])
        summary["blockers"] = list(report.get("blockers") or [])
        summary["ipas"] = extract_ipas(result_zip, output)

        if not summary["ipas"]:
            with tempfile.TemporaryDirectory(
                prefix="debtoipa-payload-"
            ) as temporary:
                payload_root = Path(temporary)
                extract_deb_payload(args.deb, payload_root)
                apps = find_original_apps(payload_root)
                if apps:
                    summary["ipas"] = [
                        package_original_app(
                            app, output, args.source_name, options
                        )
                        for app in apps
                    ]
                    append_ipas(result_zip, output, summary["ipas"])
                    summary["warnings"].insert(
                        0,
                        "The artifact contains the package's actual original "
                        "executable, not a generated shell. Stock iOS may still "
                        "reject or terminate it because the listed blockers remain.",
                    )

        verdict, result_kind, feature_complete, exit_code = classify_result(
            bool(summary["ipas"]), summary["blockers"]
        )
        summary["verdict"] = verdict
        summary["resultKind"] = result_kind
        summary["featureComplete"] = feature_complete
        summary["originalBinaryPackaged"] = bool(summary["ipas"])
        summary["stage"] = {
            "real-ipa": "complete",
            "original-blocked": "original-app-preserved-with-blockers",
            "unsupported": "report-only",
        }[result_kind]

        report["verdict"] = summary["verdict"]
        report["resultKind"] = summary["resultKind"]
        report["warnings"] = summary["warnings"]
        report["output"] = {
            **(report.get("output") or {}),
            "featureComplete": summary["featureComplete"],
            "originalBinaryPackaged": summary["originalBinaryPackaged"],
            "originalBinaryExecuted": False,
            "compatibilityHostGenerated": False,
            "ipaNames": [item["name"] for item in summary["ipas"]],
        }

        (output / "conversion-report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        (output / "runner-summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
        lines = [
            "DebToIPA runner result",
            f"Verdict: {summary['verdict']}",
            f"Result kind: {summary['resultKind']}",
            f"Original binary packaged: {summary['originalBinaryPackaged']}",
            f"Feature complete on stock iOS: {summary['featureComplete']}",
            "Generated compatibility host: False",
            f"IPA count: {len(summary['ipas'])}",
            "",
        ]
        if summary["warnings"]:
            lines += [
                "Warnings:",
                *[f"- {item}" for item in summary["warnings"]],
                "",
            ]
        if summary["blockers"]:
            lines += [
                "Stock-iOS blockers:",
                *[f"- {item}" for item in summary["blockers"]],
                "",
            ]
        (output / "README.txt").write_text(
            "\n".join(lines), encoding="utf-8"
        )
        print(json.dumps(summary, indent=2))
        if result_kind == "original-blocked":
            print(
                "::warning title=Original app preserved with blockers::"
                "The artifact contains the real executable, but this is not a "
                "successful stock-iOS conversion."
            )
        elif result_kind == "unsupported":
            print(
                "::error title=No standalone original app::"
                "No real IPA could be produced."
            )
        return exit_code
    except Exception as error:
        summary["error"] = str(error)
        (output / "runner-summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
        (output / "README.txt").write_text(
            f"DebToIPA runner failed\n\n{error}\n", encoding="utf-8"
        )
        print(f"::error title=DebToIPA runner failed::{error}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
