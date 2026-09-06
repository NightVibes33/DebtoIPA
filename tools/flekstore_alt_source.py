#!/usr/bin/env python3
import html
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests

BASE = "https://flekstore.com"
API_BASE = "https://nestapi.flekstore.com"
API_APPS = f"{API_BASE}/app/with-link"
OUT = os.environ.get("OUT", "source.json")
PAGE_SIZE = 30
SOURCE_URL = "https://raw.githubusercontent.com/NightVibes33/DebtoIPA/flekstore-alt-source/source.json"
HEADERS = {
    "User-Agent": "FlekDeck/1.0",
    "Accept": "application/json, text/plain, */*",
}

# Upstream FlekSt0re occasionally leaves catalog records pointing to deleted S3
# objects. For open-source apps only, use the original developer's official IPA
# release instead of a random mirror. Commercial apps are intentionally not
# substituted here.
RECOVERY_URLS = {
    "KillMyOTA": "https://github.com/haxi0/KillMyOTA/releases/download/1.1/KillMyOTA-1.1.ipa",
    "WDBFontOverwrite": "https://github.com/ginsudev/WDBFontOverwrite/releases/download/v1.10.8/WDBFontOverwrite.ipa",
}


def get_json(url, params=None, retries=2):
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, params=params, timeout=20, headers=HEADERS)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last = e
            if i + 1 < retries:
                time.sleep(0.75 * (i + 1))
    raise RuntimeError(f"GET failed: {url}: {last}")


def normalize_url(value):
    if not value:
        return None
    value = str(value).strip()
    if value.startswith("//"):
        return "https:" + value
    if value.startswith(("http://", "https://")):
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
    mult = {"b": 1, "kb": 1000, "kib": 1024, "mb": 1000**2, "mib": 1024**2, "gb": 1000**3, "gib": 1024**3}[unit]
    return int(n * mult)


