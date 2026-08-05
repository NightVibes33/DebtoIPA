#!/usr/bin/env python3
"""Run DebToIPA Smart Auto on a GitHub macOS runner.

A successful run has one strict meaning: the generated IPA contains the original
application binary from the uploaded Debian package. DebToIPA never substitutes
its generic compatibility host and never reports a source-level port as a
successful conversion.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import plistlib
import sys
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
COMPATIBILITY_HOST_EXECUTABLE = "DebToIPACompatibilityHost"


def load_engine() -> dict[str, Any]:
    namespace: dict[str, Any] = {
        "__name__": "debtoipa_runner_engine",
        "__file__": str(PUBLIC / "converter.py"),
    }

    def execute(path: Path, source: str | None = None) -> None:
        text = source if source is not None else path.read_text(encoding="utf-8")
        exec(compile(text, str(path), "exec"), namespace)

    execute(PUBLIC / "converter.py")
    execute(PUBLIC / "direct_guard.py")
    encoded = (PUBLIC / "port_mode.py.gz.b64").read_text(encoding="utf-8").strip()
    port_source = gzip.decompress(base64.b64decode(encoded)).decode("utf-8")
    execute(PUBLIC / "port_mode.py", port_source)
    return namespace


def validate_ipa_bytes(data: bytes) -> dict[str, Any]:
    macho_magics = {
        b"\xcf\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf",
        b"\xce\xfa\xed\xfe",
        b"\xfe\xed\xfa\xce",
        b"\xca\xfe\xba\xbe",
        b"\xbe\xba\xfe\xca",
        b"\xca\xfe\xba\xbf",
        b"\xbf\xba\xfe\xca",
    }
    with zipfile.ZipFile(BytesIO(data)) as archive:
        names = archive.namelist()
        plist_names = [
            name
            for name in names
            if name.startswith("Payload/")
            and name.count("/") == 2
            and name.endswith(".app/Info.plist")
        ]
        if len(plist_names) != 1:
            raise RuntimeError(
                "IPA must contain exactly one top-level app Info.plist; "
                f"found {len(plist_names)}."
            )
        plist_name = plist_names[0]
        plist = plistlib.loads(archive.read(plist_name))
        executable_name = plist.get("CFBundleExecutable")
        if not isinstance(executable_name, str) or not executable_name:
            raise RuntimeError("Generated IPA has no CFBundleExecutable.")
        app_root = plist_name.rsplit("/", 1)[0]
        executable_path = f"{app_root}/{executable_name}"
        if executable_path not in names:
            raise RuntimeError(f"Generated IPA is missing executable {executable_name}.")
        executable = archive.read(executable_path)
        if executable[:4] not in macho_magics:
            raise RuntimeError("Generated app executable is not Mach-O.")
        if executable_name == COMPATIBILITY_HOST_EXECUTABLE:
            raise RuntimeError(
                "Refusing DebToIPA's generic compatibility host. "
                "It is not the uploaded app."
            )
        return {
            "bundleIdentifier": plist.get("CFBundleIdentifier"),
            "displayName": plist.get("CFBundleDisplayName") or plist.get("CFBundleName"),
            "minimumIOS": plist.get("MinimumOSVersion"),
            "executable": executable_name,
            "entryCount": len(names),
        }


def read_report(result_zip: Path) -> dict[str, Any]:
    with zipfile.ZipFile(result_zip) as archive:
        return json.loads(archive.read("compatibility-report.json"))


def extract_real_ipas(result_zip: Path, output_dir: Path) -> list[dict[str, Any]]:
    extracted: list[dict[str, Any]] = []
    with zipfile.ZipFile(result_zip) as archive:
        for name in archive.namelist():
            if "/" in name or not name.lower().endswith(".ipa"):
                continue
            data = archive.read(name)
            validation = validate_ipa_bytes(data)
            destination = output_dir / Path(name).name
            destination.write_bytes(data)
            extracted.append(
                {"name": destination.name, "size": len(data), "validation": validation}
            )
    return extracted


def direct_conversion_succeeded(
    initial_verdict: str, report: dict[str, Any], ipas: list[dict[str, Any]]
) -> bool:
    verdict = str(report.get("verdict") or initial_verdict)
    return verdict == "packaged" and initial_verdict == "packaged" and bool(ipas)


def write_result_files(
    output_dir: Path, summary: dict[str, Any], report: dict[str, Any]
) -> None:
    (output_dir / "conversion-report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    (output_dir / "runner-summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    lines = [
        "DebToIPA runner result",
        f"Job: {summary['jobId']}",
        f"Source: {summary['sourceName']}",
        f"Verdict: {summary['verdict']}",
        f"Original app binary packaged: {summary['originalBinaryExecuted']}",
        f"Generated real IPA count: {len(summary['ipas'])}",
        "",
    ]
    if summary.get("error"):
        lines += ["Result:", f"- {summary['error']}", ""]
    if summary.get("warnings"):
        lines += ["Warnings:", *[f"- {item}" for item in summary["warnings"]], ""]
    if summary.get("blockers"):
        lines += [
            "Original-binary blockers:",
            *[f"- {item}" for item in summary["blockers"]],
            "",
        ]
    (output_dir / "README.txt").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deb", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--source-name", required=True)
    parser.add_argument(
        "--device", choices=["universal", "iphone", "ipad"], default="universal"
    )
    parser.add_argument("--minimum-ios", default="15.0")
    parser.add_argument("--bundle-id", default="")
    parser.add_argument("--display-name", default="")
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    result_zip = output_dir / f"DebToIPA-{args.job_id}.zip"
    options = {
        "sourceName": args.source_name,
        "mode": "auto",
        "device": args.device,
        "minimumIos": args.minimum_ios,
        "bundleId": args.bundle_id,
        "displayName": args.display_name,
    }

    summary: dict[str, Any] = {
        "schemaVersion": 2,
        "jobId": args.job_id,
        "sourceName": args.source_name,
        "runner": "github-macos",
        "verdict": "failed",
        "ipas": [],
        "originalBinaryExecuted": False,
        "featureComplete": False,
    }
    report: dict[str, Any] = {}

    try:
        if not args.deb.is_file():
            raise RuntimeError("Downloaded Debian package is missing.")

        print("::notice title=DebToIPA::Auditing complete Debian payload")
        engine = load_engine()
        convert = engine.get("convert_deb_with_port")
        if not callable(convert):
            raise RuntimeError("Smart Auto converter did not load.")

        raw = json.loads(convert(str(args.deb), str(result_zip), json.dumps(options)))
        initial_verdict = str(raw.get("verdict") or "blocked")
        summary["initialVerdict"] = initial_verdict

        report = read_report(result_zip)
        summary["warnings"] = list(report.get("warnings") or [])
        summary["blockers"] = list(report.get("blockers") or [])

        ipas: list[dict[str, Any]] = []
        if initial_verdict == "packaged":
            ipas = extract_real_ipas(result_zip, output_dir)

        if direct_conversion_succeeded(initial_verdict, report, ipas):
            summary["verdict"] = "packaged-original-app"
            summary["ipas"] = ipas
            summary["originalBinaryExecuted"] = True
            summary["featureComplete"] = True
            write_result_files(output_dir, summary, report)
            print(json.dumps(summary, indent=2))
            return 0

        summary["verdict"] = "unsupported-no-real-ipa"
        summary["error"] = (
            "No real IPA was created. The original app binary cannot run as a "
            "normal sideloaded iOS app without unavailable jailbreak services, "
            "private entitlements, or package-specific source code changes. "
            "The artifact contains only the compatibility report and generated "
            "port project."
        )
        write_result_files(output_dir, summary, report)
        print(
            "::error title=No real IPA produced::"
            "DebToIPA refused to substitute a generic compatibility-shell app."
        )
        return 3
    except Exception as error:
        summary["error"] = str(error)
        if report:
            summary["warnings"] = list(report.get("warnings") or [])
            summary["blockers"] = list(report.get("blockers") or [])
        write_result_files(output_dir, summary, report)
        print(f"::error title=DebToIPA runner failed::{error}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
