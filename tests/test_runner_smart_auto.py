import importlib.util
import io
import plistlib
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

    def test_validates_original_unsigned_ipa(self):
        result = MODULE.validate_ipa_bytes(make_ipa())
        self.assertEqual(result['bundleIdentifier'], 'com.example.runner')
        self.assertEqual(result['executable'], 'Runner')

    def test_rejects_generic_compatibility_host(self):
        with self.assertRaisesRegex(RuntimeError, 'generic compatibility host'):
            MODULE.validate_ipa_bytes(make_ipa('DebToIPACompatibilityHost'))

    def test_only_direct_packaged_result_is_success(self):
        ipa = {'name': 'Runner.ipa'}
        self.assertTrue(MODULE.direct_conversion_succeeded(
            'packaged', {'verdict': 'packaged'}, [ipa]
        ))
        self.assertFalse(MODULE.direct_conversion_succeeded(
            'port-project', {'verdict': 'host-packaged'}, [ipa]
        ))
        self.assertFalse(MODULE.direct_conversion_succeeded(
            'packaged', {'verdict': 'packaged'}, []
        ))


if __name__ == '__main__':
    unittest.main()
