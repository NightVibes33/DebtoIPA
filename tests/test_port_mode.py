import base64,gzip,io,json,plistlib,struct,tarfile,tempfile,unittest,zipfile
from pathlib import Path

ROOT=Path(__file__).parents[1]
NS={}
exec((ROOT/'public/converter.py').read_text(),NS)
port_source=gzip.decompress(base64.b64decode((ROOT/'public/port_mode.py.gz.b64').read_text().strip())).decode()
exec(port_source,NS)

def ar_member(name,payload):
    header=(name+'/').encode()[:16].ljust(16,b' ')+b'0'.ljust(12,b' ')+b'0'.ljust(6,b' ')+b'0'.ljust(6,b' ')+b'100644'.ljust(8,b' ')+str(len(payload)).encode().ljust(10,b' ')+b'`\n'
    return header+payload+(b'\n' if len(payload)%2 else b'')

def fixture(jailbreak=False):
    plist=plistlib.dumps({'CFBundleIdentifier':'com.example.fixture','CFBundleExecutable':'Fixture','CFBundleDisplayName':'Fixture','CFBundleName':'Fixture','CFBundlePackageType':'APPL','UIDeviceFamily':[1,2],'MinimumOSVersion':'15.0'})
    executable=struct.pack('<IiiIIIII',0xFEEDFACF,0x0100000C,0,2,0,0,0,0)+(b'/var/jb/Library/MobileSubstrate/DynamicLibraries/Fixture.dylib\0' if jailbreak else b'')
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w:gz') as archive:
        entries=[('Applications/Fixture.app/Info.plist',plist,0o644),('Applications/Fixture.app/Fixture',executable,0o755)]
        if jailbreak: entries.append(('Library/LaunchDaemons/com.example.fixture.plist',plistlib.dumps({'Label':'com.example.fixture','Program':'/var/jb/usr/bin/helper','RunAtLoad':True}),0o644))
        for name,data,mode in entries:
            info=tarfile.TarInfo(name);info.size=len(data);info.mode=mode;archive.addfile(info,io.BytesIO(data))
    return b'!<arch>\n'+ar_member('debian-binary',b'2.0\n')+ar_member('data.tar.gz',stream.getvalue())

class PortModeTests(unittest.TestCase):
    def convert(self,jailbreak,mode='auto'):
        temp=tempfile.TemporaryDirectory();root=Path(temp.name);source=root/'fixture.deb';output=root/'result.zip';source.write_bytes(fixture(jailbreak));result=json.loads(NS['convert_deb_with_port'](str(source),str(output),json.dumps({'sourceName':'fixture.deb','mode':mode,'device':'universal','minimumIos':'16.0'})));return temp,output,result
    def test_auto_keeps_direct_ipa_for_compatible_package(self):
        temp,output,result=self.convert(False);self.addCleanup(temp.cleanup);self.assertEqual(result['verdict'],'packaged');self.assertEqual(result['resolvedMode'],'direct')
    def test_auto_generates_buildable_port_project(self):
        temp,output,result=self.convert(True);self.addCleanup(temp.cleanup);self.assertEqual(result['verdict'],'port-project');self.assertEqual(result['resolvedMode'],'port')
        with zipfile.ZipFile(output) as archive:
            report=json.loads(archive.read('compatibility-report.json'));prefix=report['output']['name'];names=archive.namelist();self.assertIn(prefix+'/PortManifest.json',names);self.assertIn(prefix+'/Sources/DebToIPAPortKit.swift',names);self.assertIn(prefix+'/.github/workflows/build-port.yml',names);self.assertTrue(report['output']['buildable'])
    def test_direct_mode_still_blocks_jailbreak_binary(self):
        temp,output,result=self.convert(True,'direct');self.addCleanup(temp.cleanup);self.assertEqual(result['verdict'],'blocked');self.assertEqual(result['resolvedMode'],'direct')

if __name__=='__main__':unittest.main()
