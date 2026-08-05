import importlib.util
import io
import plistlib
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('runner_smart_auto', ROOT / 'scripts' / 'runner_smart_auto.py')
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class RunnerSmartAutoTests(unittest.TestCase):
    def test_loads_all_runner_paths(self):
        engine = MODULE.load_engine()
        self.assertTrue(callable(engine.get('convert_deb_with_port')))
        self.assertTrue(callable(engine.get('build_host_ipa_from_port_result')))

    def test_validates_minimal_unsigned_ipa(self):
        plist = plistlib.dumps({
            'CFBundleIdentifier': 'com.example.runner',
            'CFBundleDisplayName': 'Runner',
            'CFBundleExecutable': 'Runner',
            'MinimumOSVersion': '15.0',
        }, fmt=plistlib.FMT_BINARY)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('Payload/Runner.app/Info.plist', plist)
            archive.writestr('Payload/Runner.app/Runner', b'\xcf\xfa\xed\xfe' + b'\0' * 64)
        result = MODULE.validate_ipa_bytes(buffer.getvalue())
        self.assertEqual(result['bundleIdentifier'], 'com.example.runner')
        self.assertEqual(result['executable'], 'Runner')


if __name__ == '__main__':
    unittest.main()
