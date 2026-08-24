import importlib.util
import io
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("virtualmac_profile", ROOT / "scripts" / "virtualmac_profile.py")
vm = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(vm)


def tar_bytes(files):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as archive:
        for name, data, mode in files:
            raw = data if isinstance(data, bytes) else data.encode()
            info = tarfile.TarInfo(name)
            info.size = len(raw)
            info.mode = mode
            archive.addfile(info, io.BytesIO(raw))
    return out.getvalue()


def ar_member(name, payload):
    encoded = (name + "/").encode().ljust(16, b" ")
    header = encoded + b"0".ljust(12) + b"0".ljust(6) + b"0".ljust(6) + b"100644".ljust(8) + str(len(payload)).encode().ljust(10) + b"`\n"
    return header + payload + (b"\n" if len(payload) & 1 else b"")


def make_virtualmac_deb(path):
    control = (
        "Package: com.mac.virtual\n"
        "Name: Virtual Mac\n"
        "Version: 1.2\n"
        "Architecture: all\n"
        "Depends: firmware (>= 14.0), firmware (<< 16.4), ellekit | org.coolstar.libhooker\n"
    )
    control_tar = tar_bytes([("./control", control, 0o644)])
    binary = b"xxxxVirtualization.frameworkxxxxHypervisor.frameworkxxxxinstall-launcherxxxx"
    data_tar = tar_bytes([
        ("./var/jb/Applications/VirtualMac.app/VirtualMac", binary, 0o755),
        ("./var/root/VirtualMac/install/install-launcher", b"launcher", 0o4755),
        ("./var/jb/Library/LaunchDaemons/com.apple.NetworkSharing.plist", b"plist", 0o644),
        ("./var/root/VirtualMac/bootstrap-common/usr/lib/TweakInject/VZKeyboardPassthrough.dylib", b"VZKeyboardPassthrough", 0o755),
    ])
    path.write_bytes(b"!<arch>\n" + ar_member("debian-binary", b"2.0\n") + ar_member("control.tar.gz", control_tar) + ar_member("data.tar.gz", data_tar))


class VirtualMacProfileTests(unittest.TestCase):
    def test_control_parser_handles_continuations(self):
        parsed = vm._parse_control("Package: test\nDescription: first\n second\n")
        self.assertEqual(parsed["Package"], "test")
        self.assertEqual(parsed["Description"], "first\nsecond")

    def test_supported_target(self):
        result = vm.evaluate_target(is_virtualmac=True, ios="16.3.1", chip="M1")
        self.assertEqual(result["targetStatus"], "upstream-compatible")
        self.assertTrue(result["upstreamCompatible"])
        self.assertFalse(result["stockIpaSupported"])
        self.assertEqual(result["recommendedArtifact"], "jailbreak-deb")

    def test_newer_ios_is_not_falsely_marked_supported(self):
        result = vm.evaluate_target(is_virtualmac=True, ios="16.7.11", chip="M1")
        self.assertEqual(result["targetStatus"], "incompatible")
        self.assertFalse(result["upstreamCompatible"])
        self.assertTrue(any("16.4 or newer" in reason for reason in result["reasons"]))

    def test_old_non_apple_silicon_ipad_is_not_falsely_marked_supported(self):
        result = vm.evaluate_target(is_virtualmac=True, ios="16.3.1", chip="A9")
        self.assertEqual(result["targetStatus"], "incompatible")
        self.assertFalse(result["upstreamCompatible"])
        self.assertTrue(any("outside upstream" in reason for reason in result["reasons"]))

    def test_virtualmac_deb_detection(self):
        with tempfile.TemporaryDirectory() as td:
            deb = Path(td) / "VirtualMac_1.2.deb"
            make_virtualmac_deb(deb)
            profile = vm.inspect_deb(deb)
        self.assertTrue(profile["isVirtualMac"])
        self.assertEqual(profile["package"], "com.mac.virtual")
        self.assertIn("var/root/VirtualMac", profile["packagePaths"])
        self.assertIn("var/jb/Applications/VirtualMac.app", profile["packagePaths"])
        flattened = {item for values in profile["runtimeMarkers"].values() for item in values}
        self.assertIn("Apple Virtualization framework", flattened)
        self.assertIn("Apple Hypervisor framework", flattened)

    def test_upstream_source_tree_detection(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for relative in (
                "vz/uncache.py",
                "vz/stamp_ios.py",
                "vz/host/vmmhook.m",
                "vz/host/installation_usb_shim.m",
                "scripts/build-ipad-deb.sh",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("Virtualization.framework Hypervisor.framework", encoding="utf-8")
            profile = vm.inspect_source(root)
        self.assertTrue(profile["isVirtualMac"])
        self.assertGreaterEqual(len(profile["sourceMarkers"]), 3)


if __name__ == "__main__":
    unittest.main()
