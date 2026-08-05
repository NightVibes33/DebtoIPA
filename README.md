# DebToIPA

DebToIPA is a GitHub-authenticated `.deb` analyzer and unsigned IPA builder for normal iOS. It does not pretend that changing an archive extension converts jailbreak privileges. Instead, it builds a capability graph and selects among several real conversion strategies.

**Live app:** https://debtoipa.vercel.app

## Conversion profiles

### 1. Compatible original application (`direct-ipa`)

When the DEB contains a standalone ARM64 iOS `.app` with no detected stock-iOS blockers, DebToIPA removes stale signing data, repairs the IPA layout and selected metadata, and packages the same original executable.

### 2. Original binary with audited shims (`binary-shimmed`)

For narrowly supported binaries, DebToIPA can:

- detect common Cephei/HBPreferences framework dependencies;
- compile an ARM64 `DebToIPAAdapters.framework` against the iPhoneOS SDK;
- redirect supported Mach-O load commands with `install_name_tool`;
- embed the adapter framework under the app's `Frameworks` directory;
- map common HBPreferences calls to `UserDefaults`;
- interpose common legacy filesystem calls and map selected `/var/mobile` paths into the app sandbox;
- validate the repaired dependency graph and IPA structure.

This path does not emulate MobileSubstrate, ElleKit, libhooker, RocketBootstrap cross-process behavior, private frameworks, root access, or private entitlements.

### 3. Package-provided source rebuild (`source-ported`)

When supported source is included, DebToIPA compiles a new ARM64 iPhoneOS executable with Apple's `swiftc` or `clang`. Supported source kinds are:

- SwiftUI applications;
- UIKit applications written in Swift;
- Objective-C/UIKit applications;
- mixed Swift, Objective-C, C, and C++ applications.

The source compiler never executes package scripts, Makefiles, shell scripts, or package-provided build tools.

### 4. Application plus normal iOS extensions (`app-extensions`)

Source packages can request generated replacements such as:

- WidgetKit widgets for glanceable SpringBoard UI;
- Share Extensions for user-approved cross-app input;
- Safari Web Extensions or content blockers;
- App Intents and Shortcuts;
- generated native settings code.

The extensions are embedded under `PlugIns/` and compiled against the iPhoneOS SDK. Installation and distribution still require correct Apple signing and any necessary capabilities.

### 5. Background replacement (`background-replacement`)

Launch-daemon behavior can be redesigned using:

- `BGTaskScheduler` refresh and processing tasks;
- background `URLSession` transfers;
- optional push-triggered synchronization;
- bounded in-app event handlers.

These are normal iOS scheduling mechanisms. They do not provide a continuously running unrestricted daemon.

### 6. Companion service (`companion-service`)

For continuous or scheduled work that is appropriate to move off-device, DebToIPA generates:

- a small Vercel TypeScript service project;
- an iOS async client;
- a package-specific integration manifest.

A companion service cannot recreate root access, process injection, kernel behavior, or private entitlements.

### 7. Port project and report (`report-only`)

When no runnable conversion is honest, DebToIPA returns the capability graph, blockers, selected alternatives, generated adapter/extension/service project, and source-port scaffolding. It never substitutes a generic informational app.

## Capability graph

Every build produces `capability-plan.json` and `CAPABILITY_PLAN.md`. The analyzer detects evidence for:

- Cephei/HBPreferences;
- root or global filesystem paths;
- Darwin notifications;
- launch daemons;
- SpringBoard/system UI hooks;
- cross-app injection frameworks;
- preference bundles;
- command-line helpers;
- Safari injection;
- network filtering;
- private frameworks and entitlements;
- root/process-control behavior.

Each capability records alternatives, automation level, source requirements, entitlement requirements, evidence, and an estimated retained-functionality score.

## Source-port manifest

Recommended payload layout:

```text
usr/share/debtoipa/
├── PortManifest.json
├── Sources/
└── Resources/
```

Example:

```json
{
  "schemaVersion": 2,
  "kind": "swiftui-app",
  "appName": "Example",
  "bundleIdentifier": "com.example.normal",
  "minimumIOS": "15.0",
  "device": "universal",
  "sourceRoots": ["usr/share/debtoipa/Sources"],
  "resourceRoots": ["usr/share/debtoipa/Resources"],
  "requestedAlternatives": [
    "preferences-adapter",
    "sandbox-path-adapter",
    "background-task",
    "widget-extension",
    "app-intents"
  ],
  "extensions": ["widget"],
  "companionService": false
}
```

Recognized source roots also include `DebToIPA/Sources`, `Library/DebToIPA/Sources`, and `var/jb/Library/DebToIPA/Sources`.

## Safe automatic rewrites

The source compiler has a deliberately narrow rewrite set:

- common `HBPreferences` initialization → generated `DebToIPAPreferences`/local Objective-C adapter;
- Cephei headers/imports → generated adapter files;
- common `/var/mobile/Documents` paths → app Documents;
- common `/var/mobile/Library/Preferences` and rootless paths → Application Support;
- Darwin notification center → local notification center where semantics permit.

It rejects Logos hooks, injection frameworks, private frameworks, helper-process execution, process control, privileged IOKit/host APIs, unsafe paths, symlinks, and arbitrary build scripts.

## Public builder

The website exposes:

- Automatic — highest compatibility;
- Preserve original app;
- Original binary + audited shims;
- Rebuild package source;
- App + normal iOS extensions;
- Replace daemon/background work;
- App + companion service;
- Analyze and generate port project.

Users can independently request preference, path, notification, settings, widget, Share, Safari, App Intent, background, document-picker, and companion-service alternatives.

## Result contract

Green workflow results are limited to:

- `real-ipa` — compatible original executable packaged;
- `binary-shimmed` — original executable retained and supported dependencies redirected to audited adapters;
- `source-ported` — a new ARM64 iPhoneOS executable compiled from package source.

Blocked results are:

- `original-blocked` — original app preserved but required jailbreak capabilities remain;
- `unsupported` — no honest runnable conversion; reports and generated project only.

The executable `DebToIPACompatibilityHost` is explicitly rejected by the production runner.

## Testing

Ubuntu CI validates:

- production dependency audit;
- TypeScript type checking;
- production Next.js build;
- Python syntax;
- capability graph, adapter generation, source rewrite, and security-policy tests;
- workflow YAML;
- the exact browser JavaScript shipped to users;
- required multi-profile result markers.

macOS/Xcode CI builds and validates a permanent matrix:

1. compatible original ARM64 app;
2. original app linked to a fake Cephei framework and repaired to the embedded adapter;
3. SwiftUI source package using Cephei/path rewrites, background tasks, WidgetKit, App Intents, and a companion service;
4. Objective-C source package using HBPreferences rewrite and a Share Extension;
5. binary-only SpringBoard/Logos package that must fail without generating a fake IPA.

## Signing and runtime validation

Generated IPAs are unsigned. Installation requires a valid Apple signature through a lawful signing workflow. Compiler and structural validation do not prove exact runtime or feature parity. Every package-specific output still requires signed installation, launch testing, and feature testing on a real device.

## Hard platform boundary

Normal iOS does not expose generic equivalents for:

- SpringBoard or other-process injection;
- unrestricted root/global filesystem access;
- continuously running arbitrary daemons;
- arbitrary process control or memory modification;
- private entitlements or private frameworks;
- kernel/jailbreak services;
- global system customization outside Apple-supported extensions.

DebToIPA can redesign such behavior as a standalone app, extension, bounded background task, user-approved file flow, or companion service when source and public APIs make that possible. It cannot grant privileges the operating system refuses to third-party apps.
