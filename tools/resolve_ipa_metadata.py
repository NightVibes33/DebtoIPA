#!/usr/bin/env python3
import json
import os
import plistlib
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from remotezip import RemoteZip

SOURCE = os.environ.get("SOURCE", "source.json")
CACHE = os.environ.get("CACHE", "ipa-metadata-cache.json")
WORKERS = int(os.environ.get("WORKERS", "16"))


def load_cache():
    try:
        with open(CACHE, "r", encoding="utf-8") as f:
            obj = json.load(f)
            return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _main_info_plist(names):
    """Find the main .app Info.plist even in oddly wrapped/repacked IPAs."""
    normalized = [(n, n.replace("\\", "/")) for n in names]

    # Normal IPA, or an IPA wrapped in one or more leading directories.
    preferred = [
        (original, norm)
        for original, norm in normalized
        if re.search(r"(?:^|/)Payload/[^/]+\.app/Info\.plist$", norm, flags=re.I)
    ]
    if preferred:
        preferred.sort(key=lambda item: (item[1].count("/"), len(item[1]), item[1].casefold()))
        return preferred[0][0]

    # Some repacks omit Payload entirely. Accept only a direct .app Info.plist,
    # never extension/watch/app-clip/framework plists.
    excluded = ("/plugins/", "/watch/", "/appclips/", "/frameworks/", "/extensions/")
    fallback = []
    for original, norm in normalized:
        low = "/" + norm.lower().lstrip("/")
        if not re.search(r"(?:^|/)[^/]+\.app/Info\.plist$", norm, flags=re.I):
            continue
        if any(part in low for part in excluded):
            continue
        fallback.append((original, norm))
    if fallback:
        fallback.sort(key=lambda item: (item[1].count("/"), len(item[1]), item[1].casefold()))
        return fallback[0][0]

    raise RuntimeError("main .app/Info.plist not found in IPA central directory")


def extract(url):
    # RemoteZip reads only ZIP directory + requested Info.plist ranges, rather
    # than downloading the entire IPA.
    with RemoteZip(url) as z:
        plist_path = _main_info_plist(z.namelist())
        raw = z.read(plist_path)
    p = plistlib.loads(raw)
    bundle = str(p.get("CFBundleIdentifier") or "").strip()
    if not bundle:
        raise RuntimeError("CFBundleIdentifier missing")
    return {
        "bundleIdentifier": bundle,
        "version": str(p.get("CFBundleShortVersionString") or p.get("CFBundleVersion") or "").strip(),
        "buildVersion": str(p.get("CFBundleVersion") or "").strip(),
        "minOSVersion": str(p.get("MinimumOSVersion") or "").strip(),
        "infoPlistPath": plist_path,
    }


def main():
    with open(SOURCE, "r", encoding="utf-8") as f:
        source = json.load(f)
    apps = source.get("apps", [])
    cache = load_cache()

    pending = {}
    for app in apps:
        url = app.get("downloadURL")
        if not url:
            continue
        cached = cache.get(url)
        if isinstance(cached, dict) and cached.get("bundleIdentifier"):
            continue
        pending[url] = app.get("name", url)

    print(f"IPA metadata: {len(cache)} cached, {len(pending)} to resolve", flush=True)
    resolved = 0
    failed = 0
    if pending:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(extract, url): (url, name) for url, name in pending.items()}
            for fut in as_completed(futures):
                url, name = futures[fut]
                try:
                    cache[url] = fut.result()
                    resolved += 1
                except Exception as exc:
                    cache[url] = {"error": str(exc)}
                    failed += 1
                    print(f"WARN metadata {name}: {exc}", flush=True)
                if (resolved + failed) % 25 == 0:
                    print(f"Resolved {resolved + failed}/{len(pending)} (ok={resolved}, bad={failed})", flush=True)

    # Apply verified metadata to the full LiveContainer-oriented source itself.
    updated = 0
    for app in apps:
        url = app.get("downloadURL")
        md = cache.get(url, {})
        if not md.get("bundleIdentifier"):
            continue
        app["bundleIdentifier"] = md["bundleIdentifier"]
        version = md.get("version")
        if version:
            if "version" in app:
                app["version"] = version
            for item in app.get("versions") or []:
                item["version"] = version
                if md.get("minOSVersion"):
                    item["minOSVersion"] = md["minOSVersion"]
        updated += 1

    with open(SOURCE, "w", encoding="utf-8") as f:
        json.dump(source, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")

    by_bundle = {}
    for app in apps:
        url = app.get("downloadURL")
        md = cache.get(url, {})
        bundle = md.get("bundleIdentifier")
        if bundle:
            by_bundle.setdefault(bundle, []).append(app.get("name"))
    dupes = {k: v for k, v in by_bundle.items() if k and len(v) > 1}
    print(f"Applied real IPA metadata to {updated}/{len(apps)} apps; unresolved={len(apps)-updated}")
    print(f"Duplicate real bundle identifiers: {len(dupes)}")
    for bundle, names in sorted(dupes.items())[:100]:
        print("DUP", bundle, "=>", " | ".join(names))


if __name__ == "__main__":
    main()
