#!/usr/bin/env python3
import hashlib
import json
import re
from collections import Counter

SRC = "source.json"
OUT = "sidestore-source.json"
OUT_URL = "https://raw.githubusercontent.com/NightVibes33/DebtoIPA/flekstore-alt-source/sidestore-source.json"


def safe_version(value):
    s = str(value or "").strip()
    m = re.match(r"^(\d+(?:\.\d+)*)", s)
    return m.group(1) if m else "1.0"


def clip(value, n):
    return str(value or "")[:n]


def main():
    with open(SRC, encoding="utf-8") as f:
        src = json.load(f)

    raw_apps = src.get("apps", [])
    bundle_counts = Counter(str(a.get("bundleIdentifier") or "") for a in raw_apps)
    apps = []

    for a in raw_apps:
        versions = a.get("versions") or []
        if not versions:
            continue
        v = versions[0]
        download = str(v.get("downloadURL") or a.get("downloadURL") or "").strip()
        if not download:
            continue

        source_bundle = str(a.get("bundleIdentifier") or "").strip()
        bundle = source_bundle
        if not source_bundle or bundle_counts.get(source_bundle, 0) > 1:
            seed = (source_bundle + "\0" + str(a.get("name")) + "\0" + download).encode("utf-8")
            bundle = f"com.nightvibes33.flekvariant.{hashlib.sha1(seed).hexdigest()[:12]}"

        version = {
            "version": safe_version(v.get("version") or a.get("version")),
            "date": str(v.get("date") or "2026-01-01T00:00:00Z"),
            "downloadURL": download,
            "size": max(0, int(v.get("size") or a.get("size") or 0)),
        }

        apps.append({
            "name": clip(a.get("name"), 120),
            "bundleIdentifier": bundle,
            "developerName": clip(a.get("developerName") or "FlekSt0re", 80),
            "localizedDescription": clip(a.get("subtitle") or a.get("localizedDescription") or "FlekSt0re catalog app", 100),
            "iconURL": str(a.get("iconURL") or "https://flekstore.com/favicon.ico"),
            "downloadURL": download,
            "versions": [version],
        })

    ids = [a["bundleIdentifier"] for a in apps]
    assert len(ids) == len(set(ids)), "duplicate SideStore listing identifiers remain"
    assert len(apps) == len(raw_apps), f"catalog lost apps: {len(apps)} != {len(raw_apps)}"

    out = {
        "name": "FlekSt0re Lib Mirror (SideStore Minimal v6)",
        "identifier": "com.nightvibes33.flekstorelib.sidestore.v6",
        "sourceURL": OUT_URL,
        "apps": apps,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")

    print("WROTE", OUT, "APPS", len(apps), "UNIQUE_IDS", len(set(ids)))


if __name__ == "__main__":
    main()
