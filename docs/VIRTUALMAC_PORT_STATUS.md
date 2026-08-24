# VirtualMac Port Status

- Run: 32682163786
- Commit tested: 5d4c949d879fac09d461a300c0ef7be7288cae25
- Unit tests: success
- Upstream source profile: success
- Upstream 1.2 DEB profile: success

## Compatible reference target
```json
{
  "architecture": "all",
  "compatibility": {
    "reasons": [
      "Virtual Mac requires a jailbreak package with privileged helpers, launch daemons, tweak injection, and extracted/patched Apple virtualization frameworks.",
      "A standalone stock-iOS IPA cannot provide the required VM runtime or private virtualization privileges."
    ],
    "recommendedArtifact": "jailbreak-deb",
    "recommendedPath": "source-build-or-current-upstream-deb",
    "requiresHardwareVirtualization": true,
    "requiresJailbreak": true,
    "stockIpaSupported": false,
    "supportedChipFamilies": [
      "M1",
      "M2"
    ],
    "supportedOSRange": "iPadOS 14.0 through 16.3.1",
    "targetStatus": "upstream-compatible",
    "upstreamCompatible": true
  },
  "depends": "firmware (>= 14.5), firmware (<< 16.4), ellekit | org.coolstar.libhooker",
  "isVirtualMac": true,
  "kind": "deb",
  "name": "Virtual Mac",
  "package": "com.mac.virtual",
  "packagePaths": {
    "var/jb/Applications/VirtualMac.app": "rootless application",
    "var/jb/Library/LaunchDaemons": "rootless launch daemons",
    "var/jb/basebin/LaunchDaemons": "Dopamine launch daemons",
    "var/jb/usr/libexec": "privileged helper executables",
    "var/root/VirtualMac": "shared VM/runtime payload",
    "var/root/VirtualMac/bootstrap-common/usr/lib/TweakInject": "tweak injection payload"
  },
  "path": "/tmp/VirtualMac_1.2.deb",
  "payloadEntryCount": 385,
  "runtimeMarkers": {
    "var/jb/Applications/VirtualMac.app/VZHostCompat.dylib": [
      "Virtualization XPC service",
      "virtualization entitlement"
    ],
    "var/jb/Applications/VirtualMac.app/VirtualMac": [
      "Apple Hypervisor framework",
      "Apple Virtualization framework",
      "SpringBoard keyboard passthrough tweak",
      "VM networking stack",
      "Virtualization XPC service",
      "paravirtualized graphics stack",
      "privileged installer launcher",
      "virtualization entitlement"
    ],
    "var/jb/usr/bin/virtualmac-diagnostics": [
      "SpringBoard keyboard passthrough tweak",
      "privileged installer launcher"
    ],
    "var/jb/usr/libexec/InternetSharing": [
      "VM networking stack"
    ],
    "var/jb/usr/libexec/InternetSharing.ipados14": [
      "VM networking stack"
    ],
    "var/jb/usr/libexec/InternetSharing.ipados15": [
      "VM networking stack"
    ],
    "var/jb/usr/libexec/InternetSharing.ipados16": [
      "VM networking stack"
    ],
    "var/jb/usr/share/VirtualMac/trustcache.txt": [
      "Apple Hypervisor framework",
      "Apple Virtualization framework",
      "SpringBoard keyboard passthrough tweak",
      "VM networking stack",
      "Virtualization XPC service",
      "paravirtualized graphics stack",
      "privileged installer launcher"
    ],
    "var/root/VirtualMac/bootstrap-common/usr/lib/TweakInject/VZKeyboardPassthrough.dylib": [
      "SpringBoard keyboard passthrough tweak"
    ],
    "var/root/VirtualMac/bootstrap-rootful/usr/libexec/VirtualMac/InternetSharing.ipados14": [
      "VM networking stack"
    ],
    "var/root/VirtualMac/install/VZHostCompat.dylib": [
      "Virtualization XPC service",
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/install/install-launcher": [
      "privileged installer launcher",
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/install/install-macos": [
      "Apple Hypervisor framework",
      "Apple Virtualization framework",
      "Virtualization XPC service",
      "paravirtualized graphics stack",
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/install/start-install.sh": [
      "privileged installer launcher"
    ],
    "var/root/VirtualMac/payload/Compatibility/iPadOS14/Hypervisor": [
      "Apple Hypervisor framework",
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Compatibility/iPadOS14/IOKit15Compat.dylib": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Compatibility/iPadOS14/LibSystemCompat.dylib": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Compatibility/iPadOS14/ParavirtualizedGraphics": [
      "paravirtualized graphics stack"
    ],
    "var/root/VirtualMac/payload/Compatibility/iPadOS14/Virtualization": [
      "Apple Hypervisor framework",
      "Apple Virtualization framework",
      "VM networking stack",
      "Virtualization XPC service",
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Compatibility/iPadOS14/vmnet": [
      "VM networking stack"
    ],
    "var/root/VirtualMac/payload/Compatibility/iPadOS15/Hypervisor": [
      "Apple Hypervisor framework"
    ],
    "var/root/VirtualMac/payload/Compatibility/iPadOS15/ParavirtualizedGraphics": [
      "paravirtualized graphics stack"
    ],
    "var/root/VirtualMac/payload/Compatibility/iPadOS15/Virtualization": [
      "Apple Hypervisor framework",
      "Apple Virtualization framework",
      "VM networking stack",
      "Virtualization XPC service",
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Compatibility/iPadOS15Authenticated/Hypervisor": [
      "Apple Hypervisor framework"
    ],
    "var/root/VirtualMac/payload/Compatibility/iPadOS15Authenticated/ParavirtualizedGraphics": [
      "paravirtualized graphics stack"
    ],
    "var/root/VirtualMac/payload/Compatibility/iPadOS15Authenticated/Virtualization": [
      "Apple Hypervisor framework",
      "Apple Virtualization framework",
      "VM networking stack",
      "Virtualization XPC service",
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Frameworks/Hypervisor.framework/Versions/A/Hypervisor": [
      "Apple Hypervisor framework"
    ],
    "var/root/VirtualMac/payload/Frameworks/IOKit15Compat.dylib": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Frameworks/LaunchServicesCompat.dylib": [
      "Apple Hypervisor framework",
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Frameworks/LaunchServicesCompat.dylib.ipados14": [
      "Apple Hypervisor framework",
      "VM networking stack",
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Frameworks/LibSystem15Compat.dylib": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Frameworks/MetalCompat.dylib": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Frameworks/ParavirtualizedGraphics.framework/Versions/A/ParavirtualizedGraphics": [
      "paravirtualized graphics stack"
    ],
    "var/root/VirtualMac/payload/Frameworks/Virtualization.framework/Versions/A/Resources/Localizable.loctable": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Frameworks/Virtualization.framework/Versions/A/Virtualization": [
      "Apple Hypervisor framework",
      "Apple Virtualization framework",
      "VM networking stack",
      "Virtualization XPC service",
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Frameworks/vmnet.framework/vmnet": [
      "VM networking stack"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/CoreServicesCompat.dylib": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/CoreUtilsCompat.dylib": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/CrashReporterCompat.dylib": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/DiskImagesCompat.dylib": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/Foundation14Compat.dylib": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/IOKit14Compat.dylib": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/InstallationCompat.dylib": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/InstallationCompat.dylib.ipados14": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/InstallationCompat.dylib.ipados15": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/InstallationCompat.dylib.ipados16": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/MobileDevice.framework/Versions/A/MobileDevice": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/MobileDevice.framework/Versions/A/MobileDevice.ipados14": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/MobileDevice.framework/Versions/A/MobileDevice.ipados15": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/MobileDevice.framework/Versions/A/MobileDevice.ipados15-auth": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/MobileDevice.framework/Versions/A/MobileDevice.ipados16": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/MobileDevice.framework/Versions/A/Resources/usbmuxd": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/SecurityCompat.dylib": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/SoftLinking14Compat.dylib": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/MacOS/com.apple.Virtualization.Installation": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/MacOS/com.apple.Virtualization.Installation.ipados14": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/MacOS/com.apple.Virtualization.Installation.ipados15": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/MacOS/com.apple.Virtualization.Installation.ipados15-auth": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/MacOS/com.apple.Virtualization.Installation.ipados16": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/VirtualMachine.xpc/Contents/Info.plist": [
      "Virtualization XPC service"
    ],
    "var/root/VirtualMac/payload/VirtualMachine.xpc/Contents/MacOS/com.apple.Virtualization.VirtualMachine": [
      "Apple Hypervisor framework",
      "Apple Virtualization framework",
      "VM networking stack",
      "Virtualization XPC service",
      "paravirtualized graphics stack",
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/VirtualMachine.xpc/Contents/MacOS/com.apple.Virtualization.VirtualMachine.ipados14": [
      "Apple Hypervisor framework",
      "Apple Virtualization framework",
      "VM networking stack",
      "Virtualization XPC service",
      "paravirtualized graphics stack",
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/VirtualMachine.xpc/Contents/MacOS/com.apple.Virtualization.VirtualMachine.ipados15": [
      "Apple Hypervisor framework",
      "Apple Virtualization framework",
      "VM networking stack",
      "Virtualization XPC service",
      "paravirtualized graphics stack",
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/VirtualMachine.xpc/Contents/MacOS/com.apple.Virtualization.VirtualMachine.ipados16": [
      "Apple Hypervisor framework",
      "Apple Virtualization framework",
      "VM networking stack",
      "Virtualization XPC service",
      "paravirtualized graphics stack",
      "virtualization entitlement"
    ]
  },
  "target": {
    "chip": "M1",
    "ios": "16.3.1"
  },
  "version": "2:1.2+565.799fc13aff"
}
```

