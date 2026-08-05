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
GUARD_SOURCE = (ROOT / 'public' / 'direct_guard.py').read_text()


def ar_member(name: str, payload: bytes) -> bytes:
    header = (
        (name + '/').encode()[:16].ljust(16, b' ')
        + b'0'.ljust(12, b' ')
        + b'0'.ljust(6, b' ')
        + b'0'.ljust(6, b' ')
        + b'100644'.ljust(8, b' ')
        + str(len(payload)).encode().ljust(10, b' ')
        + b'`\n'
    )
    return header + payload + (b'\n' if len(payload) & 1 else b'')


def make_deb(risky=False):
    plist = plistlib.dumps({
        'CFBundleIdentifier': 'com.example.guard',
        'CFBundleExecutable': 'GuardFixture',
        'CFBundlePackageType': 'APPL',
        'MinimumOSVersion': '16.0',
    })
    executable = struct.pack('<IiiIIIII', 0xFEEDFACF, 0x0100000C, 0, 2, 0, 0, 0, 0)
    if risky:
        executable += b'/var/root/VirtualMac/payload/Frameworks/Virtualization.framework com.apple.private.hypervisor'
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode='w:gz') as archive:
        files = [
            ('Applications/GuardFixture.app/Info.plist', plist, 0o644),
            ('Applications/GuardFixture.app/GuardFixture', executable, 0o755),
        ]
        if risky:
            files += [
                ('var/jb/Library/LaunchDaemons/com.example.guard.plist', b'<plist/>', 0o644),
                ('var/root/GuardFixture/helper', executable, 0o755),
            ]
        for name, data, mode in files:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = mode
            archive.addfile(info, io.BytesIO(data))
    return b'!<arch>\n' + ar_member('debian-binary', b'2.0\n') + ar_member('data.tar.gz', payload.getvalue())


def load_guard(original=None):
    namespace = {'__name__': 'direct_guard_test'}
    if original is not None:
        namespace['convert_deb'] = original
    exec(compile(GUARD_SOURCE, 'direct_guard.py', 'exec'), namespace)
    return namespace


class DirectGuardTests(unittest.TestCase):
    def test_clean_app_is_allowed_and_minimum_os_is_not_downgraded(self):
        calls = []
        def original(input_path, output_path, options_json):
            calls.append(json.loads(options_json))
            Path(output_path).write_bytes(b'zip')
            return json.dumps({'verdict': 'packaged'})
        guard = load_guard(original)
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'clean.deb'
            output = Path(temp) / 'result.zip'
            source.write_bytes(make_deb(False))
            result = json.loads(guard['convert_deb'](str(source), str(output), json.dumps({'minimumIos': '15.0'})))
        self.assertEqual(result['verdict'], 'packaged')
        self.assertEqual(calls[0]['minimumIos'], '16.0')

    def test_risky_package_is_blocked_before_direct_ipa(self):
        guard = load_guard(lambda *_: self.fail('original converter must not run'))
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'risky.deb'
            output = Path(temp) / 'result.zip'
            source.write_bytes(make_deb(True))
            result = json.loads(guard['convert_deb'](str(source), str(output), json.dumps({'sourceName': 'risky.deb', 'minimumIos': '15.0'})))
            with zipfile.ZipFile(output) as archive:
                report = json.loads(archive.read('compatibility-report.json'))
        self.assertEqual(result['verdict'], 'blocked')
        self.assertTrue(any('launch daemon' in item for item in result['blockers']))
        self.assertTrue(any('restricted runtime dependencies' in item for item in result['blockers']))
        self.assertEqual(report['schemaVersion'], 3)
        self.assertEqual(report['analysis']['wholePackageAudit']['originalMinimumOSVersion'], '16.0')


if __name__ == '__main__':
    unittest.main()
