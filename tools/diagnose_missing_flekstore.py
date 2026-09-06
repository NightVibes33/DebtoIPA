#!/usr/bin/env python3
import json
import os
from urllib.parse import urlparse

import requests

API = "https://nestapi.flekstore.com/app/with-link"
DETAIL = "https://nestapi.flekstore.com/app/{app_id}"
OUT = os.environ.get("OUT", "missing-app-diagnostics.json")
TARGETS = {
    "FlekDeck",
    "Halo: Spartan Assault",
    "KillMyOTA",
    "Night of the Full Moon",
    "VCUS",
    "WDBFontOverwrite",
}
HEADERS = {"User-Agent": "FlekDeck-source-diagnostics/1.0", "Accept": "application/json,*/*"}


def get_json(url, params=None):
    r = requests.get(url, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def walk_urls(value, path="$"):
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            found.extend(walk_urls(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            found.extend(walk_urls(item, f"{path}[{i}]"))
    elif isinstance(value, str) and value.startswith(("http://", "https://")):
        found.append({"field": path, "url": value})
    return found


def probe(url):
    try:
        r = requests.head(url, allow_redirects=True, timeout=15, headers=HEADERS)
        # Some hosts reject HEAD; use a one-byte GET to distinguish that case.
        if r.status_code in (403, 405):
            r = requests.get(url, headers={**HEADERS, "Range": "bytes=0-0"}, allow_redirects=True, timeout=15, stream=True)
        return {
            "status": r.status_code,
            "finalURL": r.url,
            "contentLength": r.headers.get("Content-Length"),
            "contentType": r.headers.get("Content-Type"),
        }
    except Exception as exc:
        return {"error": str(exc)}


def related_candidates(url, name):
    """Very small, deterministic set of likely typo/case variants; not a bucket scan."""
    if not url:
        return []
    parsed = urlparse(url)
    path = parsed.path
    if not path.lower().endswith(".ipa"):
        return []
    prefix = path.rsplit("/", 1)[0]
    stem = path.rsplit("/", 1)[1][:-4]
    host = f"{parsed.scheme}://{parsed.netloc}"
    compact = "".join(ch for ch in name if ch.isalnum())
    stems = {stem, stem.lower(), compact, compact.lower()}
    if name == "FlekDeck":
        stems.update({"FlekDeck", "flekdeck", "FlekDeck1", "flekdeck1", "FlekDeck2", "flekdeck2", "FlekDeck3", "flekdeck3"})
    return sorted({f"{host}{prefix}/{s}.ipa" for s in stems})


def main():
    found = {}
    for page in range(101):
        data = get_json(API, {"page": page, "search": "false", "filter": "all"})
        rows = data.get("data", data) if isinstance(data, dict) else data
        if not isinstance(rows, list) or not rows:
            break
        for row in rows:
            name = str(row.get("app_name") or row.get("name") or "")
            if name in TARGETS:
                found[name] = row
        if TARGETS.issubset(found):
            break

    report = {"targets": {}}
    for name in sorted(TARGETS):
        summary = found.get(name)
        if not summary:
            report["targets"][name] = {"catalogRecordFound": False}
            continue
        app_id = summary.get("app_id", summary.get("id"))
        try:
            detail_raw = get_json(DETAIL.format(app_id=app_id))
            detail = detail_raw.get("data", detail_raw) if isinstance(detail_raw, dict) else detail_raw
        except Exception as exc:
            detail = {"diagnosticError": str(exc)}

        exposed = walk_urls({"summary": summary, "detail": detail})
        ipa_urls = []
        for item in exposed:
            if ".ipa" in item["url"].lower() and item["url"] not in ipa_urls:
                ipa_urls.append(item["url"])

        probes = {url: probe(url) for url in ipa_urls}
        related = {}
        for url in ipa_urls[:1]:
            for candidate in related_candidates(url, name):
                if candidate not in probes:
                    result = probe(candidate)
                    # Keep every probe for FlekDeck; for old catalog entries only
                    # retain successful alternates so the report stays compact.
                    if name == "FlekDeck" or result.get("status") in (200, 206):
                        related[candidate] = result

        report["targets"][name] = {
            "catalogRecordFound": True,
            "appID": app_id,
            "summary": summary,
            "detail": detail,
            "exposedURLs": exposed,
            "ipaProbes": probes,
            "relatedObjectProbes": related,
        }
        print(name, "app", app_id, "IPA URLs", len(ipa_urls), "related hits", sum(1 for x in related.values() if x.get("status") in (200, 206)))

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("WROTE", OUT)


if __name__ == "__main__":
    main()
