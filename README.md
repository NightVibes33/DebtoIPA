# DebToIPA

DebToIPA is a public, GitHub-authenticated iOS package analyzer and unsigned IPA builder. Users sign in with GitHub, upload a `.deb` to a temporary repository branch they own, and submit a build to DebToIPA’s hosted GitHub Actions workflow on `macos-15`.

**Live app:** https://debtoipa.vercel.app

## Success contract

A successful DebToIPA build means all of the following are true:

- The package contains a standalone iOS `.app` bundle.
- The original app executable is ARM64 Mach-O.
- The executable does not depend on jailbreak-only loaders, filesystem paths, helper processes, or unavailable linked libraries.
- The generated unsigned IPA contains the original app executable.
- The IPA passes structural validation before it is published.

DebToIPA does **not** substitute a generic compatibility viewer, placeholder app, or informational shell. The executable `DebToIPACompatibilityHost` is explicitly rejected by the production runner.

## Unsupported packages

Packaging is not source-code conversion. Packages that depend on MobileSubstrate, ElleKit, libhooker, SpringBoard injection, launch daemons, root filesystem access, private entitlements, private frameworks, external helper executables, or other jailbreak services cannot become normal stock-iOS apps through repackaging.

For an unsupported package, the workflow fails honestly and publishes only:

- `conversion-report.json`
- `runner-summary.json`
- `README.txt`
- A generated source-level port project when the analyzer can produce one

No IPA is created for that result.

## Public build flow

1. Sign in with GitHub Device Flow.
2. Choose a `.deb` up to 250 MB.
3. DebToIPA uploads temporary chunks to the user-owned public `debtoipa-uploads` repository.
4. An authenticated issue starts `.github/workflows/public-convert.yml`.
5. Ubuntu validates identity, ownership, quota, and the upload manifest.
6. A GitHub-hosted `macos-15` runner reconstructs and analyzes the package.
7. The website tracks the exact workflow run through machine-readable issue comments.
8. Temporary upload branches are removed after completion.

Only one active build is allowed per GitHub account. Accounts must be at least seven days old. Build artifacts are retained for three days.

## Repository components

- `public/public-runner.html` — live GitHub login, upload, queue, status, and download client
- `app/api/oauth/device/route.ts` — starts GitHub Device Flow
- `app/api/oauth/token/route.ts` — polls GitHub for completion
- `.github/workflows/public-convert.yml` — validates requests and runs the public macOS build
- `scripts/runner_smart_auto.py` — enforces the original-app-only IPA contract
- `public/converter.py` and `public/direct_guard.py` — Debian extraction and direct compatibility analysis
- `public/port_mode.py.gz.b64` — report and source-level port-project generator

## Local validation

```bash
npm ci
npm run typecheck
npm run build
npm run test:converter
```

CI also parses the runner workflows and syntax-checks the exact JavaScript shipped inside `public/public-runner.html`.

## Signing

Generated IPAs are unsigned. Installation on a normal iPhone or iPad requires a valid Apple signature through Xcode, AltStore/SideStore, a signing service you control, or another lawful sideloading workflow.

## Security

- OAuth access tokens remain in the current browser tab’s `sessionStorage`.
- Uploaded package code is analyzed but never executed.
- Tar extraction rejects path traversal.
- Users receive no write access to the DebToIPA repository or its workflows.
- Public workflows execute only trusted code from the DebToIPA `main` branch.
