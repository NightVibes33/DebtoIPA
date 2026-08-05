import importlib.util
import io
import json
import plistlib
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location('host_mode', ROOT / 'public' / 'host_mode.py')
host_mode = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(host_mode)


class HostModeTests(unittest.TestCase):
    def make_template(self, path: Path) -> None:
        plist = plistlib.dumps({
            'CFBundleIdentifier': 'com.template.host',
            'CFBundleDisplayName': 'Compatibility Host',
            'CFBundleName': 'Compatibility Host',
            'CFBundleExecutable': 'DebToIPACompatibilityHost',
            'MinimumOSVersion': '15.0',
            'UIDeviceFamily': [1, 2],
        }, fmt=plistlib.FMT_BINARY)
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('Payload/DebToIPACompatibilityHost.app/Info.plist', plist)
            archive.writestr('Payload/DebToIPACompatibilityHost.app/DebToIPACompatibilityHost', b'\xcf\xfa\xed\xfe' + b'\0' * 64)
            archive.writestr('Payload/DebToIPACompatibilityHost.app/_CodeSignature/CodeResources', b'stale')

    def make_port_result(self, path: Path) -> None:
        manifest = {
            'schemaVersion': 1,
            'name': 'Example Port',
            'bundleIdentifier': 'com.example.port',
            'minimumIOS': '16.0',
            'virtualPathMappings': {'/var/mobile': 'Library/Application Support/DebToIPAPort/var/mobile'},
            'capabilityPlan': {
                'translatable': ['Container-backed files are supported.'],
                'requiresRedesign': ['A launch daemon needs a BackgroundTasks replacement.'],
                'notEmulatable': [],
            },
        }
        report = {
            'schemaVersion': 3,
            'verdict': 'port-project',
            'source': {'name': 'example.deb'},
            'blockers': ['The original executable requires a jailbreak helper.'],
            'warnings': [],
        }
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('compatibility-report.json', json.dumps(report))
            archive.writestr('Example-DebToIPA-Port/PortManifest.json', json.dumps(manifest))
            archive.writestr('Example-DebToIPA-Port/PortPayload/var/mobile/config.json', b'{"enabled":true}')
            archive.writestr('Example-DebToIPA-Port/PortPayload/var/root/native-helper', b'\xcf\xfa\xed\xfe' + b'\0' * 20)
            archive.writestr('Example-DebToIPA-Port/README.md', b'Port project')

    def test_builds_launchable_host_and_filters_nested_native_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            template = root / 'template.ipa'
            result_zip = root / 'result.zip'
            self.make_template(template)
            self.make_port_result(result_zip)

            result = json.loads(host_mode.build_host_ipa_from_port_result(
                str(result_zip),
                str(template),
                json.dumps({'sourceName': 'example.deb', 'device': 'universal'}),
            ))
            self.assertEqual(result['verdict'], 'host-packaged')

            with zipfile.ZipFile(result_zip) as outer:
                report = json.loads(outer.read('compatibility-report.json'))
                ipa_bytes = outer.read(report['output']['name'])
                self.assertIn('Example-DebToIPA-Port/README.md', outer.namelist())

            self.assertTrue(report['output']['launchable'])
            self.assertFalse(report['output']['featureComplete'])
            self.assertFalse(report['output']['originalBinaryExecuted'])

            with zipfile.ZipFile(io.BytesIO(ipa_bytes)) as ipa:
                names = ipa.namelist()
                root_path = 'Payload/DebToIPACompatibilityHost.app/DebToIPA'
                self.assertIn(root_path + '/PortPayload/var/mobile/config.json', names)
                self.assertNotIn(root_path + '/PortPayload/var/root/native-helper', names)
                self.assertNotIn('Payload/DebToIPACompatibilityHost.app/_CodeSignature/CodeResources', names)
                plist = plistlib.loads(ipa.read('Payload/DebToIPACompatibilityHost.app/Info.plist'))
                self.assertEqual(plist['CFBundleIdentifier'], 'com.example.port')
                self.assertEqual(plist['MinimumOSVersion'], '16.0')


if __name__ == '__main__':
    unittest.main()
