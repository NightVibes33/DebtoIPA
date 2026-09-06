#!/usr/bin/env python3
import hashlib
import json
import re
from collections import Counter

SRC = "source.json"
OUT = "sidestore-source.json"
OUT_URL = "https://raw.githubusercontent.com/NightVibes33/DebtoIPA/flekstore-alt-source/sidestore-source.json"
INT32_MAX = 2_147_483_647


def safe_version(value):
    s = str(value or "").strip()
    m = re.match(r"^(\d+(?:\.\d+)*)", s)
    return m.group(1) if m else "1.0"


def safe_date(value):
    s = str(value or "")
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", s)
    return m.group(1) if m else "2026-01-01"


def clean_text(value, n):
    s = str(value or "")
    s = re.sub(r"[\x00-\x1f\x7f]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:n]


def safe_size(value):
    try:
        n = int(float(value or 0))
    except Exception:
        n = 0
    return min(max(0, n), INT32_MAX)


def make_source(apps, name, identifier, source_url=None):
    out = {"name": name, "identifier": identifier, "apps": apps}
    if source_url:
        out["sourceURL"] = source_url
    return out


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
        if not download.startswith("https://"):
            continue

        source_bundle = str(a.get("bundleIdentifier") or "").strip()
        bundle = source_bundle
        if not source_bundle or bundle_counts.get(source_bundle, 0) > 1:
            seed = (source_bundle + "\0" + str(a.get("name")) + "\0" + download).encode("utf-8")
            bundle = f"com.nightvibes33.flekvariant.{hashlib.sha1(seed).hexdigest()[:12]}"

        version_string = safe_version(v.get("version") or a.get("version"))
        date_string = safe_date(v.get("date") or a.get("versionDate"))
        size = safe_size(v.get("size") or a.get("size"))
        description = clean_text(a.get("localizedDescription") or a.get("subtitle") or "FlekSt0re catalog app", 300)
        subtitle = clean_text(a.get("subtitle") or description, 100)
        name = clean_text(a.get("name") or "FlekSt0re App", 120)
        developer = clean_text(a.get("developerName") or "FlekSt0re", 80)
        icon = str(a.get("iconURL") or "https://flekstore.com/favicon.ico").strip()
        if not icon.startswith("https://"):
            icon = "https://flekstore.com/favicon.ico"

        version = {
            "version": version_string,
            "date": date_string,
            "downloadURL": download,
            "size": size,
        }

        apps.append({
            "name": name,
            "bundleIdentifier": bundle,
            "developerName": developer,
            "subtitle": subtitle,
            "localizedDescription": description,
            "iconURL": icon,
            "version": version_string,
            "versionDate": date_string,
            "versionDescription": description[:250],
            "downloadURL": download,
            "size": size,
            "versions": [version],
        })

    ids = [a["bundleIdentifier"] for a in apps]
    assert len(ids) == len(set(ids)), "duplicate SideStore listing identifiers remain"
    assert len(apps) == len(raw_apps), f"catalog lost apps: {len(apps)} != {len(raw_apps)}"

    full = make_source(
        apps,
        "FlekSt0re Lib Mirror (SideStore v7)",
        "com.nightvibes33.flekstorelib.sidestore.v7",
        OUT_URL,
    )
    full["news"] = []
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(full, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")

    # Full catalog, deliberately minimal. This keeps all apps while removing
    # almost all optional strings/legacy metadata that SideStore would persist.
    lean_apps = []
    for a in apps:
        v = a["versions"][0]
        lean_apps.append({
            "name": a["name"],
            "bundleIdentifier": a["bundleIdentifier"],
            "developerName": a["developerName"],
            "localizedDescription": "FlekSt0re catalog app",
            "iconURL": a["iconURL"],
            # Retain top-level downloadURL for older SideStore compatibility.
            "downloadURL": a["downloadURL"],
            "versions": [{
                "version": v["version"],
                "date": v["date"],
                "downloadURL": v["downloadURL"],
                "size": v["size"],
            }],
        })
    lean_path = "sidestore-lean.json"
    lean_url = f"https://raw.githubusercontent.com/NightVibes33/DebtoIPA/flekstore-alt-source/{lean_path}"
    lean = make_source(
        lean_apps,
        "FlekSt0re Lib Mirror (SideStore Lean)",
        "com.nightvibes33.flekstorelib.sidestore.lean.v8",
        lean_url,
    )
    with open(lean_path, "w", encoding="utf-8") as f:
        json.dump(lean, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")

    for count in (1, 25, 100):
        path = f"sidestore-smoke-{count}.json"
        url = f"https://raw.githubusercontent.com/NightVibes33/DebtoIPA/flekstore-alt-source/{path}"
        smoke = make_source(
            lean_apps[:count],
            f"FlekSt0re SideStore Smoke {count}",
            f"com.nightvibes33.flekstorelib.smoke.{count}.v8",
            url,
        )
        with open(path, "w", encoding="utf-8") as f:
            json.dump(smoke, f, ensure_ascii=False, separators=(",", ":"))
            f.write("\n")

    print(
        "WROTE", OUT,
        "APPS", len(apps),
        "LEAN_APPS", len(lean_apps),
        "UNIQUE_IDS", len(set(ids)),
        "INT32_SIZE_CLAMP", INT32_MAX,
    )


if __name__ == "__main__":
    main()
