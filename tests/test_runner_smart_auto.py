import importlib.util
import io
import plistlib
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'runner_smart_auto', ROOT / 'scripts' / 'runner_smart_auto.py'
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def make_ipa(executable_name: str = 'Runner') -> bytes:
    plist = plistlib.dumps({
        'CFBundleIdentifier': 'com.example.runner',
        'CFBundleDisplayName': 'Runner',
        'CFBundleExecutable': executable_name,
        'MinimumOSVersion': '15.0',
    }, fmt=plistlib.FMT_BINARY)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('Payload/Runner.app/Info.plist', plist)
        archive.writestr(
            f'Payload/Runner.app/{executable_name}',
            b'\xcf\xfa\xed\xfe' + b'\0' * 64,
        )
    return buffer.getvalue()


class RunnerSmartAutoTests(unittest.TestCase):
    def test_loads_direct_and_port_analysis_paths(self):
        engine = MODULE.load_engine()
        self.assertTrue(callable(engine.get('convert_deb_with_port')))
        self.assertFalse(callable(engine.get('build_host_ipa_from_port_result')))

    def test_validates_original_unsigned_ipa_and_hashes_executable(self):
        result = MODULE.validate_ipa_bytes(make_ipa())
        self.assertEqual(result['bundleIdentifier'], 'com.example.runner')
        self.assertEqual(result['executable'], 'Runner')
        self.assertEqual(len(result['executableSha256']), 64)

    def test_rejects_generic_compatibility_host(self):
        with self.assertRaisesRegex(RuntimeError, 'generic compatibility host'):
            MODULE.validate_ipa_bytes(make_ipa('DebToIPACompatibilityHost'))

    def test_discovers_real_top_level_app(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / 'var' / 'jb' / 'Applications' / 'Real.app'
            app.mkdir(parents=True)
            (app / 'Info.plist').write_bytes(plistlib.dumps({
                'CFBundleIdentifier': 'com.example.real',
                'CFBundleExecutable': 'Real',
                'CFBundleName': 'Real',
            }))
            (app / 'Real').write_bytes(b'\xcf\xfa\xed\xfe' + b'\0' * 64)
            self.assertEqual(MODULE.find_original_apps(root), [app])

    def test_ignores_app_without_original_binary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / 'Applications' / 'Fake.app'
            app.mkdir(parents=True)
            (app / 'Info.plist').write_bytes(plistlib.dumps({
                'CFBundleExecutable': 'Missing',
            }))
            self.assertEqual(MODULE.find_original_apps(root), [])

    def test_classifies_three_honest_results(self):
        self.assertEqual(
            MODULE.classify_result(True, []),
            ('packaged', 'real-ipa', True, 0),
        )
        self.assertEqual(
            MODULE.classify_result(True, ['private entitlement']),
            ('original-packaged-blocked', 'original-blocked', False, 3),
        )
        self.assertEqual(
            MODULE.classify_result(False, ['no app']),
            ('blocked-no-standalone-app', 'unsupported', False, 2),
        )


if __name__ == '__main__':
    unittest.main()
