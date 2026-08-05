#!/usr/bin/env python3
"""Run DebToIPA Smart Auto on a GitHub macOS runner.

The runner uses one audited engine for all outcomes:
1. package a directly compatible app;
2. generate a Port Project when the original binary is blocked;
3. compile the Swift compatibility host with Xcode and inject translated resources.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import plistlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"


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
    execute(PUBLIC / "host_mode.py")
    return namespace


def validate_ipa_bytes(data: bytes) -> dict[str, Any]:
    macho_magics = {
        b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xce",
        b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca",
    }
    from io import BytesIO
    with zipfile.ZipFile(BytesIO(data)) as archive:
        names = archive.namelist()
        plist_names = [name for name in names if name.startswith("Payload/") and name.count("/") == 2 and name.endswith(".app/Info.plist")]
        if len(plist_names) != 1:
            raise RuntimeError(f"IPA must contain exactly one top-level app Info.plist; found {len(plist_names)}.")
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


def extract_ipas(result_zip: Path, output_dir: Path) -> list[dict[str, Any]]:
    extracted: list[dict[str, Any]] = []
    with zipfile.ZipFile(result_zip) as archive:
        for name in archive.namelist():
            if "/" in name or not name.lower().endswith(".ipa"):
                continue
            data = archive.read(name)
            validation = validate_ipa_bytes(data)
            destination = output_dir / Path(name).name
            destination.write_bytes(data)
            extracted.append({"name": destination.name, "size": len(data), "validation": validation})
    return extracted


def build_host_template(output_dir: Path) -> Path:
    template_dir = output_dir / "host-template"
    template_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["bash", str(ROOT / "scripts" / "build_compatibility_host.sh"), str(template_dir.resolve())],
        cwd=ROOT,
        check=True,
    )
    template = template_dir / "DebToIPA-CompatibilityHost-template.ipa"
    if not template.is_file():
        raise RuntimeError("Xcode completed without producing the compatibility host template.")
    validate_ipa_bytes(template.read_bytes())
    return template


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deb", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--source-name", required=True)
    parser.add_argument("--device", choices=["universal", "iphone", "ipad"], default="universal")
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
        "jobId": args.job_id,
        "sourceName": args.source_name,
        "runner": "github-macos",
        "verdict": "failed",
        "stage": "initializing",
        "ipas": [],
    }

    try:
        if not args.deb.is_file():
            raise RuntimeError("Downloaded Debian package is missing.")
        print("::notice title=DebToIPA::Auditing complete Debian payload")
        engine = load_engine()
        convert = engine.get("convert_deb_with_port")
        if not callable(convert):
            raise RuntimeError("Smart Auto converter did not load.")

        raw = json.loads(convert(str(args.deb), str(result_zip), json.dumps(options)))
        summary["initialVerdict"] = raw.get("verdict")

        if raw.get("verdict") == "port-project":
            print("::notice title=DebToIPA::Original binary blocked; compiling stock-iOS replacement host")
            template = build_host_template(output_dir)
            host_builder = engine.get("build_host_ipa_from_port_result")
            if not callable(host_builder):
                raise RuntimeError("Compatibility host builder did not load.")
            raw = json.loads(host_builder(str(result_zip), str(template), json.dumps(options)))

        report = read_report(result_zip)
        verdict = str(report.get("verdict") or raw.get("verdict") or "blocked")
        summary["verdict"] = verdict
        summary["featureComplete"] = bool((report.get("output") or {}).get("featureComplete", verdict == "packaged"))
        summary["originalBinaryExecuted"] = bool((report.get("output") or {}).get("originalBinaryExecuted", verdict == "packaged"))
        summary["warnings"] = list(report.get("warnings") or [])
        summary["blockers"] = list(report.get("blockers") or [])
        summary["ipas"] = extract_ipas(result_zip, output_dir)

        (output_dir / "conversion-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (output_dir / "runner-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

        lines = [
            "DebToIPA runner result",
            f"Job: {args.job_id}",
            f"Source: {args.source_name}",
            f"Verdict: {verdict}",
            f"Feature complete: {summary['featureComplete']}",
            f"Generated IPA count: {len(summary['ipas'])}",
            "",
        ]
        if summary["warnings"]:
            lines += ["Warnings:", *[f"- {item}" for item in summary["warnings"]], ""]
        if summary["blockers"]:
            lines += ["Original-binary blockers:", *[f"- {item}" for item in summary["blockers"]], ""]
        (output_dir / "README.txt").write_text("\n".join(lines), encoding="utf-8")

        if verdict not in {"packaged", "host-packaged"} or not summary["ipas"]:
            raise RuntimeError("Smart Auto did not produce a validated IPA.")

        print(json.dumps(summary, indent=2))
        if verdict == "host-packaged" and not summary["featureComplete"]:
            print("::warning title=Partial replacement::The IPA launches, but the report lists behavior that still requires a package-specific public-API implementation.")
        return 0
    except Exception as error:
        summary["error"] = str(error)
        (output_dir / "runner-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        if not (output_dir / "README.txt").exists():
            (output_dir / "README.txt").write_text(f"DebToIPA runner failed\n\n{error}\n", encoding="utf-8")
        print(f"::error title=DebToIPA runner failed::{error}")
        return 2
    finally:
        shutil.rmtree(output_dir / "host-template", ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
