#!/usr/bin/env python3
"""DebToIPA full conversion pipeline.

Order of operations:
1. Run the original-binary analyzer and packager.
2. If that cannot produce a usable stock-iOS IPA, look for constrained source
   inside the DEB and rebuild it directly with Apple's iPhoneOS compiler.
3. Never run package scripts and never substitute a generic compatibility app.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import runner_smart_auto as baseline
from source_port import SourcePortError, build_source_port


def _copy_tree_contents(
    source: Path,
    destination: Path,
    *,
    skip: set[str],
    skip_ipas: bool = False,
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for path in source.iterdir():
        if path.name in skip or (skip_ipas and path.suffix.lower() == ".ipa"):
            continue
        target = destination / path.name
        if path.is_dir():
            shutil.copytree(path, target, dirs_exist_ok=True)
        else:
            shutil.copy2(path, target)


def _load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else default
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default


def _write_final_archive(
    baseline_archive: Path,
    destination: Path,
    ipa: Path,
    report: dict[str, Any],
    summary: dict[str, Any],
    source_report: Path,
) -> None:
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        if baseline_archive.is_file():
            with zipfile.ZipFile(baseline_archive) as original:
                for info in original.infolist():
                    name = info.filename
                    if name == "compatibility-report.json" or name.lower().endswith(".ipa"):
                        continue
                    output.writestr(info, original.read(name))
        output.write(ipa, ipa.name, compress_type=zipfile.ZIP_STORED)
        output.writestr("compatibility-report.json", json.dumps(report, indent=2))
        output.writestr("runner-summary.json", json.dumps(summary, indent=2))
        output.write(source_report, "source-port-report.json")


def _run_baseline(args: argparse.Namespace, directory: Path) -> int:
    command = [
        sys.executable,
        str(Path(__file__).with_name("runner_smart_auto.py")),
        "--deb", str(args.deb),
        "--output-dir", str(directory),
        "--job-id", args.job_id,
        "--source-name", args.source_name,
        "--device", args.device,
        "--minimum-ios", args.minimum_ios,
        "--bundle-id", args.bundle_id,
        "--display-name", args.display_name,
    ]
    return subprocess.run(command).returncode


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

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    options = {
        "sourceName": args.source_name,
        "device": args.device,
        "minimumIos": args.minimum_ios,
        "bundleId": args.bundle_id,
        "displayName": args.display_name,
    }

    with tempfile.TemporaryDirectory(prefix="debtoipa-full-auto-") as temporary:
        workspace = Path(temporary).resolve()
        baseline_output = workspace / "baseline"
        baseline_output.mkdir()
        baseline_code = _run_baseline(args, baseline_output)
        baseline_summary = _load_json(baseline_output / "runner-summary.json", {})

        if baseline_code == 0 and baseline_summary.get("resultKind") == "real-ipa":
            _copy_tree_contents(baseline_output, output, skip=set())
            print("::notice title=DebToIPA::Original binary is compatible; source rebuild was not needed.")
            return 0

        payload_root = (workspace / "payload").resolve()
        try:
            baseline.extract_deb_payload(args.deb, payload_root)
            source_result = build_source_port(payload_root, output, args.source_name, options)
        except SourcePortError as error:
            source_result = None
            source_error = str(error)
        except Exception as error:
            source_result = None
            source_error = f"Source-assisted conversion failed unexpectedly: {error}"
        else:
            source_error = ""

        if source_result is None:
            _copy_tree_contents(baseline_output, output, skip=set())
            if source_error:
                source_report = {
                    "schemaVersion": 1,
                    "resultKind": "source-port-blocked",
                    "error": source_error,
                    "compileVerified": False,
                }
                (output / "source-port-report.json").write_text(
                    json.dumps(source_report, indent=2), encoding="utf-8"
                )
                summary_path = output / "runner-summary.json"
                summary = _load_json(summary_path, baseline_summary)
                summary["sourcePortAttempted"] = True
                summary["sourcePortBuilt"] = False
                summary["sourcePortError"] = source_error
                summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
                print(f"::warning title=Source rebuild unavailable::{source_error}")
            else:
                print("::notice title=Source rebuild unavailable::The DEB contains no DebToIPA source-port manifest or recognized source tree.")
            return baseline_code if baseline_code in {2, 3} else 2

        ipa: Path = source_result["ipa"]
        source_report: dict[str, Any] = source_result["report"]
        validation = baseline.validate_ipa_bytes(ipa.read_bytes())
        baseline_report = _load_json(baseline_output / "conversion-report.json", {})
        original_blockers = list(baseline_report.get("blockers") or baseline_summary.get("blockers") or [])
        warnings = list(baseline_report.get("warnings") or [])
        warnings.insert(
            0,
            "This IPA was rebuilt from source included in the DEB. Compilation and IPA structure are verified, but exact feature parity still requires real-device testing.",
        )
        report: dict[str, Any] = {
            **baseline_report,
            "schemaVersion": max(int(baseline_report.get("schemaVersion") or 0), 3),
            "verdict": "source-ported",
            "resultKind": "source-ported",
            "blockers": [],
            "originalPackageBlockers": original_blockers,
            "warnings": warnings,
            "sourcePort": source_report,
            "output": {
                "featureComplete": None,
                "behavioralParityVerified": False,
                "stockIOSCompileVerified": True,
                "sourceDerived": True,
                "originalBinaryPackaged": False,
                "originalBinaryExecuted": False,
                "compatibilityHostGenerated": False,
                "ipaNames": [ipa.name],
                "validation": validation,
            },
        }
        summary: dict[str, Any] = {
            "schemaVersion": 4,
            "jobId": args.job_id,
            "sourceName": args.source_name,
            "runner": "github-macos",
            "verdict": "source-ported",
            "resultKind": "source-ported",
            "stage": "source-rebuild-complete",
            "ipas": [{"name": ipa.name, "size": ipa.stat().st_size, "kind": "source-rebuilt-app", "validation": validation}],
            "compatibilityHostGenerated": False,
            "originalBinaryPackaged": False,
            "originalBinaryExecuted": False,
            "stockIOSCompileVerified": True,
            "behavioralParityVerified": False,
            "featureComplete": None,
            "sourcePortAttempted": True,
            "sourcePortBuilt": True,
            "originalPackageBlockers": original_blockers,
            "warnings": warnings,
        }
        skip = {
            f"DebToIPA-{args.job_id}.zip",
            "conversion-report.json",
            "runner-summary.json",
            "README.txt",
            "source-port-report.json",
        }
        _copy_tree_contents(
            baseline_output,
            output,
            skip=skip,
            skip_ipas=True,
        )
        conversion_path = output / "conversion-report.json"
        summary_path = output / "runner-summary.json"
        source_report_path = output / "source-port-report.json"
        conversion_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        source_report_path.write_text(json.dumps(source_report, indent=2), encoding="utf-8")
        readme = "\n".join([
            "DebToIPA source-assisted stock-iOS rebuild",
            f"Source: {args.source_name}",
            "Result: source-ported",
            f"IPA: {ipa.name}",
            "Stock-iOS compile verified: True",
            "Original jailbreak binary packaged: False",
            "Generated compatibility host: False",
            "Behavioral parity verified: False — install and test on a real device.",
            "",
        ])
        (output / "README.txt").write_text(readme, encoding="utf-8")
        final_archive = output / f"DebToIPA-{args.job_id}.zip"
        _write_final_archive(
            baseline_output / f"DebToIPA-{args.job_id}.zip",
            final_archive,
            ipa,
            report,
            summary,
            source_report_path,
        )
        print(json.dumps(summary, indent=2))
        print("::notice title=Source-assisted port built::The stock-iOS IPA was compiled from source included in the DEB; no compatibility shell was generated.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
