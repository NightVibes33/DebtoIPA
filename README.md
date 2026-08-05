# DebToIPA

DebToIPA is a public, GitHub-authenticated iOS package analyzer and unsigned IPA builder. Users sign in with GitHub, upload a `.deb` to a temporary branch they own, and submit a build to DebToIPA’s hosted GitHub Actions workflow on `macos-15`.

**Live app:** https://debtoipa.vercel.app

## What it can convert

DebToIPA now has two genuine IPA build paths and two honest blocked outcomes.

### 1. Compatible original application

When the DEB already contains a standalone ARM64 iOS `.app`, DebToIPA validates its original executable, removes stale signing files, repairs the IPA layout and selected metadata, and publishes an unsigned IPA containing that same executable.

Machine-readable result: `real-ipa`.

### 2. Source-assisted stock-iOS rebuild

When the original jailbreak binary is not usable but the DEB includes supported SwiftUI or Objective-C UIKit source, DebToIPA can rebuild that source directly with Apple’s iPhoneOS compiler. It applies a small audited set of compatibility rewrites, packages the compiled ARM64 executable, and publishes a source-rebuilt unsigned IPA.

Machine-readable result: `source-ported`.

A source-rebuilt result proves that:

- The input source passed DebToIPA’s jailbreak/private-API policy.
- Xcode compiled an ARM64 iPhoneOS executable.
- The output IPA passed structural and Mach-O validation.
- No generic DebToIPA compatibility host was substituted.

Compilation does not prove exact behavioral or feature parity. The rebuilt app must still be installed, launched, and tested on a real device.

### 3. Original application preserved with blockers

When a package contains a real app but still depends on jailbreak loaders, daemons, private frameworks, helper processes, root filesystem paths, or unavailable entitlements, DebToIPA preserves the original app for inspection but does not call it usable on stock iOS.

Machine-readable result: `original-blocked`; the workflow is red.

### 4. Unsupported or report-only

When the package contains neither a usable standalone app nor source that DebToIPA can safely compile, it publishes reports and a generated port project when available. It does not fabricate an IPA.

Machine-readable result: `unsupported`; the workflow is red.

DebToIPA explicitly rejects the old `DebToIPACompatibilityHost` executable.

## Source-port package format

A DEB can opt into source-assisted rebuilding with this payload layout:

```text
usr/share/debtoipa/
├── PortManifest.json
├── Sources/
│   └── App.swift
└── Resources/
    └── Assets.xcassets/...
```

Recognized roots also include `DebToIPA/`, `Library/DebToIPA/`, and `var/jb/Library/DebToIPA/`. A recognized `Sources` directory can be auto-detected, but a manifest is recommended.

Example `PortManifest.json`:

```json
{
  "schemaVersion": 1,
  "kind": "swiftui-app",
  "appName": "Example",
  "bundleIdentifier": "com.example.app",
  "minimumIOS": "15.0",
  "device": "universal",
  "sourceRoots": ["usr/share/debtoipa/Sources"],
  "resourceRoots": ["usr/share/debtoipa/Resources"],
  "frameworks": ["SwiftUI", "Foundation"]
}
```

Supported kinds:

- `swiftui-app` — requires an `@main` application entry point.
- `uikit-objc-app` — requires `main.m` calling `UIApplicationMain`.

The source compiler does not run Makefiles, Theos, Swift Package plugins, maintainer scripts, or code from the uploaded package. It invokes `swiftc` or `clang` directly with a restricted set of public Apple frameworks.

## Safe automatic rewrites

The source path currently supports a limited set of explicit replacements:

- Cephei `HBPreferences` to an app-local `UserDefaults` compatibility class.
- Exact jailbreak preferences and documents directories to app sandbox directories.
- Darwin notification center calls to in-process notification center calls.

It rejects Logos hooks, MobileSubstrate/libhooker/ElleKit APIs, runtime hooking, private SpringBoard APIs, process injection/control, helper-process launching, jailbreak-only paths, private frameworks, unsafe symlinks, and path traversal.

These checks prevent DebToIPA from pretending an unavailable system-level feature can be recreated inside a normal app sandbox.

## Why arbitrary binary-only tweaks cannot be fully converted

A compiled jailbreak tweak does not contain enough information to automatically reconstruct its intended behavior using public APIs. MobileSubstrate injection, SpringBoard modifications, launch daemons, root filesystem access, private entitlements, and privileged process control are capabilities that normal iOS applications do not receive.

Therefore:

- A compatible standalone app can be repackaged.
- Supported package-provided source can be rebuilt with replacements.
- A binary-only jailbreak tweak that fundamentally requires privileged behavior cannot be made into an equivalent normal app by any generic DEB-to-IPA wrapper.

Such packages require their original source and package-specific redesign.

## Public build flow

1. Sign in with GitHub Device Flow.
2. Choose a `.deb` up to 250 MB.
3. DebToIPA uploads temporary chunks to the user-owned public `debtoipa-uploads` repository.
4. An authenticated issue starts `.github/workflows/public-convert.yml`.
5. Ubuntu validates identity, ownership, quota, and the upload manifest.
6. A GitHub-hosted `macos-15` runner reconstructs the package.
7. `scripts/runner_full_auto.py` tries the compatible-original path and then the constrained source-rebuild path.
8. The website tracks the exact workflow run and result kind through machine-readable issue comments.
9. Temporary upload branches are removed after completion.

Only one active build is allowed per GitHub account. Accounts must be at least seven days old. Artifacts are retained for three days.

## Repository components

- `public/public-runner.html` — GitHub login, upload, queue, conversion type, status, and artifact download
- `.github/workflows/public-convert.yml` — authenticated public macOS build queue
- `scripts/runner_full_auto.py` — binary-first and source-assisted orchestration
- `scripts/runner_smart_auto.py` — original application analysis and packaging
- `scripts/source_port.py` — constrained SwiftUI and Objective-C stock-iOS compiler
- `tests/test_source_port.py` — source policy and rewrite tests
- `tests/macos_source_port_smoke.py` — real Swift and Objective-C iPhoneOS compilation tests
- `public/converter.py` and `public/direct_guard.py` — Debian extraction and binary compatibility analysis
- `public/port_mode.py.gz.b64` — compatibility report and generated port-project support

## Validation

```bash
npm ci
npm run typecheck
npm run build
npm run test:converter
```

CI also:

- Parses both workflow files.
- Syntax-checks the exact browser JavaScript shipped to users.
- Uses a real `macos-15` runner and Xcode to build synthetic SwiftUI and Objective-C DEBs into ARM64 iPhoneOS IPAs.
- Verifies the resulting Info.plist, Mach-O executable, result metadata, and absence of the generic compatibility host.

## Signing

Generated IPAs are unsigned. Installation on a normal iPhone or iPad requires a valid Apple signature through Xcode, AltStore/SideStore, a signing service you control, or another lawful sideloading workflow.

## Security

- OAuth access tokens remain in the current browser tab’s `sessionStorage`.
- Uploaded package source and binaries are analyzed but never executed.
- Package build scripts are never run.
- Tar extraction rejects path traversal.
- Source roots reject symlinks and enforce file, count, and size limits.
- Framework and API allowlists block private or jailbreak-only dependencies.
- Users receive no write access to the DebToIPA repository or its workflows.
- Public workflows execute only trusted DebToIPA code.
