import importlib.util
import plistlib
import tempfile
import struct
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location('converter', Path(__file__).parents[1] / 'scripts' / 'convert_deb.py')
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


if __name__ == '__main__':
    unittest.main()
