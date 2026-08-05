import importlib.util
import io
import json
import plistlib
import struct
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location('browser_converter', ROOT / 'public' / 'converter.py')
browser_converter = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(browser_converter)


def ar_member(name: str, payload: bytes) -> bytes:
    encoded_name = (name + '/').encode('ascii')[:16].ljust(16, b' ')
    header = (
        encoded_name
        + b'0'.ljust(12, b' ')
        + b'0'.ljust(6, b' ')
        + b'0'.ljust(6, b' ')
        + b'100644'.ljust(8, b' ')
        + str(len(payload)).encode('ascii').ljust(10, b' ')
        + b'`\n'
    )
    return header + payload + (b'\n' if len(payload) % 2 else b'')


def make_deb() -> bytes:
    plist = plistlib.dumps({
        'CFBundleIdentifier': 'com.example.fixture',
        'CFBundleExecutable': 'Fixture',
        'CFBundleDisplayName': 'Fixture',
        'CFBundleName': 'Fixture',
        'CFBundlePackageType': 'APPL',
        'UIDeviceFamily': [2],
        'MinimumOSVersion': '13.0',
    })
    executable = struct.pack('<IiiIIIII', 0xFEEDFACF, 0x0100000C, 0, 2, 0, 0, 0, 0)

    tar_bytes = io.BytesIO()
    with tarfile.open(fileobj=tar_bytes, mode='w:gz') as archive:
        for name, data, mode in (
            ('Applications/Fixture.app/Info.plist', plist, 0o644),
            ('Applications/Fixture.app/Fixture', executable, 0o755),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = mode
            archive.addfile(info, io.BytesIO(data))

    return (
        b'!<arch>\n'
        + ar_member('debian-binary', b'2.0\n')
        + ar_member('data.tar.gz', tar_bytes.getvalue())
    )


class BrowserConverterTests(unittest.TestCase):
    def test_zero_setup_browser_engine_packages_ipa(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'fixture.deb'
            result_zip = root / 'result.zip'
            source.write_bytes(make_deb())

            result = json.loads(browser_converter.convert_deb(
                str(source),
                str(result_zip),
                json.dumps({
                    'sourceName': 'fixture.deb',
                    'device': 'universal',
                    'minimumIos': '16.0',
                    'bundleId': 'com.example.converted',
                    'displayName': 'Converted Fixture',
                }),
            ))

            self.assertEqual(result['verdict'], 'packaged')
            with zipfile.ZipFile(result_zip) as outer:
                report = json.loads(outer.read('compatibility-report.json'))
                ipa_name = report['output']['name']
                ipa_bytes = outer.read(ipa_name)
            with zipfile.ZipFile(io.BytesIO(ipa_bytes)) as ipa:
                plist = plistlib.loads(ipa.read('Payload/Fixture.app/Info.plist'))
                self.assertIn('Payload/Fixture.app/Fixture', ipa.namelist())

            self.assertEqual(plist['CFBundleIdentifier'], 'com.example.converted')
            self.assertEqual(plist['CFBundleDisplayName'], 'Converted Fixture')
            self.assertEqual(plist['UIDeviceFamily'], [1, 2])
            self.assertEqual(plist['MinimumOSVersion'], '16.0')
            self.assertEqual(report['engine'], 'DebtoIPA private browser engine')


if __name__ == '__main__':
    unittest.main()