## Unsupported-device proof
```json
{
  "architecture": "all",
  "compatibility": {
    "reasons": [
      "Virtual Mac requires a jailbreak package with privileged helpers, launch daemons, tweak injection, and extracted/patched Apple virtualization frameworks.",
      "A standalone stock-iOS IPA cannot provide the required VM runtime or private virtualization privileges.",
      "Chip A9 is outside upstream Virtual Mac's M1/M2 hardware support envelope.",
      "iPadOS 16.7.11 is 16.4 or newer; upstream documents removal of required Hypervisor kernel support in this range."
    ],
    "recommendedArtifact": "jailbreak-deb",
    "recommendedPath": "source-build-or-current-upstream-deb",
    "requiresHardwareVirtualization": true,
    "requiresJailbreak": true,
    "stockIpaSupported": false,
    "supportedChipFamilies": [
      "M1",
      "M2"
    ],
    "supportedOSRange": "iPadOS 14.0 through 16.3.1",
    "targetStatus": "incompatible",
    "upstreamCompatible": false
  },
  "depends": "firmware (>= 14.5), firmware (<< 16.4), ellekit | org.coolstar.libhooker",
  "isVirtualMac": true,
  "kind": "deb",
  "name": "Virtual Mac",
  "package": "com.mac.virtual",
  "packagePaths": {
    "var/jb/Applications/VirtualMac.app": "rootless application",
    "var/jb/Library/LaunchDaemons": "rootless launch daemons",
    "var/jb/basebin/LaunchDaemons": "Dopamine launch daemons",
    "var/jb/usr/libexec": "privileged helper executables",
    "var/root/VirtualMac": "shared VM/runtime payload",
    "var/root/VirtualMac/bootstrap-common/usr/lib/TweakInject": "tweak injection payload"
  },
  "path": "/tmp/VirtualMac_1.2.deb",
  "payloadEntryCount": 385,
  "runtimeMarkers": {
    "var/jb/Applications/VirtualMac.app/VZHostCompat.dylib": [
      "Virtualization XPC service",
      "virtualization entitlement"
    ],
    "var/jb/Applications/VirtualMac.app/VirtualMac": [
      "Apple Hypervisor framework",
      "Apple Virtualization framework",
      "SpringBoard keyboard passthrough tweak",
      "VM networking stack",
      "Virtualization XPC service",
      "paravirtualized graphics stack",
      "privileged installer launcher",
      "virtualization entitlement"
    ],
    "var/jb/usr/bin/virtualmac-diagnostics": [
      "SpringBoard keyboard passthrough tweak",
      "privileged installer launcher"
    ],
    "var/jb/usr/libexec/InternetSharing": [
      "VM networking stack"
    ],
    "var/jb/usr/libexec/InternetSharing.ipados14": [
      "VM networking stack"
    ],
    "var/jb/usr/libexec/InternetSharing.ipados15": [
      "VM networking stack"
    ],
    "var/jb/usr/libexec/InternetSharing.ipados16": [
      "VM networking stack"
    ],
    "var/jb/usr/share/VirtualMac/trustcache.txt": [
      "Apple Hypervisor framework",
      "Apple Virtualization framework",
      "SpringBoard keyboard passthrough tweak",
      "VM networking stack",
      "Virtualization XPC service",
      "paravirtualized graphics stack",
      "privileged installer launcher"
    ],
    "var/root/VirtualMac/bootstrap-common/usr/lib/TweakInject/VZKeyboardPassthrough.dylib": [
      "SpringBoard keyboard passthrough tweak"
    ],
    "var/root/VirtualMac/bootstrap-rootful/usr/libexec/VirtualMac/InternetSharing.ipados14": [
      "VM networking stack"
    ],
    "var/root/VirtualMac/install/VZHostCompat.dylib": [
      "Virtualization XPC service",
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/install/install-launcher": [
      "privileged installer launcher",
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/install/install-macos": [
      "Apple Hypervisor framework",
      "Apple Virtualization framework",
      "Virtualization XPC service",
      "paravirtualized graphics stack",
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/install/start-install.sh": [
      "privileged installer launcher"
    ],
    "var/root/VirtualMac/payload/Compatibility/iPadOS14/Hypervisor": [
      "Apple Hypervisor framework",
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Compatibility/iPadOS14/IOKit15Compat.dylib": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Compatibility/iPadOS14/LibSystemCompat.dylib": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Compatibility/iPadOS14/ParavirtualizedGraphics": [
      "paravirtualized graphics stack"
    ],
    "var/root/VirtualMac/payload/Compatibility/iPadOS14/Virtualization": [
      "Apple Hypervisor framework",
      "Apple Virtualization framework",
      "VM networking stack",
      "Virtualization XPC service",
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Compatibility/iPadOS14/vmnet": [
      "VM networking stack"
    ],
    "var/root/VirtualMac/payload/Compatibility/iPadOS15/Hypervisor": [
      "Apple Hypervisor framework"
    ],
    "var/root/VirtualMac/payload/Compatibility/iPadOS15/ParavirtualizedGraphics": [
      "paravirtualized graphics stack"
    ],
    "var/root/VirtualMac/payload/Compatibility/iPadOS15/Virtualization": [
      "Apple Hypervisor framework",
      "Apple Virtualization framework",
      "VM networking stack",
      "Virtualization XPC service",
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Compatibility/iPadOS15Authenticated/Hypervisor": [
      "Apple Hypervisor framework"
    ],
    "var/root/VirtualMac/payload/Compatibility/iPadOS15Authenticated/ParavirtualizedGraphics": [
      "paravirtualized graphics stack"
    ],
    "var/root/VirtualMac/payload/Compatibility/iPadOS15Authenticated/Virtualization": [
      "Apple Hypervisor framework",
      "Apple Virtualization framework",
      "VM networking stack",
      "Virtualization XPC service",
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Frameworks/Hypervisor.framework/Versions/A/Hypervisor": [
      "Apple Hypervisor framework"
    ],
    "var/root/VirtualMac/payload/Frameworks/IOKit15Compat.dylib": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Frameworks/LaunchServicesCompat.dylib": [
      "Apple Hypervisor framework",
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Frameworks/LaunchServicesCompat.dylib.ipados14": [
      "Apple Hypervisor framework",
      "VM networking stack",
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Frameworks/LibSystem15Compat.dylib": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Frameworks/MetalCompat.dylib": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Frameworks/ParavirtualizedGraphics.framework/Versions/A/ParavirtualizedGraphics": [
      "paravirtualized graphics stack"
    ],
    "var/root/VirtualMac/payload/Frameworks/Virtualization.framework/Versions/A/Resources/Localizable.loctable": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Frameworks/Virtualization.framework/Versions/A/Virtualization": [
      "Apple Hypervisor framework",
      "Apple Virtualization framework",
      "VM networking stack",
      "Virtualization XPC service",
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Frameworks/vmnet.framework/vmnet": [
      "VM networking stack"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/CoreServicesCompat.dylib": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/CoreUtilsCompat.dylib": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/CrashReporterCompat.dylib": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/DiskImagesCompat.dylib": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/Foundation14Compat.dylib": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/IOKit14Compat.dylib": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/InstallationCompat.dylib": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/InstallationCompat.dylib.ipados14": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/InstallationCompat.dylib.ipados15": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/InstallationCompat.dylib.ipados16": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/MobileDevice.framework/Versions/A/MobileDevice": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/MobileDevice.framework/Versions/A/MobileDevice.ipados14": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/MobileDevice.framework/Versions/A/MobileDevice.ipados15": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/MobileDevice.framework/Versions/A/MobileDevice.ipados15-auth": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/MobileDevice.framework/Versions/A/MobileDevice.ipados16": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/MobileDevice.framework/Versions/A/Resources/usbmuxd": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/SecurityCompat.dylib": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/Frameworks/SoftLinking14Compat.dylib": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/MacOS/com.apple.Virtualization.Installation": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/MacOS/com.apple.Virtualization.Installation.ipados14": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/MacOS/com.apple.Virtualization.Installation.ipados15": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/MacOS/com.apple.Virtualization.Installation.ipados15-auth": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/Installation.xpc/Contents/MacOS/com.apple.Virtualization.Installation.ipados16": [
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/VirtualMachine.xpc/Contents/Info.plist": [
      "Virtualization XPC service"
    ],
    "var/root/VirtualMac/payload/VirtualMachine.xpc/Contents/MacOS/com.apple.Virtualization.VirtualMachine": [
      "Apple Hypervisor framework",
      "Apple Virtualization framework",
      "VM networking stack",
      "Virtualization XPC service",
      "paravirtualized graphics stack",
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/VirtualMachine.xpc/Contents/MacOS/com.apple.Virtualization.VirtualMachine.ipados14": [
      "Apple Hypervisor framework",
      "Apple Virtualization framework",
      "VM networking stack",
      "Virtualization XPC service",
      "paravirtualized graphics stack",
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/VirtualMachine.xpc/Contents/MacOS/com.apple.Virtualization.VirtualMachine.ipados15": [
      "Apple Hypervisor framework",
      "Apple Virtualization framework",
      "VM networking stack",
      "Virtualization XPC service",
      "paravirtualized graphics stack",
      "virtualization entitlement"
    ],
    "var/root/VirtualMac/payload/VirtualMachine.xpc/Contents/MacOS/com.apple.Virtualization.VirtualMachine.ipados16": [
      "Apple Hypervisor framework",
      "Apple Virtualization framework",
      "VM networking stack",
      "Virtualization XPC service",
      "paravirtualized graphics stack",
      "virtualization entitlement"
    ]
  },
  "target": {
    "chip": "A9",
    "ios": "16.7.11"
  },
  "version": "2:1.2+565.799fc13aff"
}
```
