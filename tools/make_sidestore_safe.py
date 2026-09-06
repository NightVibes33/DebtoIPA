#!/usr/bin/env python3
import json
import re
from collections import Counter

SRC = "source.json"
CACHE = "ipa-metadata-cache.json"
OUT = "sidestore-source.json"
OUT_URL = "https://raw.githubusercontent.com/NightVibes33/DebtoIPA/flekstore-alt-source/sidestore-source.json"
BUNDLE_RE = re.compile(r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+$")


def safe_version(value):
    s = str(value or "").strip()
    m = re.match(r"^(\d+(?:\.\d+)*)", s)
    return m.group(1) if m else "1.0"


def clip(value, n):
    return str(value or "")[:n]


def main():
    with open(SRC, encoding="utf-8") as f:
        src = json.load(f)
    with open(CACHE, encoding="utf-8") as f:
        cache = json.load(f)

    candidates = []
    dropped_unverified = []
    for a in src.get("apps", []):
        source_versions = a.get("versions") or []
        if not source_versions:
            dropped_unverified.append((a.get("name"), "no versions"))
            continue

        first = source_versions[0]
        url = str(first.get("downloadURL") or a.get("downloadURL") or "").strip()
        md = cache.get(url) if url else None
        real_bundle = str((md or {}).get("bundleIdentifier") or "").strip()

        # SideStore uses bundleIdentifier as a durable app identity. Never feed it
        # a made-up catalog identifier: only include entries whose remote IPA was
        # actually opened and whose CFBundleIdentifier was read from Info.plist.
        if not url or not isinstance(md, dict) or not real_bundle or not BUNDLE_RE.fullmatch(real_bundle):
            reason = (md or {}).get("error") if isinstance(md, dict) else "metadata not resolved"
            dropped_unverified.append((a.get("name"), reason or "invalid bundle identifier"))
            continue

        version = safe_version(md.get("version") or first.get("version") or a.get("version"))
        min_os = str(md.get("minOSVersion") or first.get("minOSVersion") or "").strip()
        item = {
            "version": version,
            "date": str(first.get("date") or "2026-01-01T00:00:00Z"),
            "downloadURL": url,
            "size": max(0, int(first.get("size") or a.get("size") or 0)),
            "localizedDescription": clip(first.get("localizedDescription") or a.get("localizedDescription"), 180),
        }
        if min_os:
            item["minOSVersion"] = safe_version(min_os)

        app = {
            "name": clip(a.get("name"), 120),
            "bundleIdentifier": real_bundle,
            "developerName": clip(a.get("developerName") or "FlekSt0re", 80),
            "localizedDescription": clip(a.get("localizedDescription") or "FlekSt0re catalog app", 420),
            "iconURL": str(a.get("iconURL") or "https://flekstore.com/favicon.ico"),
            "versions": [item],
        }
        subtitle = clip(a.get("subtitle"), 90)
        if subtitle:
            app["subtitle"] = subtitle
        tint = a.get("tintColor")
        if isinstance(tint, str) and re.fullmatch(r"#?[0-9A-Fa-f]{6}", tint):
            app["tintColor"] = tint.lstrip("#")
        candidates.append(app)

    # SideStore/AltStore models key apps by bundle ID. FlekSt0re intentionally
    # has multiple tweaked variants with the same embedded bundle ID; representing
    # those as fake bundle IDs makes source metadata disagree with the IPA and can
    # poison SideStore's app/source state. Keep one deterministic listing per real ID.
    bundle_counts = Counter(a["bundleIdentifier"] for a in candidates)
    seen = set()
    apps = []
    dropped_duplicates = []
    for app in candidates:
        bundle = app["bundleIdentifier"]
        if bundle in seen:
            dropped_duplicates.append((app["name"], bundle))
            continue
        seen.add(bundle)
        apps.append(app)

    out = {
        "name": "FlekSt0re Lib Mirror (SideStore Verified)",
        "identifier": "com.nightvibes33.flekstorelib.sidestore.v5",
        "sourceURL": OUT_URL,
        "apps": apps,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")

    duplicate_groups = sum(1 for n in bundle_counts.values() if n > 1)
    print(
        "WROTE", OUT,
        "APPS", len(apps),
        "VERIFIED_CANDIDATES", len(candidates),
        "UNVERIFIED_DROPPED", len(dropped_unverified),
        "DUPLICATE_LISTINGS_DROPPED", len(dropped_duplicates),
        "DUPLICATE_GROUPS", duplicate_groups,
    )
    for name, reason in dropped_unverified[:100]:
        print("DROP_UNVERIFIED", name, "=>", reason)
    for name, bundle in dropped_duplicates[:100]:
        print("DROP_DUPLICATE", name, "=>", bundle)


if __name__ == "__main__":
    main()
