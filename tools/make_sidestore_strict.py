#!/usr/bin/env python3
import json
import re
from collections import Counter
from datetime import datetime, timezone

SRC = "source.json"
CACHE = "ipa-metadata-cache.json"
OUT = "sidestore-strict.json"
LITE_OUT = "sidestore-strict-lite.json"
OUT_URL = "https://raw.githubusercontent.com/NightVibes33/DebtoIPA/flekstore-alt-source/sidestore-strict.json"
LITE_URL = "https://raw.githubusercontent.com/NightVibes33/DebtoIPA/flekstore-alt-source/sidestore-strict-lite.json"
BUNDLE_RE = re.compile(r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+$")


def numeric_version(value):
    s = str(value or "").strip()
    m = re.match(r"^(\d+(?:\.\d+)*)", s)
    return m.group(1) if m else "1.0"


def normalized_date(value):
    s = str(value or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", s):
        return s
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s + "T00:00:00Z"
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return "2026-01-01T00:00:00Z"


def clip(value, n):
    return str(value or "")[:n]


def make_app(a, md):
    versions = a.get("versions") or []
    first = versions[0]
    url = str(first.get("downloadURL") or a.get("downloadURL") or "").strip()
    bundle = str(md.get("bundleIdentifier") or "").strip()
    version = numeric_version(md.get("version") or first.get("version") or a.get("version"))
    size = first.get("size", a.get("size", 0))
    try:
        size = max(0, int(size or 0))
    except Exception:
        size = 0

    ver = {
        "version": version,
        "date": normalized_date(first.get("date") or a.get("versionDate")),
        "downloadURL": url,
        "size": size,
        "localizedDescription": clip(first.get("localizedDescription") or a.get("localizedDescription"), 180),
    }
    min_os = str(md.get("minOSVersion") or first.get("minOSVersion") or "").strip()
    if min_os:
        ver["minOSVersion"] = numeric_version(min_os)

    app = {
        "name": clip(a.get("name"), 120),
        "bundleIdentifier": bundle,
        "developerName": clip(a.get("developerName") or "FlekSt0re", 80),
        "localizedDescription": clip(a.get("localizedDescription") or "FlekSt0re catalog app", 420),
        "iconURL": str(a.get("iconURL") or "https://flekstore.com/favicon.ico"),
        "version": version,
        "downloadURL": url,
        "versions": [ver],
    }
    subtitle = clip(a.get("subtitle"), 90)
    if subtitle:
        app["subtitle"] = subtitle
    tint = str(a.get("tintColor") or "").lstrip("#")
    if re.fullmatch(r"[0-9A-Fa-f]{6}", tint):
        app["tintColor"] = tint
    return app


def source_doc(name, identifier, url, apps):
    return {
        "name": name,
        "identifier": identifier,
        "sourceURL": url,
        "apps": apps,
        "news": [],
    }


def main():
    with open(SRC, encoding="utf-8") as f:
        src = json.load(f)
    with open(CACHE, encoding="utf-8") as f:
        cache = json.load(f)

    verified = []
    rejected = []
    for a in src.get("apps", []):
        versions = a.get("versions") or []
        if not versions:
            rejected.append((a.get("name"), "no version"))
            continue
        url = str(versions[0].get("downloadURL") or a.get("downloadURL") or "").strip()
        md = cache.get(url, {}) if url else {}
        bundle = str(md.get("bundleIdentifier") or "").strip()
        if not url or not bundle or not BUNDLE_RE.fullmatch(bundle):
            rejected.append((a.get("name"), md.get("error") or "IPA identity not verified"))
            continue
        verified.append(make_app(a, md))

    # SideStore treats the embedded bundle ID as the app's durable identity.
    # Multiple tweaked variants with the same real ID cannot safely coexist as
    # separate apps unless their binary bundle IDs are actually changed too.
    counts = Counter(a["bundleIdentifier"] for a in verified)
    seen = set()
    strict = []
    duplicates = []
    for app in verified:
        bundle = app["bundleIdentifier"]
        if bundle in seen:
            duplicates.append((app["name"], bundle))
            continue
        seen.add(bundle)
        strict.append(app)

    strict.sort(key=lambda a: a["name"].casefold())
    lite = strict[:100]

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(source_doc(
            "FlekSt0re Lib Mirror (SideStore Strict)",
            "com.nightvibes33.flekstorelib.sidestore.strict.v1",
            OUT_URL,
            strict,
        ), f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")

    with open(LITE_OUT, "w", encoding="utf-8") as f:
        json.dump(source_doc(
            "FlekSt0re Lib Mirror (SideStore Strict Lite)",
            "com.nightvibes33.flekstorelib.sidestore.strictlite.v1",
            LITE_URL,
            lite,
        ), f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")

    duplicate_groups = sum(1 for n in counts.values() if n > 1)
    print(
        f"STRICT {len(strict)} apps; LITE {len(lite)}; "
        f"unverified={len(rejected)} duplicate-listings={len(duplicates)} "
        f"duplicate-groups={duplicate_groups}"
    )
    for name, reason in rejected[:100]:
        print("STRICT_DROP_UNVERIFIED", name, "=>", reason)
    for name, bundle in duplicates[:100]:
        print("STRICT_DROP_DUPLICATE", name, "=>", bundle)


if __name__ == "__main__":
    main()
