# DebtoIPA

DebtoIPA is a mobile-first Vercel application backed by a GitHub Actions conversion worker. It accepts an iOS Debian package, locates a real `.app` bundle, checks whether that binary is plausibly usable on stock iOS, repairs the IPA layout and selected metadata, and returns an unsigned IPA plus a JSON compatibility report.

**Live app:** https://nightvibes33-debtoipa.vercel.app

**Production status:** the web application and GitHub conversion workflow are deployed and green. Before uploads and conversion dispatches work, connect a Public Vercel Blob store and add the GitHub token variables listed below to the `nightvibes33-debtoipa` Vercel project, then redeploy.

## What it does

- Direct browser-to-Vercel Blob uploads up to 750 MB
- GitHub Actions workflow dispatch and live job polling
- Debian `data.tar.*` extraction, including zstd payloads
- `.app` discovery under rootful or rootless package layouts
- ARM64/Mach-O, executable, jailbreak-loader, rootless-path, and linked-library checks
- Correct `Payload/App.app` IPA structure
- Optional iPhone, iPad, or universal `UIDeviceFamily`
- Optional minimum iOS, bundle ID, and display-name overrides
- Removal of stale signatures and provisioning profiles before repackaging
- Three-day GitHub artifact retention with the IPA, report, and readable summary

## Hard limitation

Packaging is not source-code conversion. A MobileSubstrate/ElleKit/libhooker tweak, SpringBoard injection bundle, launch daemon, root-dependent tool, 32-bit binary, or app linked to jailbreak-only libraries cannot be made stock-compatible by wrapping it in `Payload/`. DebtoIPA rejects these packages instead of producing a misleading IPA.

The generated IPA is unsigned. A normal iPhone or iPad still requires a valid Apple signature through Xcode, AltStore/SideStore, a signing service you control, or another lawful sideloading workflow.

## Deploy

The active Vercel project is `nightvibes33-debtoipa`.

1. Open the project in Vercel.
2. Create a **Public Vercel Blob** store and connect it to the project. Vercel adds `BLOB_READ_WRITE_TOKEN` automatically.
3. Create a fine-grained GitHub token limited to `NightVibes33/DebtoIPA` with:
   - Actions: Read and write
   - Contents: Read
4. Add these Vercel environment variables for Production, Preview, and Development:

```text
GITHUB_TOKEN=github_pat_...
GITHUB_OWNER=NightVibes33
GITHUB_REPO=DebtoIPA
APP_ACCESS_CODE=optional-private-code
```

5. Redeploy. The web app uploads the `.deb` to a random public Blob URL, dispatches `.github/workflows/convert.yml`, polls the run, and proxies the short-lived GitHub artifact download.

## Local development

```bash
npm ci
cp .env.example .env.local
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

## Security model

- The Vercel API only accepts workflow inputs pointing to Vercel public Blob hosts.
- Filenames and workflow arguments are passed through environment variables, not evaluated as shell code.
- Tar extraction rejects path traversal.
- GitHub credentials stay server-side in Vercel environment variables.
- `APP_ACCESS_CODE` can restrict uploads, dispatch, status, and downloads.
- Artifact downloads are limited to non-expired `DebtoIPA-*` artifacts and expire after three days.

For a production multi-user service, add real authentication, per-user ownership, rate limiting, and automatic Blob deletion after every completed run.
