#!/usr/bin/env python3
"""DebToIPA multi-profile conversion pipeline.

Order:
1. Analyze the package and create a capability graph.
2. Try the requested/recommended profile without executing package scripts.
3. Prefer a compatible original binary, then audited binary shims, then a
   package-provided source rebuild with normal iOS adapters/extensions.
4. Always publish an honest result and never substitute a generic viewer.
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

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from typing import Any

import runner_smart_auto as baseline
from adapter_sdk import write_adapter_sdk
from binary_shim import build_binary_shimmed_ipa
from capability_graph import CapabilityGraph, analyze_payload
from source_port import SourcePortError, build_source_port

GREEN_RESULTS = {"real-ipa", "binary-shimmed", "source-ported"}
VALID_PROFILES = {
    "automatic", "direct-ipa", "binary-shims", "source-rebuild", "app-extensions",
    "background-replacement", "companion-service", "report-only",
}
VALID_ALTERNATIVES = {
    "preferences-adapter", "settings-screen", "sandbox-path-adapter", "document-picker",
    "file-provider", "notification-adapter", "push-notifications", "background-task",
    "background-transfer", "companion-service", "widget-extension", "standalone-ui",
    "share-extension", "app-intents", "url-schemes", "safari-web-extension",
    "content-blocker", "network-extension", "local-proxy", "native-library",
    "public-api-redesign",
}


def _load_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else (default or {})
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default or {}


def _copy_tree_contents(source: Path, destination: Path, *, skip: set[str] | None = None, skip_ipas: bool = False) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    skip = skip or set()
    if not source.is_dir():
        return
    for path in source.iterdir():
        if path.name in skip or (skip_ipas and path.suffix.lower() == ".ipa"):
            continue
        target = destination / path.name
        if path.is_dir():
            shutil.copytree(path, target, dirs_exist_ok=True)
        else:
            shutil.copy2(path, target)


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


def _selected_alternatives(graph: CapabilityGraph, explicit: list[str], profile: str) -> list[str]:
    values = set(explicit)
    for capability in graph.capabilities:
        if capability.selected_alternative:
            values.add(capability.selected_alternative)
    if profile == "app-extensions":
        for value in ("widget-extension", "share-extension", "app-intents"):
            if any(value == option.id for cap in graph.capabilities for option in cap.alternatives):
                values.add(value)
    elif profile == "background-replacement":
        values.update({"background-task", "background-transfer"})
    elif profile == "companion-service":
        values.add("companion-service")
    return sorted(values & VALID_ALTERNATIVES)


def _plan_profile(graph: CapabilityGraph, requested: str) -> str:
    if requested != "automatic":
        return requested
    return graph.recommendedProfile


def _write_capability_outputs(output: Path, graph: CapabilityGraph, selected_profile: str, alternatives: list[str]) -> None:
    plan = graph.to_dict()
    plan["selectedProfile"] = selected_profile
    plan["selectedAlternatives"] = alternatives
    (output / "capability-plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    lines = [
        "# DebToIPA capability plan",
        "",
        f"- Recommended profile: **{graph.recommendedProfile}**",
        f"- Selected profile: **{selected_profile}**",
        f"- Expected retained functionality: **{graph.expectedRetainedFunctionality}%**",
        f"- Standalone app: **{graph.facts.get('hasStandaloneApp', False)}**",
        f"- Package source: **{graph.facts.get('hasSource', False)}**",
        "",
        "## Detected capabilities",
    ]
    if not graph.capabilities:
        lines.append("- No jailbreak-only capability markers were detected.")
    for capability in graph.capabilities:
        lines.append(f"- **{capability.title}** — {capability.severity}; replacement: `{capability.selected_alternative or 'none'}`")
    if graph.hardBlockers:
        lines.extend(["", "## Hard blockers", *[f"- {item}" for item in graph.hardBlockers]])
    if alternatives:
        lines.extend(["", "## Selected alternatives", *[f"- `{item}`" for item in alternatives]])
    (output / "CAPABILITY_PLAN.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _validate_ipa(path: Path) -> dict[str, Any]:
    return baseline.validate_ipa_bytes(path.read_bytes())


def _final_summary(
    args: argparse.Namespace,
    *,
    result_kind: str,
    profile: str,
    ipa: Path | None,
    validation: dict[str, Any] | None,
    graph: CapabilityGraph,
    alternatives: list[str],
    report: dict[str, Any],
    warnings: list[str],
    original_binary: bool,
    compile_verified: bool,
    behavioral_parity: bool,
) -> dict[str, Any]:
    return {
        "schemaVersion": 5,
        "jobId": args.job_id,
        "sourceName": args.source_name,
        "runner": "github-macos",
        "verdict": result_kind,
        "resultKind": result_kind,
        "conversionProfile": profile,
        "recommendedProfile": graph.recommendedProfile,
        "selectedAlternatives": alternatives,
        "expectedRetainedFunctionality": graph.expectedRetainedFunctionality,
        "stage": "complete" if result_kind in GREEN_RESULTS else "blocked",
        "ipas": [] if ipa is None else [{
            "name": ipa.name,
            "size": ipa.stat().st_size,
            "kind": result_kind,
            "validation": validation,
        }],
        "capabilityCount": len(graph.capabilities),
        "hardBlockers": graph.hardBlockers,
        "compatibilityHostGenerated": False,
        "originalBinaryPackaged": original_binary,
        "originalBinaryExecuted": False,
        "stockIOSCompileVerified": compile_verified,
        "behavioralParityVerified": behavioral_parity,
        "featureComplete": True if result_kind == "real-ipa" else None if result_kind in {"binary-shimmed", "source-ported"} else False,
        "warnings": warnings,
        "report": report,
    }


def _write_result_files(output: Path, summary: dict[str, Any], report: dict[str, Any]) -> None:
    (output / "runner-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (output / "conversion-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [
        "DebToIPA full conversion result",
        f"Result: {summary.get('resultKind')}",
        f"Profile: {summary.get('conversionProfile')}",
        f"Recommended profile: {summary.get('recommendedProfile')}",
        f"Expected retained functionality: {summary.get('expectedRetainedFunctionality')}%",
        f"Original binary packaged: {summary.get('originalBinaryPackaged')}",
        f"Stock-iOS compile verified: {summary.get('stockIOSCompileVerified')}",
        f"Behavioral parity verified: {summary.get('behavioralParityVerified')}",
        "Generated compatibility host: False",
        "",
    ]
    if summary.get("selectedAlternatives"):
        lines.extend(["Selected alternatives:", *[f"- {item}" for item in summary["selectedAlternatives"]], ""])
    if summary.get("warnings"):
        lines.extend(["Warnings:", *[f"- {item}" for item in summary["warnings"]], ""])
    if summary.get("hardBlockers"):
        lines.extend(["Hard blockers:", *[f"- {item}" for item in summary["hardBlockers"]], ""])
    (output / "README.txt").write_text("\n".join(lines), encoding="utf-8")


def _merge_archive(output: Path, job_id: str, ipa: Path | None) -> None:
    archive_path = output / f"DebToIPA-{job_id}.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(output.rglob("*")):
            if not path.is_file() or path == archive_path:
                continue
            relative = path.relative_to(output).as_posix()
            archive.write(path, relative, compress_type=zipfile.ZIP_STORED if path.suffix.lower() == ".ipa" else zipfile.ZIP_DEFLATED)


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
    parser.add_argument("--profile", choices=sorted(VALID_PROFILES), default="automatic")
    parser.add_argument("--alternative", action="append", default=[])
    args = parser.parse_args()

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if not args.deb.is_file():
        (output / "runner-summary.json").write_text(json.dumps({"resultKind": "unsupported", "error": "Input DEB is missing."}, indent=2), encoding="utf-8")
        return 2

    with tempfile.TemporaryDirectory(prefix="debtoipa-full-auto-") as temporary:
        workspace = Path(temporary)
        payload_root = (workspace / "payload").resolve()
        baseline_output = workspace / "baseline"
        baseline_output.mkdir()
        try:
            baseline.extract_deb_payload(args.deb, payload_root)
        except Exception as error:
            summary = {"schemaVersion": 5, "jobId": args.job_id, "resultKind": "unsupported", "error": f"Could not safely extract the Debian payload: {error}", "compatibilityHostGenerated": False}
            _write_result_files(output, summary, summary)
            _merge_archive(output, args.job_id, None)
            return 2

        graph = analyze_payload(payload_root, requested_profile=args.profile, requested_alternatives=args.alternative)
        profile = _plan_profile(graph, args.profile)
        alternatives = _selected_alternatives(graph, args.alternative, profile)
        _write_capability_outputs(output, graph, profile, alternatives)

        # Always generate the selected adapter/extension/service project so a blocked
        # conversion still returns a concrete package-specific starting point.
        generated_project = output / "GeneratedPortProject"
        write_adapter_sdk(
            generated_project,
            bundle_id=args.bundle_id or "app.debtoipa.converted",
            app_name=args.display_name or Path(args.source_name).stem,
            alternatives=alternatives,
        )

        baseline_code = _run_baseline(args, baseline_output)
        baseline_summary = _load_json(baseline_output / "runner-summary.json")
        baseline_report = _load_json(baseline_output / "conversion-report.json")

        if profile in {"automatic", "direct-ipa"} and baseline_code == 0 and baseline_summary.get("resultKind") == "real-ipa":
            _copy_tree_contents(baseline_output, output, skip={f"DebToIPA-{args.job_id}.zip", "runner-summary.json", "conversion-report.json", "README.txt"})
            ipa_names = [item.get("name") for item in baseline_summary.get("ipas") or [] if isinstance(item, dict)]
            ipa = next((output / name for name in ipa_names if name and (output / name).is_file()), None)
            if ipa is None:
                nested_archive = baseline_output / f"DebToIPA-{args.job_id}.zip"
                if nested_archive.is_file():
                    with zipfile.ZipFile(nested_archive) as archive:
                        ipa_entry = next((name for name in archive.namelist() if "/" not in name and name.lower().endswith(".ipa")), None)
                        if ipa_entry:
                            ipa = output / Path(ipa_entry).name
                            ipa.write_bytes(archive.read(ipa_entry))
            validation = _validate_ipa(ipa) if ipa else None
            warnings = list(baseline_summary.get("warnings") or []) + graph.warnings
            report = {**baseline_report, "resultKind": "real-ipa", "conversionProfile": "direct-ipa", "capabilityGraph": graph.to_dict(), "selectedAlternatives": alternatives}
            summary = _final_summary(args, result_kind="real-ipa", profile="direct-ipa", ipa=ipa, validation=validation, graph=graph, alternatives=alternatives, report=report, warnings=warnings, original_binary=True, compile_verified=False, behavioral_parity=False)
            _write_result_files(output, summary, report)
            _merge_archive(output, args.job_id, ipa)
            print(json.dumps(summary, indent=2))
            return 0

        if profile in {"automatic", "binary-shims"}:
            try:
                binary_result = build_binary_shimmed_ipa(
                    payload_root,
                    output,
                    source_name=args.source_name,
                    minimum_ios=args.minimum_ios,
                    bundle_id=args.bundle_id,
                    display_name=args.display_name,
                    device=args.device,
                )
            except Exception as error:
                binary_error = str(error)
            else:
                ipa: Path = binary_result["ipa"]
                validation = _validate_ipa(ipa)
                warnings = [
                    "The original executable was retained and known support-library dependencies were redirected to audited adapters.",
                    "A signed real-device launch and feature test is still required; binary shims cannot recreate private privileges.",
                    *graph.warnings,
                ]
                report = {
                    "schemaVersion": 5,
                    "resultKind": "binary-shimmed",
                    "conversionProfile": "binary-shims",
                    "capabilityGraph": graph.to_dict(),
                    "selectedAlternatives": alternatives,
                    "binaryShim": binary_result["report"],
                    "output": {"ipaNames": [ipa.name], "originalBinaryPackaged": True, "compatibilityHostGenerated": False, "validation": validation},
                }
                summary = _final_summary(args, result_kind="binary-shimmed", profile="binary-shims", ipa=ipa, validation=validation, graph=graph, alternatives=alternatives, report=report, warnings=warnings, original_binary=True, compile_verified=False, behavioral_parity=False)
                _write_result_files(output, summary, report)
                _merge_archive(output, args.job_id, ipa)
                print(json.dumps(summary, indent=2))
                return 0
        else:
            binary_error = "Binary-shim profile was not selected."

        source_profiles = {"automatic", "source-rebuild", "app-extensions", "background-replacement", "companion-service"}
        if profile in source_profiles:
            options = {
                "sourceName": args.source_name,
                "device": args.device,
                "minimumIos": args.minimum_ios,
                "bundleId": args.bundle_id,
                "displayName": args.display_name,
                "requestedAlternatives": alternatives,
            }
            try:
                source_result = build_source_port(payload_root, output, args.source_name, options)
            except SourcePortError as error:
                source_error = str(error)
                source_result = None
            except Exception as error:
                source_error = f"Source-assisted conversion failed unexpectedly: {error}"
                source_result = None
            else:
                source_error = "No supported package-provided source tree was found." if source_result is None else ""
            if source_result is not None:
                ipa: Path = source_result["ipa"]
                validation = _validate_ipa(ipa)
                source_report = source_result["report"]
                warnings = [
                    "This IPA was rebuilt from package-provided source using public iOS frameworks and generated alternatives.",
                    "Compilation and IPA validation do not prove exact feature parity; install and test the signed IPA on a real device.",
                    *graph.warnings,
                ]
                report = {
                    "schemaVersion": 5,
                    "resultKind": "source-ported",
                    "conversionProfile": profile if profile != "automatic" else graph.recommendedProfile,
                    "capabilityGraph": graph.to_dict(),
                    "selectedAlternatives": alternatives,
                    "sourcePort": source_report,
                    "originalPackageBlockers": list(baseline_report.get("blockers") or baseline_summary.get("blockers") or []),
                    "output": {"ipaNames": [ipa.name], "sourceDerived": True, "stockIOSCompileVerified": True, "behavioralParityVerified": False, "compatibilityHostGenerated": False, "validation": validation},
                }
                summary = _final_summary(args, result_kind="source-ported", profile=report["conversionProfile"], ipa=ipa, validation=validation, graph=graph, alternatives=alternatives, report=report, warnings=warnings, original_binary=False, compile_verified=True, behavioral_parity=False)
                _write_result_files(output, summary, report)
                _merge_archive(output, args.job_id, ipa)
                print(json.dumps(summary, indent=2))
                return 0
        else:
            source_error = "Source-rebuild profiles were not selected."

        _copy_tree_contents(
            baseline_output,
            output,
            skip={f"DebToIPA-{args.job_id}.zip", "runner-summary.json", "conversion-report.json", "README.txt"},
            skip_ipas=profile == "report-only",
        )
        result_kind = "original-blocked" if baseline_summary.get("resultKind") == "original-blocked" and profile != "report-only" else "unsupported"
        warnings = list(baseline_summary.get("warnings") or []) + graph.warnings
        warnings.extend([f"Binary-shim path: {binary_error}", f"Source-rebuild path: {source_error}"])
        report = {
            **baseline_report,
            "schemaVersion": 5,
            "resultKind": result_kind,
            "conversionProfile": profile,
            "capabilityGraph": graph.to_dict(),
            "selectedAlternatives": alternatives,
            "binaryShimError": binary_error,
            "sourcePortError": source_error,
            "output": {"featureComplete": False, "compatibilityHostGenerated": False, "ipaNames": [item.get("name") for item in baseline_summary.get("ipas") or [] if isinstance(item, dict)]},
        }
        summary = _final_summary(args, result_kind=result_kind, profile=profile, ipa=None, validation=None, graph=graph, alternatives=alternatives, report=report, warnings=warnings, original_binary=result_kind == "original-blocked", compile_verified=False, behavioral_parity=False)
        _write_result_files(output, summary, report)
        _merge_archive(output, args.job_id, None)
        print(json.dumps(summary, indent=2))
        return 3 if result_kind == "original-blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