def iso_date(value):
    if not value:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    text = str(value).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}T", text):
        if text.endswith("Z"):
            return text
        return text.replace("+00:00", "Z")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d.%m.%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            pass
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean_text(value, limit=700):
    text = str(value or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</div\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        text = "FlekSt0re catalog app"
    return text[:limit]


def fetch_catalog():
    apps, seen = [], set()
    for page in range(101):
        data = get_json(API_APPS, {"page": page, "search": "false", "filter": "all"})
        rows = data.get("data", data) if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise RuntimeError(f"Unexpected with-link response on page {page}: {type(rows).__name__}")
        if not rows:
            break
        for row in rows:
            key = str(row.get("app_id", row.get("id", "")))
            if key and key not in seen:
                seen.add(key)
                apps.append(row)
        if len(rows) < PAGE_SIZE:
            break
    else:
        raise RuntimeError("Pagination safety stop")
    return apps


def fetch_detail(app_id):
    data = get_json(f"{API_BASE}/app/{app_id}")
    return data.get("data", data) if isinstance(data, dict) else data


def to_alt_app(summary, detail):
    detail = detail if isinstance(detail, dict) else {}

    app_id = str(pick(summary, "app_id", "id", default=pick(detail, "id", default="unknown")))
    name = str(pick(summary, "app_name", "name", default=pick(detail, "name", default=f"FlekSt0re App {app_id}"))).strip()
    version = str(pick(summary, "app_version", "version", default=pick(detail, "version", default="1.0"))).strip()

    # `/app/with-link` carries the real public object URL. If that object was
    # deleted and an original open-source developer release is known, use it.
    download = RECOVERY_URLS.get(name) or normalize_url(pick(summary, "install_url", "downloadURL", "download_url"))
    if not download:
        return None

    icon = normalize_url(pick(summary, "app_icon", "icon", default=pick(detail, "icon"))) or "https://flekstore.com/favicon.ico"
    description = clean_text(pick(detail, "description", default=pick(summary, "app_short_description", "short_description", default="FlekSt0re catalog app")), 700)
    subtitle = clean_text(pick(summary, "app_short_description", "short_description", default=description), 100)
    developer = clean_text(pick(detail, "developer", default="FlekSt0re"), 80)
    size = parse_size(pick(detail, "size", default=0))
    date = iso_date(pick(detail, "date"))
    bundle = clean_bundle(pick(detail, "bundle_id", "bundleIdentifier", "bundle_identifier", "bundleid", "package", "identifier"), app_id)

    app = {
        "name": name,
        "bundleIdentifier": bundle,
        "developerName": developer,
        "subtitle": subtitle,
        "localizedDescription": description,
        "iconURL": icon,
        "tintColor": "6C5CE7",
        "version": version,
        "versionDate": date,
        "versionDescription": description[:250],
        "downloadURL": download,
        "size": size,
        "versions": [{
            "version": version,
            "date": date,
            "size": size,
            "downloadURL": download,
            "localizedDescription": description[:250],
        }],
    }
    return app


def validate_source(source):
    allowed_source = {"name", "identifier", "apps", "news", "sourceURL"}
    allowed_app = {
        "name", "bundleIdentifier", "developerName", "subtitle", "localizedDescription",
        "iconURL", "tintColor", "version", "versionDate", "versionDescription",
        "downloadURL", "size", "versions", "screenshotURLs", "permissions", "beta"
    }
    allowed_version = {"version", "date", "localizedDescription", "downloadURL", "size", "minOSVersion", "maxOSVersion"}
    extra_source = set(source) - allowed_source
    assert not extra_source, f"Unsupported source keys: {sorted(extra_source)}"
    assert source.get("name") and source.get("identifier") and isinstance(source.get("apps"), list)
    for app in source["apps"]:
        extra_app = set(app) - allowed_app
        assert not extra_app, f"Unsupported app keys for {app.get('name')}: {sorted(extra_app)}"
        for req in ("name", "bundleIdentifier", "developerName", "localizedDescription", "iconURL", "versions", "downloadURL"):
            assert app.get(req) not in (None, ""), f"Missing {req} for {app.get('name')}"
        assert app["downloadURL"].startswith("https://"), f"non-HTTPS download URL for {app.get('name')}: {app['downloadURL']}"
        assert isinstance(app["versions"], list) and app["versions"]
        for ver in app["versions"]:
            extra_ver = set(ver) - allowed_version
            assert not extra_ver, f"Unsupported version keys for {app.get('name')}: {sorted(extra_ver)}"
            for req in ("version", "date", "downloadURL", "size"):
                assert req in ver, f"Missing version {req} for {app.get('name')}"


def main():
    summaries = fetch_catalog()
    print(f"Fetched {len(summaries)} FlekSt0re catalog entries with direct links", flush=True)

    details = {}
    with ThreadPoolExecutor(max_workers=18) as pool:
        futures = {pool.submit(fetch_detail, s.get("app_id", s.get("id"))): s for s in summaries}
        done = 0
        for fut in as_completed(futures):
            summary = futures[fut]
            app_id = summary.get("app_id", summary.get("id"))
            try:
                details[str(app_id)] = fut.result()
            except Exception as exc:
                print(f"WARN detail {app_id}: {exc}", flush=True)
                details[str(app_id)] = {}
            done += 1
            if done % 25 == 0:
                print(f"Resolved {done}/{len(summaries)} details", flush=True)

    alt_apps, raw_samples = [], []
    for idx, summary in enumerate(summaries):
        app_id = summary.get("app_id", summary.get("id"))
        detail = details.get(str(app_id), {})
        if idx < 3:
            raw_samples.append({"summary": summary, "detail": detail})
        app = to_alt_app(summary, detail)
        if app:
            alt_apps.append(app)
        else:
            print(f"WARN no direct download URL for {app_id} {summary.get('app_name', summary.get('name'))}", flush=True)

    alt_apps.sort(key=lambda x: x["name"].casefold())
    source = {
        "name": "FlekSt0re Lib Mirror",
        "identifier": "com.nightvibes33.flekstorelib",
        "sourceURL": SOURCE_URL,
        "apps": alt_apps,
        "news": [],
    }
    validate_source(source)

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(source, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    with open("flekstore-api-sample.json", "w", encoding="utf-8") as f:
        json.dump(raw_samples, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"Wrote {OUT} with {len(alt_apps)} apps using direct IPA URLs ({os.path.getsize(OUT)} bytes)", flush=True)


if __name__ == "__main__":
    main()
