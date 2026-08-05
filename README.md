# DebToIPA

DebToIPA is a public, GitHub-authenticated iOS package analyzer and unsigned IPA builder. Users sign in with GitHub, upload a `.deb` to a temporary repository branch they own, and submit a build to DebToIPA’s hosted GitHub Actions workflow on `macos-15`.

**Live app:** https://debtoipa.vercel.app

## Honest result contract

DebToIPA reports three distinct outcomes:

### 1. Usable original-app IPA

A successful build means all of the following are true:

- The package contains a standalone iOS `.app` bundle.
- The original app executable is ARM64 Mach-O.
- Static analysis found no jailbreak-only loader, unavailable linked-library, helper-process, filesystem, or entitlement blockers.
- The generated unsigned IPA contains the original app executable.
- The IPA passes structural validation before publication.

This outcome uses the machine-readable result `real-ipa` and exits successfully.

### 2. Original app preserved with blockers

When a package contains a real standalone app, DebToIPA can preserve that original executable in an unsigned IPA even if jailbreak dependencies remain. This artifact is useful for inspection and package-specific porting, but it is **not** described as a usable stock-iOS conversion.

This outcome uses `original-blocked`, returns a failing workflow status, and includes the original app IPA, compatibility report, and generated port project when available.

### 3. Unsupported or report-only

When no standalone original app can be packaged, the workflow publishes only the report files and generated source-level port project when available. This outcome uses `unsupported` and returns a failing workflow status.

DebToIPA does **not** substitute a generic compatibility viewer, placeholder app, or informational shell. The executable `DebToIPACompatibilityHost` is explicitly rejected by the production runner.

## Why some packages cannot become normal IPAs

Packaging is not source-code conversion. Packages that depend on MobileSubstrate, ElleKit, libhooker, SpringBoard injection, launch daemons, root filesystem access, private entitlements, private frameworks, external helper executables, or other jailbreak services cannot become normal stock-iOS apps merely by wrapping their files in `Payload/`.

A complete stock-iOS port of such a package requires package-specific source code and public-API replacements for the unavailable behavior.

## Public build flow

1. Sign in with GitHub Device Flow.
2. Choose a `.deb` up to 250 MB.
3. DebToIPA uploads temporary chunks to the user-owned public `debtoipa-uploads` repository.
4. An authenticated issue starts `.github/workflows/public-convert.yml`.
5. Ubuntu validates identity, ownership, quota, and the upload manifest.
6. A GitHub-hosted `macos-15` runner reconstructs and analyzes the package.
7. The website tracks the exact workflow run and result kind through machine-readable issue comments.
8. Temporary upload branches are removed after completion.

Only one active build is allowed per GitHub account. Accounts must be at least seven days old. Build artifacts are retained for three days.

## Repository components

- `public/public-runner.html` — GitHub login, upload, queue, honest result status, and artifact download client
- `app/api/oauth/device/route.ts` — starts GitHub Device Flow
- `app/api/oauth/token/route.ts` — polls GitHub for completion
- `.github/workflows/public-convert.yml` — validates requests and publishes `real-ipa`, `original-blocked`, or `unsupported`
- `scripts/runner_smart_auto.py` — preserves original app binaries and enforces the three-outcome contract
- `public/converter.py` and `public/direct_guard.py` — Debian extraction and direct compatibility analysis
- `public/port_mode.py.gz.b64` — compatibility report and source-level port-project generator

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
