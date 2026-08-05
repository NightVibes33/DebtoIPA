# DebtoIPA

DebtoIPA is a mobile-first, zero-setup Vercel app that converts compatible iOS Debian packages entirely inside the browser. The `.deb` never needs to be uploaded to Vercel Blob or GitHub. A Web Worker opens the package, locates a real `.app`, checks whether its ARM64 binary is plausibly usable on stock iOS, repairs the IPA layout and selected metadata, and downloads an unsigned IPA plus a JSON compatibility report.

**Live app:** https://debtoipa.vercel.app

## No setup required

Open the app, choose a `.deb`, select the target device, and tap **Convert on this device**. There are no accounts, tokens, access codes, environment variables, storage connections, or runner configuration steps.

## What it does

- Private on-device conversion in a dedicated browser Web Worker
- Debian `data.tar.*` extraction, including gzip, bzip2, xz, and zstd payloads
- `.app` discovery under rootful or rootless package layouts
- ARM64/Mach-O, executable, jailbreak-loader, rootless-path, and linked-library checks
- Correct `Payload/App.app` IPA structure
- Optional iPhone, iPad, or universal `UIDeviceFamily`
- Optional minimum iOS, bundle ID, and display-name overrides
- Removal of stale signatures and provisioning profiles before repackaging
- A downloadable result ZIP containing the unsigned IPA and compatibility report
- No server-side copy of the uploaded package or generated result

The mobile UI currently limits packages to 350 MB to reduce browser memory crashes. Desktop browsers may still be constrained by available memory.

## Hard limitation

Packaging is not source-code conversion. A MobileSubstrate/ElleKit/libhooker tweak, SpringBoard injection bundle, launch daemon, root-dependent tool, 32-bit binary, or app linked to jailbreak-only libraries cannot be made stock-compatible by wrapping it in `Payload/`. DebtoIPA rejects these packages and produces a compatibility report instead of a misleading IPA.

The generated IPA is unsigned. A normal iPhone or iPad still requires a valid Apple signature through Xcode, AltStore/SideStore, a signing service you control, or another lawful sideloading workflow.

## Architecture

- Next.js provides the installable mobile web interface.
- `public/converter-worker.js` runs conversion off the main UI thread.
- Pyodide runs `public/converter.py` locally in the browser.
- The original GitHub Actions/CLI converter remains available for CI and development, but the production UI does not require it.

## Local development

```bash
npm ci
npm run dev
```

Converter tests:

```bash
npm run test:converter
```

Direct CLI usage:

```bash
python3 scripts/convert_deb.py \
  --deb Example.deb \
  --output Example.ipa \
  --report conversion-report.json \
  --device universal \
  --minimum-ios 15.0
```

## Privacy and security

- Package bytes remain in the current browser session.
- Conversion runs in an isolated Web Worker.
- Tar extraction rejects path traversal.
- The converter never executes code from the package.
- No GitHub credential or Vercel storage token is exposed to the browser.
- Generated downloads disappear when the page is refreshed or closed unless the user saves them.
