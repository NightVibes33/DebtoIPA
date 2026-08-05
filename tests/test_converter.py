import importlib.util
import json
import plistlib
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location('converter', ROOT / 'scripts' / 'convert_deb.py')
converter = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(converter)


class ConverterTests(unittest.TestCase):
    def test_update_plist_to_universal(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'Info.plist'
            with path.open('wb') as handle:
                plistlib.dump({
                    'CFBundleIdentifier': 'com.old.app',
                    'CFBundleExecutable': 'App',
                    'CFBundleDisplayName': 'Old',
                    'UIDeviceFamily': [2],
                    'MinimumOSVersion': '12.0',
                }, handle)
            before, after = converter.update_plist(path, 'universal', '16.0', 'com.new.app', 'New App')
            self.assertEqual(before['UIDeviceFamily'], [2])
            self.assertEqual(after['UIDeviceFamily'], [1, 2])
            self.assertEqual(after['CFBundleIdentifier'], 'com.new.app')
            self.assertEqual(after['MinimumOSVersion'], '16.0')

    def test_find_apps_ignores_nested_apps(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            outer = root / 'Applications' / 'Outer.app'
            nested = outer / 'PlugIns' / 'Nested.app'
            nested.mkdir(parents=True)
            outer.mkdir(parents=True, exist_ok=True)
            (outer / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable': 'Outer'}))
            (nested / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable': 'Nested'}))
            apps = converter.find_apps(root)
            self.assertEqual(apps, [outer])

    def test_macho_dylib_parser(self):
        name = b'/usr/lib/libSystem.B.dylib\0'
        cmdsize = 24 + len(name)
        cmdsize = (cmdsize + 7) & ~7
        command = struct.pack('<IIIIII', 0xC, cmdsize, 24, 0, 0, 0) + name
        command += b'\0' * (cmdsize - len(command))
        header = struct.pack('<IiiIIIII', 0xFEEDFACF, 0x0100000C, 0, 2, 1, cmdsize, 0, 0)
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / 'App'
            binary.write_bytes(header + command)
            self.assertEqual(converter.macho_linked_libraries(binary), ['/usr/lib/libSystem.B.dylib'])

    def test_detects_tweak_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            marker = root / 'Library' / 'MobileSubstrate' / 'DynamicLibraries'
            marker.mkdir(parents=True)
            (marker / 'Test.dylib').write_bytes(b'x')
            self.assertIn('Library/MobileSubstrate/DynamicLibraries', converter.package_markers(root))

    def test_full_deb_to_ipa_packaging(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package_root = root / 'package'
            app = package_root / 'Applications' / 'Fixture.app'
            control = package_root / 'DEBIAN'
            app.mkdir(parents=True)
            control.mkdir(parents=True)

            (control / 'control').write_text(
                'Package: com.example.fixture\n'
                'Name: Fixture\n'
                'Version: 1.0\n'
                'Architecture: iphoneos-arm64\n'
                'Description: DebtoIPA integration fixture\n'
                'Maintainer: DebtoIPA\n',
                encoding='utf-8',
            )
            (app / 'Info.plist').write_bytes(plistlib.dumps({
                'CFBundleIdentifier': 'com.example.fixture',
                'CFBundleExecutable': 'Fixture',
                'CFBundleDisplayName': 'Fixture',
                'CFBundleName': 'Fixture',
                'CFBundlePackageType': 'APPL',
                'UIDeviceFamily': [2],
                'MinimumOSVersion': '13.0',
            }))
            executable = app / 'Fixture'
            executable.write_bytes(struct.pack('<IiiIIIII', 0xFEEDFACF, 0x0100000C, 0, 2, 0, 0, 0, 0))
            executable.chmod(0o755)

            deb = root / 'fixture.deb'
            ipa = root / 'fixture.ipa'
            report_path = root / 'report.json'
            subprocess.run(['dpkg-deb', '--build', str(package_root), str(deb)], check=True, capture_output=True, text=True)
            subprocess.run([
                sys.executable,
                str(ROOT / 'scripts' / 'convert_deb.py'),
                '--deb', str(deb),
                '--output', str(ipa),
                '--report', str(report_path),
                '--device', 'universal',
                '--minimum-ios', '16.0',
                '--bundle-id', 'com.example.converted',
                '--display-name', 'Converted Fixture',
            ], check=True)

            report = json.loads(report_path.read_text(encoding='utf-8'))
            self.assertEqual(report['verdict'], 'packaged')
            self.assertTrue(ipa.is_file())
            with zipfile.ZipFile(ipa) as archive:
                names = set(archive.namelist())
                self.assertIn('Payload/Fixture.app/Info.plist', names)
                self.assertIn('Payload/Fixture.app/Fixture', names)
                converted_plist = plistlib.loads(archive.read('Payload/Fixture.app/Info.plist'))
            self.assertEqual(converted_plist['CFBundleIdentifier'], 'com.example.converted')
            self.assertEqual(converted_plist['CFBundleDisplayName'], 'Converted Fixture')
            self.assertEqual(converted_plist['UIDeviceFamily'], [1, 2])
            self.assertEqual(converted_plist['MinimumOSVersion'], '16.0')
            self.assertEqual(converted_plist['CFBundleSupportedPlatforms'], ['iPhoneOS'])
            self.assertTrue(converted_plist['LSRequiresIPhoneOS'])


if __name__ == '__main__':
    unittest.main()
