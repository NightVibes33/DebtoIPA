#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT_DIR="$ROOT/CompatibilityHost"
OUTPUT_DIR="${1:-$ROOT/output}"
DERIVED_DATA="$ROOT/.build/CompatibilityHost"

mkdir -p "$OUTPUT_DIR"
rm -rf "$DERIVED_DATA" "$PROJECT_DIR/DebToIPACompatibilityHost.xcodeproj"

if ! command -v xcodegen >/dev/null 2>&1; then
  brew install xcodegen
fi

cd "$PROJECT_DIR"
xcodegen generate --spec project.yml

xcodebuild \
  -project DebToIPACompatibilityHost.xcodeproj \
  -scheme DebToIPACompatibilityHost \
  -configuration Release \
  -sdk iphoneos \
  -derivedDataPath "$DERIVED_DATA" \
  CODE_SIGNING_ALLOWED=NO \
  CODE_SIGNING_REQUIRED=NO \
  CODE_SIGN_IDENTITY="" \
  build

APP="$DERIVED_DATA/Build/Products/Release-iphoneos/DebToIPACompatibilityHost.app"
if [[ ! -d "$APP" ]]; then
  echo "Compatibility host app was not produced at $APP" >&2
  exit 1
fi

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/Payload"
ditto "$APP" "$STAGE/Payload/DebToIPACompatibilityHost.app"

IPA="$OUTPUT_DIR/DebToIPA-CompatibilityHost-template.ipa"
rm -f "$IPA"
(
  cd "$STAGE"
  zip -qry -y "$IPA" Payload
)

unzip -t "$IPA"
plutil -lint "$APP/Info.plist"
file "$APP/DebToIPACompatibilityHost"

python3 - "$IPA" <<'PY'
import hashlib, json, pathlib, sys, zipfile
path = pathlib.Path(sys.argv[1])
with zipfile.ZipFile(path) as archive:
    names = archive.namelist()
    assert any(name == 'Payload/DebToIPACompatibilityHost.app/Info.plist' for name in names)
    assert any(name == 'Payload/DebToIPACompatibilityHost.app/DebToIPACompatibilityHost' for name in names)
print(json.dumps({
    'name': path.name,
    'size': path.stat().st_size,
    'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
    'signed': False,
}, indent=2))
PY
