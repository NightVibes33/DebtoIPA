#!/usr/bin/env python3
"""Build a searchable, policy-aware snapshot of public iOS APT repositories."""

from __future__ import annotations

import argparse
import bz2
import concurrent.futures
import datetime as dt
import gzip
import hashlib
import json
import lzma
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable

USER_AGENT = "DebToIPA-Library/1.0 (+https://github.com/NightVibes33/DebtoIPA)"
MAX_COMPRESSED = 48 * 1024 * 1024
MAX_DECOMPRESSED = 192 * 1024 * 1024
REQUEST_TIMEOUT = 24
PACKAGE_LIMIT_PER_SOURCE = 25000

COMMERCIAL_TAGS = {"cydia::commercial", "commercial", "paid"}
PIRACY_RE = re.compile(
    r"\b(crack(?:ed|tool)?|pirat(?:e|ed)|drm\s*bypass|license\s*bypass|iap\s*(?:crack|hack|bypass)|premium\s*unlocked|vip\s*unlocked|paid\s*for\s*free)\b",
    re.IGNORECASE,
)
JAILBREAK_DEP_RE = re.compile(
    r"mobilesubstrate|substrate|substitute|ellekit|libhooker|rocketbootstrap|preferenceloader|applist|springboard",
    re.IGNORECASE,
)
OPEN_LICENSE_RE = re.compile(
    r"\b(MIT|BSD(?:-[23]-Clause)?|Apache(?:-2\.0)?|GPL(?:v?[23]|-[23]\.0)?|LGPL(?:v?[23]|-[23]\.0)?|MPL-2\.0|ISC|Unlicense|CC0|Public Domain)\b",
    re.IGNORECASE,
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/octet-stream,text/plain,*/*",
            "Accept-Encoding": "identity",
        },
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        length = response.headers.get("Content-Length")
        if length and int(length) > MAX_COMPRESSED:
            raise ValueError(f"index is too large: {length} bytes")
        data = response.read(MAX_COMPRESSED + 1)
        if len(data) > MAX_COMPRESSED:
            raise ValueError("index exceeded compressed size limit")
        return data


def decompress_index(url: str, data: bytes) -> bytes:
    lowered = url.lower()
    if data.startswith(b"\x1f\x8b") or lowered.endswith(".gz"):
        output = gzip.decompress(data)
    elif data.startswith(b"BZh") or lowered.endswith(".bz2"):
        output = bz2.decompress(data)
    elif data.startswith(b"\xfd7zXZ\x00") or lowered.endswith(".xz"):
        output = lzma.decompress(data)
    else:
        output = data
    if len(output) > MAX_DECOMPRESSED:
        raise ValueError("index exceeded decompressed size limit")
    return output


def decode_control(data: bytes) -> str:
    for encoding in ("utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def parse_control_stanzas(text: str) -> list[dict[str, str]]:
    stanzas: list[dict[str, str]] = []
    current: dict[str, str] = {}
    last_key: str | None = None
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not raw_line.strip():
            if current:
                stanzas.append(current)
                current = {}
                last_key = None
            continue
        if raw_line[:1].isspace() and last_key:
            current[last_key] = f"{current[last_key]}\n{raw_line[1:]}".strip()
            continue
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        key = key.strip()
        if not key:
            continue
        current[key] = value.strip()
        last_key = key
    if current:
        stanzas.append(current)
    return stanzas


def candidate_urls(source: dict[str, Any]) -> tuple[list[str], bool]:
    explicit = [str(item).strip() for item in source.get("indexUrls", []) if str(item).strip()]
    if explicit:
        return list(dict.fromkeys(explicit)), True
    base = str(source["baseUrl"]).rstrip("/") + "/"
    candidates = [
        urllib.parse.urljoin(base, name)
        for name in ("Packages.xz", "Packages.bz2", "Packages.gz", "Packages")
    ]
    for arch in ("iphoneos-arm64", "iphoneos-arm"):
        for name in ("Packages.xz", "Packages.bz2", "Packages.gz", "Packages"):
            candidates.append(urllib.parse.urljoin(base, f"dists/stable/main/binary-{arch}/{name}"))
    return list(dict.fromkeys(candidates)), False


def normalize_tags(raw: str) -> list[str]:
    values = re.split(r"[,\s]+", raw or "")
    return sorted({item.strip().lower() for item in values if item.strip()})


def package_title(stanza: dict[str, str]) -> str:
    return (
        stanza.get("Name")
        or stanza.get("Package-Name")
        or stanza.get("Package")
        or "Unnamed package"
    ).strip()


def first_line(value: str) -> str:
    lines = (value or "").splitlines()
    return lines[0].strip() if lines else ""


def package_download_url(source: dict[str, Any], stanza: dict[str, str]) -> str | None:
    filename = stanza.get("Filename", "").strip()
    if not filename:
        return None
    parsed = urllib.parse.urlparse(filename)
    if parsed.scheme:
        if parsed.scheme != "https":
            return None
        return filename
    return urllib.parse.urljoin(str(source["baseUrl"]).rstrip("/") + "/", filename.lstrip("/"))


def classify_package(source: dict[str, Any], stanza: dict[str, str]) -> dict[str, Any]:
    title = package_title(stanza)
    package_id = stanza.get("Package", "").strip()
    description = stanza.get("Description", "").strip()
    section = stanza.get("Section", "Other").strip() or "Other"
    architecture = stanza.get("Architecture", "unknown").strip() or "unknown"
    tags = normalize_tags(stanza.get("Tag", ""))
    dependency_text = " ".join(
        stanza.get(key, "")
        for key in ("Depends", "Pre-Depends", "Conflicts", "Provides", "Description", "Section")
    )
    combined = " ".join((title, package_id, description, dependency_text))
    commercial = bool(COMMERCIAL_TAGS.intersection(tags)) or any(
        stanza.get(key, "").strip() for key in ("Price", "Purchase-Link", "Payment-Provider")
    )
    piracy_flag = bool(PIRACY_RE.search(combined))
    jailbreak_dependency = bool(JAILBREAK_DEP_RE.search(dependency_text))
    section_lower = section.lower()
    if "theme" in section_lower:
        conversion = "asset-pack"
        score = 5
        reason = "Theme packages do not contain a standalone iOS app."
    elif any(word in section_lower for word in ("tweak", "addon", "extension")) or jailbreak_dependency:
        conversion = "jailbreak-dependent"
        score = 15
        reason = "Likely depends on injection, SpringBoard, or jailbreak frameworks."
    elif any(word in section_lower for word in ("library", "development", "system", "terminal", "commandline")):
        conversion = "library-or-tool"
        score = 25
        reason = "May be reusable through source rebuild or native-tool integration, not direct IPA wrapping."
    elif any(word in section_lower for word in ("application", "app", "utilities", "utility", "multimedia", "games")):
        conversion = "application-candidate"
        score = 65
        reason = "Application-style package; full package analysis can determine direct, shim, or source conversion."
    else:
        conversion = "needs-analysis"
        score = 45
        reason = "Package metadata alone is insufficient; DebToIPA will run the full capability graph."

    if architecture not in {"iphoneos-arm", "iphoneos-arm64", "all", "darwin-arm", "darwin-arm64"}:
        score = min(score, 20)
        reason = f"Architecture {architecture} may not contain an iOS device executable."
    if piracy_flag:
        score = 0
        reason = "Blocked from direct loading because package metadata suggests a crack or purchase bypass."
    elif commercial:
        score = min(score, 10)
        reason = "Purchase or repository authentication is required; DebToIPA will not bypass it."

    download_url = package_download_url(source, stanza)
    source_policy = str(source.get("policy", "catalog-only"))
    if piracy_flag:
        download_policy = "blocked"
    elif commercial:
        download_policy = "purchase-required"
    elif source_policy != "direct":
        download_policy = "source-only"
    elif download_url:
        download_policy = "direct"
    else:
        download_policy = "metadata-only"

    license_text = " ".join(
        stanza.get(key, "") for key in ("License", "Homepage", "Description")
    )
    bundle_eligible = (
        source.get("mirrorPolicy") == "license-only"
        and bool(OPEN_LICENSE_RE.search(license_text))
        and download_policy == "direct"
    )
    flags: list[str] = []
    if commercial:
        flags.append("commercial")
    if piracy_flag:
        flags.append("suspected-piracy")
    if jailbreak_dependency:
        flags.append("jailbreak-framework")
    if "rootless" in combined.lower():
        flags.append("rootless")

    return {
        "title": title,
        "package": package_id,
        "version": stanza.get("Version", "unknown").strip() or "unknown",
        "description": first_line(description),
        "author": first_line(stanza.get("Author") or stanza.get("Maintainer") or "Unknown"),
        "section": section,
        "architecture": architecture,
        "tags": tags,
        "depends": first_line(stanza.get("Depends", "")),
        "homepage": stanza.get("Homepage", "").strip(),
        "depiction": stanza.get("SileoDepiction", stanza.get("Depiction", "")).strip(),
        "icon": stanza.get("Icon", "").strip(),
        "filename": stanza.get("Filename", "").strip(),
        "size": int(stanza.get("Size", "0")) if stanza.get("Size", "").isdigit() else 0,
        "sha256": stanza.get("SHA256", "").strip().lower(),
        "downloadUrl": download_url if download_policy == "direct" else None,
        "downloadPolicy": download_policy,
        "bundleEligible": bundle_eligible,
        "commercial": commercial,
        "riskFlags": flags,
        "conversion": {
            "class": conversion,
            "score": score,
            "reason": reason,
        },
    }


def source_result(source: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    urls, explicit = candidate_urls(source)
    errors: list[str] = []
    packages: list[dict[str, Any]] = []
    successful_urls: list[str] = []
    for url in urls:
        try:
            raw = fetch_bytes(url)
            stanzas = parse_control_stanzas(decode_control(decompress_index(url, raw)))
            if not stanzas:
                raise ValueError("no package stanzas")
            successful_urls.append(url)
            for stanza in stanzas[:PACKAGE_LIMIT_PER_SOURCE]:
                if not stanza.get("Package") or not stanza.get("Version"):
                    continue
                item = classify_package(source, stanza)
                item["sourceId"] = source["id"]
                item["sourceName"] = source["name"]
                item["sourceHomepage"] = source["homepage"]
                item["sourcePolicy"] = source.get("policy", "catalog-only")
                raw_id = "\0".join(
                    (str(source["id"]), item["package"], item["version"], item["architecture"])
                )
                item["id"] = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:24]
                packages.append(item)
            if not explicit:
                break
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError) as exc:
            errors.append(f"{url}: {exc}")
    deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in packages:
        key = (item["package"], item["version"], item["architecture"])
        deduped[key] = item
    ordered = sorted(
        deduped.values(),
        key=lambda item: (str(item["title"]).lower(), str(item["version"]), str(item["architecture"])),
    )
    summary = {
        "id": source["id"],
        "name": source["name"],
        "homepage": source["homepage"],
        "baseUrl": source["baseUrl"],
        "policy": source.get("policy", "catalog-only"),
        "mirrorPolicy": source.get("mirrorPolicy", "never"),
        "notes": source.get("notes", ""),
        "packageCount": len(ordered),
        "status": "ready" if ordered else "unavailable",
        "indexes": successful_urls,
        "errors": errors[-4:] if not ordered else [],
    }
    return summary, ordered


def build_snapshot(source_document: dict[str, Any], workers: int = 8) -> dict[str, Any]:
    sources = source_document.get("sources", [])
    if not isinstance(sources, list) or not sources:
        raise ValueError("source registry contains no sources")
    summaries: list[dict[str, Any]] = []
    packages: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(source_result, source): source for source in sources}
        for future in concurrent.futures.as_completed(futures):
            source = futures[future]
            try:
                summary, source_packages = future.result()
            except Exception as exc:  # noqa: BLE001 - preserve the rest of the library
                summary = {
                    "id": source.get("id", "unknown"),
                    "name": source.get("name", "Unknown"),
                    "homepage": source.get("homepage", ""),
                    "baseUrl": source.get("baseUrl", ""),
                    "policy": source.get("policy", "catalog-only"),
                    "mirrorPolicy": source.get("mirrorPolicy", "never"),
                    "notes": source.get("notes", ""),
                    "packageCount": 0,
                    "status": "error",
                    "indexes": [],
                    "errors": [str(exc)],
                }
                source_packages = []
            summaries.append(summary)
            packages.extend(source_packages)
            print(f"{summary['name']}: {summary['packageCount']} packages ({summary['status']})", file=sys.stderr)
    summaries.sort(key=lambda item: str(item["name"]).lower())
    packages.sort(
        key=lambda item: (
            -int(item["conversion"]["score"]),
            str(item["title"]).lower(),
            str(item["sourceName"]).lower(),
        )
    )
    direct_count = sum(item["downloadPolicy"] == "direct" for item in packages)
    blocked_count = sum(item["downloadPolicy"] == "blocked" for item in packages)
    bundle_count = sum(bool(item["bundleEligible"]) for item in packages)
    return {
        "schemaVersion": 1,
        "generatedAt": utc_now(),
        "packageCount": len(packages),
        "sourceCount": len(summaries),
        "readySourceCount": sum(item["status"] == "ready" for item in summaries),
        "directPackageCount": direct_count,
        "blockedPackageCount": blocked_count,
        "bundleEligibleCount": bundle_count,
        "notice": "CyPwn and mixed commercial repositories are cataloged, but cracks, paid packages, authenticated purchases, and unclear redistribution are not proxied or bundled.",
        "sources": summaries,
        "packages": packages,
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    os.replace(temporary, path)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", default="library/sources.json")
    parser.add_argument("--output", default="public/library/index.json")
    parser.add_argument("--stats", default="public/library/stats.json")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--minimum-packages", type=int, default=0)
    args = parser.parse_args(list(argv) if argv is not None else None)

    source_document = read_json(Path(args.sources))
    snapshot = build_snapshot(source_document, workers=args.workers)
    if snapshot["packageCount"] < args.minimum_packages:
        raise SystemExit(
            f"library snapshot has {snapshot['packageCount']} packages; expected at least {args.minimum_packages}"
        )
    write_json(Path(args.output), snapshot)
    write_json(
        Path(args.stats),
        {key: value for key, value in snapshot.items() if key not in {"packages"}},
    )
    print(
        f"wrote {snapshot['packageCount']} packages from {snapshot['readySourceCount']}/{snapshot['sourceCount']} sources",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
