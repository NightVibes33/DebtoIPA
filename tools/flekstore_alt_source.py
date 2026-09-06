#!/usr/bin/env python3
import json
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests

BASE = "https://flekstore.com"
API_APPS = f"{BASE}/rest/apps/getApps/"
API_APP = f"{BASE}/rest/apps/getApp"
OUT = os.environ.get("OUT", "source.json")
PAGE_SIZE = 30

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 27_0 like Mac OS X) AppleWebKit/605.1.15 Version/27.0 Mobile/15E148 Safari/604.1",
    "Referer": f"{BASE}/pro_app/",
    "Accept": "application/json, text/plain, */*",
})


def get_json(url, params=None, retries=4):
    last = None
    for i in range(retries):
        try:
            r = session.get(url, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"GET failed: {url}: {last}")


def normalize_url(value):
    if not value:
        return None
    value = str(value).strip()
    if value.startswith("//"):
        return "https:" + value
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return urljoin(BASE + "/", value.lstrip("/"))


def pick(obj, *keys, default=None):
    for key in keys:
        value = obj.get(key)
        if value not in (None, "", False):
            return value
    return default


def clean_bundle(value, app_id):
    if value:
        value = str(value).strip()
        if re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+", value):
            return value
    # AltSource requires an identifier. This fallback is metadata only;
    # the IPA itself retains its embedded bundle identifier when installed.
    return f"com.flekstore.catalog.{app_id}"


def parse_size(value):
    if value is None:
        return 0
    try:
        return int(float(value))
    except Exception:
        pass
    s = str(value).strip().lower().replace(",", "")
    m = re.match(r"([0-9.]+)\s*(b|kb|kib|mb|mib|gb|gib)?", s)
    if not m:
        return 0
    n = float(m.group(1))
    unit = m.group(2) or "b"
    mult = {
        "b": 1,
        "kb": 1000,
        "kib": 1024,
        "mb": 1000**2,
        "mib": 1024**2,
        "gb": 1000**3,
        "gib": 1024**3,
    }[unit]
    return int(n * mult)


def iso_date(value):
    if not value:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    text = str(value).strip()
    # AltStore accepts ISO-8601. Preserve already-ISO values.
    if "T" in text and re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return text.replace("+00:00", "Z")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d.%m.%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            pass
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_catalog():
    apps = []
    page = 0
    seen = set()
    while True:
        data = get_json(API_APPS, {"page": page, "search": "false", "filter": "all"})
        rows = data.get("data", data) if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise RuntimeError(f"Unexpected getApps response on page {page}: {type(rows).__name__}")
        if not rows:
            break
        for row in rows:
            key = str(row.get("id", ""))
            if key and key not in seen:
                seen.add(key)
                apps.append(row)
        if len(rows) < PAGE_SIZE:
            break
        page += 1
        if page > 100:
            raise RuntimeError("Pagination safety stop")
    return apps


def fetch_detail(app_id):
    data = get_json(API_APP, {"id": app_id})
    return data.get("data", data) if isinstance(data, dict) else data


def to_alt_app(summary, detail):
    detail = detail if isinstance(detail, dict) else {}
    merged = dict(summary)
    merged.update({k: v for k, v in detail.items() if v not in (None, "")})

    app_id = str(pick(merged, "id", default="unknown"))
    name = str(pick(merged, "name", "title", default=f"FlekSt0re App {app_id}"))
    version = str(pick(merged, "version", "app_version", default="1.0"))
    bundle = clean_bundle(pick(merged, "bundle_id", "bundleIdentifier", "bundle_identifier", "bundleid", "package", "identifier"), app_id)
    download = normalize_url(pick(merged, "install_url", "download_url", "downloadURL", "ipa", "url"))
    icon = normalize_url(pick(merged, "icon", "icon_url", "iconURL"))
    description = str(pick(merged, "description", "full_description", "short_description", default="FlekSt0re catalog app"))
    subtitle = str(pick(merged, "short_description", "subtitle", default=description[:80]))
    developer = str(pick(merged, "developer", "developer_name", "author", default="FlekSt0re"))
    size = parse_size(pick(merged, "size", "file_size", "filesize", default=0))
    date = iso_date(pick(merged, "updated_at", "update_date", "date", "created_at"))

    if not download:
        return None

    version_obj = {
        "version": version,
        "date": date,
        "size": size,
        "downloadURL": download,
        "localizedDescription": description,
    }

    app = {
        "name": name,
        "bundleIdentifier": bundle,
        "developerName": developer,
        "subtitle": subtitle,
        "localizedDescription": description,
        "iconURL": icon or "https://flekstore.com/favicon.ico",
        "tintColor": "#6C5CE7",
        "versions": [version_obj],
    }

    screenshots = pick(merged, "photos", "screenshots", default=[])
    if isinstance(screenshots, list):
        urls = []
        for x in screenshots:
            if isinstance(x, str):
                u = normalize_url(x)
            elif isinstance(x, dict):
                u = normalize_url(pick(x, "url", "image", "src"))
            else:
                u = None
            if u:
                urls.append(u)
        if urls:
            app["screenshots"] = urls

    return app


def main():
    summaries = fetch_catalog()
    print(f"Fetched {len(summaries)} FlekSt0re catalog entries")

    alt_apps = []
    raw_samples = []
    for idx, summary in enumerate(summaries, 1):
        app_id = summary.get("id")
        try:
            detail = fetch_detail(app_id)
        except Exception as exc:
            print(f"WARN detail {app_id}: {exc}")
            detail = {}
        if idx <= 3:
            raw_samples.append({"summary": summary, "detail": detail})
        app = to_alt_app(summary, detail)
        if app:
            alt_apps.append(app)
        else:
            print(f"WARN no download URL for {app_id} {summary.get('name')}")
        if idx % 25 == 0:
            print(f"Processed {idx}/{len(summaries)}")
        time.sleep(0.03)

    alt_apps.sort(key=lambda x: x["name"].casefold())
    source = {
        "name": "FlekSt0re Lib Mirror",
        "identifier": "com.nightvibes33.flekstorelib",
        "subtitle": "AltSource mirror of the public FlekSt0re catalog",
        "description": "Automatically generated from FlekSt0re's public web catalog API.",
        "iconURL": "https://flekstore.com/favicon.ico",
        "website": "https://flekstore.com/",
        "tintColor": "#6C5CE7",
        "apps": alt_apps,
        "news": [],
    }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(source, f, ensure_ascii=False, indent=2)
        f.write("\n")
    with open("flekstore-api-sample.json", "w", encoding="utf-8") as f:
        json.dump(raw_samples, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"Wrote {OUT} with {len(alt_apps)} downloadable apps")


if __name__ == "__main__":
    main()
