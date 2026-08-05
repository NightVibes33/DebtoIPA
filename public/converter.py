import hashlib, io, json, os, plistlib, shutil, stat, struct, tarfile, tempfile, zipfile
from pathlib import Path

ARM64 = 0x0100000C
BLOCKED = (b'/Library/MobileSubstrate', b'/var/jb/', b'CydiaSubstrate', b'SubstrateLoader', b'libhooker', b'ElleKit', b'Substitute', b'RocketBootstrap')
MARKERS = ('Library/MobileSubstrate/DynamicLibraries', 'var/jb/Library/MobileSubstrate/DynamicLibraries', 'Library/PreferenceBundles', 'var/jb/Library/PreferenceBundles', 'Library/LaunchDaemons', 'var/jb/Library/LaunchDaemons')
ALLOWED = ('/System/Library/', '/usr/lib/', '@rpath/', '@loader_path/', '@executable_path/')
DYLIB_CMDS = {0xC, 0x80000018, 0x8000001F, 0x20, 0x80000023}


def ar_members(data):
    if not data.startswith(b'!<arch>\n'):
        raise RuntimeError('Input is not a valid Debian archive.')
    out, pos, long_names = [], 8, b''
    while pos + 60 <= len(data):
        h, pos = data[pos:pos + 60], pos + 60
        if h[58:60] != b'`\n':
            raise RuntimeError('Malformed Debian archive member.')
        name = h[:16].decode('utf-8', 'replace').strip()
        try: size = int(h[48:58].decode().strip() or '0')
        except ValueError: raise RuntimeError('Invalid Debian archive size.')
        if pos + size > len(data): raise RuntimeError('Truncated Debian archive.')
        payload, pos = data[pos:pos + size], pos + size + (size & 1)
        if name == '//': long_names = payload; continue
        if name.startswith('#1/'):
            n = int(name[3:]); name, payload = payload[:n].decode('utf-8', 'replace').rstrip('\0'), payload[n:]
        elif name.startswith('/') and name[1:].isdigit() and long_names:
            start = int(name[1:]); end = long_names.find(b'/\n', start)
            name = long_names[start:end if end >= 0 else len(long_names)].decode('utf-8', 'replace')
        else: name = name.rstrip('/')
        if name: out.append((name, payload))
    return out


def extract_tar(payload, dest):
    with tarfile.open(fileobj=io.BytesIO(payload), mode='r:*') as tf:
        base = dest.resolve()
        for member in tf.getmembers():
            target = (dest / member.name).resolve()
            if target != base and base not in target.parents:
                raise RuntimeError(f'Unsafe path in payload: {member.name}')
        tf.extractall(dest, filter='data')


def find_apps(root):
    apps = []
    for p in root.rglob('*.app'):
        if p.is_dir() and (p / 'Info.plist').is_file() and not any(x.suffix in {'.app', '.appex'} for x in p.parents if x != root):
            apps.append(p)
    def size(p):
        total = 0
        for f in p.rglob('*'):
            try:
                if f.is_file() and not f.is_symlink(): total += f.stat().st_size
            except OSError: pass
        return total
    return sorted(apps, key=size, reverse=True)


def archs(data):
    thin = {b'\xcf\xfa\xed\xfe':'<', b'\xfe\xed\xfa\xcf':'>', b'\xce\xfa\xed\xfe':'<', b'\xfe\xed\xfa\xce':'>'}
    if data[:4] in thin and len(data) >= 8: return [struct.unpack_from(thin[data[:4]] + 'I', data, 4)[0]]
    fat = {b'\xca\xfe\xba\xbe':('>',20), b'\xbe\xba\xfe\xca':('<',20), b'\xca\xfe\xba\xbf':('>',32), b'\xbf\xba\xfe\xca':('<',32)}
    if data[:4] not in fat or len(data) < 8: return []
    endian, stride = fat[data[:4]]; count = struct.unpack_from(endian + 'I', data, 4)[0]
    return [struct.unpack_from(endian + 'I', data, 8 + i * stride)[0] for i in range(min(count, 64)) if 8 + (i + 1) * stride <= len(data)]


def macho_slice_libs(data, offset=0, limit=None):
    limit = len(data) if limit is None else limit
    fmt = {b'\xcf\xfa\xed\xfe':('<',32), b'\xfe\xed\xfa\xcf':('>',32), b'\xce\xfa\xed\xfe':('<',28), b'\xfe\xed\xfa\xce':('>',28)}
    if data[offset:offset + 4] not in fmt: return []
    endian, header = fmt[data[offset:offset + 4]]
    if offset + header > limit: return []
    count, pos, libs = struct.unpack_from(endian + 'I', data, offset + 16)[0], offset + header, []
    for _ in range(min(count, 8192)):
        if pos + 8 > limit: break
        cmd, size = struct.unpack_from(endian + 'II', data, pos)
        if size < 8 or pos + size > limit: break
        if cmd in DYLIB_CMDS and size >= 24:
            start = pos + struct.unpack_from(endian + 'I', data, pos + 8)[0]
            if pos <= start < pos + size:
                name = data[start:pos + size].split(b'\0', 1)[0].decode('utf-8', 'replace').strip()
                if name: libs.append(name)
        pos += size
    return libs


def linked_libs(data):
    fat = {b'\xca\xfe\xba\xbe':('>',False), b'\xbe\xba\xfe\xca':('<',False), b'\xca\xfe\xba\xbf':('>',True), b'\xbf\xba\xfe\xca':('<',True)}
    if data[:4] not in fat: return sorted(set(macho_slice_libs(data)))
    endian, wide = fat[data[:4]]; count, pos, stride, libs = struct.unpack_from(endian + 'I', data, 4)[0], 8, 32 if wide else 20, []
    for _ in range(min(count, 64)):
        if pos + stride > len(data): break
        if wide: _, _, off, size, _, _ = struct.unpack_from(endian + 'IIQQII', data, pos)
        else: _, _, off, size, _ = struct.unpack_from(endian + 'IIIII', data, pos)
        if off + size <= len(data): libs += macho_slice_libs(data, int(off), int(off + size))
        pos += stride
    return sorted(set(libs))


def inspect(exe):
    data, blockers, warnings = exe.read_bytes(), [], []
    architectures = archs(data)
    if not architectures: blockers.append('The app executable is not a Mach-O iOS binary.')
    elif ARM64 not in architectures: blockers.append('The app executable has no ARM64 slice for modern stock iOS.')
    refs = [x.decode('utf-8', 'ignore') for x in BLOCKED if x in data]
    if refs: blockers.append('The executable references jailbreak-only loaders or paths: ' + ', '.join(refs))
    libs = linked_libs(data); unsupported = [x for x in libs if not x.startswith(ALLOWED)]
    if unsupported: blockers.append('The executable links libraries unavailable on stock iOS: ' + ', '.join(unsupported))
    if not libs: warnings.append('No linked libraries were discovered; architecture and jailbreak-string checks still completed.')
    return blockers, warnings, {'architectures':['arm64' if x == ARM64 else hex(x) for x in architectures], 'linkedLibraries':libs, 'blockedReferences':refs}


def rewrite_plist(path, options):
    with path.open('rb') as f: p = plistlib.load(f)
    if not isinstance(p, dict): raise RuntimeError('Info.plist is invalid.')
    keys = ('CFBundleIdentifier','CFBundleDisplayName','CFBundleName','UIDeviceFamily','MinimumOSVersion','CFBundleExecutable')
    before = {k:p.get(k) for k in keys}
    if options.get('bundleId'): p['CFBundleIdentifier'] = options['bundleId']
    if options.get('displayName'):
        p['CFBundleDisplayName'] = options['displayName']; p['CFBundleName'] = options['displayName'][:16]
    p['UIDeviceFamily'] = {'iphone':[1], 'ipad':[2], 'universal':[1,2]}[options.get('device','universal')]
    p['MinimumOSVersion'] = options.get('minimumIos','15.0'); p['CFBundleSupportedPlatforms'] = ['iPhoneOS']; p['LSRequiresIPhoneOS'] = True
    with path.open('wb') as f: plistlib.dump(p, f, fmt=plistlib.FMT_BINARY, sort_keys=False)
    return before, {k:p.get(k) for k in keys}


def cleanup(app):
    removed = []
    for p in list(app.rglob('*')):
        try:
            if p.name in {'_CodeSignature','SC_Info'} and p.is_dir() and not p.is_symlink(): shutil.rmtree(p); removed.append(str(p.relative_to(app)))
            elif p.name == 'embedded.mobileprovision' and p.is_file(): p.unlink(); removed.append(str(p.relative_to(app)))
        except OSError: pass
    return removed


def normalize(root):
    for p in root.rglob('*'):
        if p.is_symlink(): continue
        try:
            mode = p.stat().st_mode
            p.chmod(0o755 if p.is_dir() or (p.is_file() and mode & 0o111) else 0o644)
        except OSError: pass


def add_tree(z, root):
    for p in [root, *root.rglob('*')]:
        name = p.relative_to(root.parent).as_posix(); mode = p.lstat().st_mode
        if p.is_symlink():
            i = zipfile.ZipInfo(name); i.create_system = 3; i.external_attr = (stat.S_IFLNK | 0o777) << 16; z.writestr(i, os.readlink(p).encode(), compress_type=zipfile.ZIP_STORED)
        elif p.is_dir():
            i = zipfile.ZipInfo(name.rstrip('/') + '/'); i.create_system = 3; i.external_attr = (stat.S_IFDIR | 0o755) << 16; z.writestr(i, b'', compress_type=zipfile.ZIP_STORED)
        elif p.is_file():
            i = zipfile.ZipInfo.from_file(p, name, strict_timestamps=False); i.create_system = 3; i.external_attr = (stat.S_IFREG | (mode & 0o777)) << 16
            z.writestr(i, p.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)


def convert_deb(input_path, output_path, options_json):
    options, src = json.loads(options_json), Path(input_path)
    data, source_name = src.read_bytes(), str(json.loads(options_json).get('sourceName') or src.name)
    base = Path(source_name).stem or 'Converted'
    report = {'schemaVersion':2,'engine':'DebtoIPA private browser engine','source':{'name':source_name,'size':len(data),'sha256':hashlib.sha256(data).hexdigest()},'target':options,'verdict':'blocked','blockers':[],'warnings':[],'changes':{}}
    try:
        members = ar_members(data); report['source']['archiveMembers'] = [n for n,_ in members]
        payload = next((b for n,b in members if n.startswith('data.tar')), None)
        if payload is None: raise RuntimeError('Debian archive has no data.tar payload.')
        with tempfile.TemporaryDirectory(prefix='debtoipa-') as td:
            root = Path(td); extracted = root/'root'; extracted.mkdir(); extract_tar(payload, extracted)
            paths = {str(p.relative_to(extracted)).replace(os.sep,'/') for p in extracted.rglob('*')}
            markers = [m for m in MARKERS if m in paths or any(x.startswith(m + '/') for x in paths)]
            apps = find_apps(extracted); report['analysis'] = {'packageMarkers':markers,'appCandidates':[str(x.relative_to(extracted)) for x in apps]}
            if not apps:
                report['blockers'].append('This is a jailbreak tweak with no standalone .app bundle.' if markers else 'No standalone iOS .app bundle with Info.plist was found.')
                raise RuntimeError('No convertible app bundle found.')
            if len(apps) > 1: report['warnings'].append(f'Multiple app bundles found; selected {apps[0].name}.')
            source_app, stage = apps[0], root/'stage'; dest = stage/'Payload'/apps[0].name; dest.parent.mkdir(parents=True); shutil.copytree(source_app, dest, symlinks=True)
            before, after = rewrite_plist(dest/'Info.plist', options); exe_name = after.get('CFBundleExecutable')
            if not isinstance(exe_name, str) or not exe_name: report['blockers'].append('Info.plist has no valid CFBundleExecutable.'); raise RuntimeError('Missing executable metadata.')
            exe = dest/exe_name
            if not exe.is_file(): report['blockers'].append(f'The declared executable does not exist: {exe_name}'); raise RuntimeError('Missing executable.')
            blockers, warnings, binary = inspect(exe); report['blockers'] += blockers; report['warnings'] += warnings; report['analysis']['selectedApp'] = str(source_app.relative_to(extracted)); report['analysis']['binary'] = binary
            report['changes'] = {'plistBefore':before,'plistAfter':after,'removedSigningArtifacts':cleanup(dest),'ipaLayout':f'Payload/{dest.name}'}; normalize(stage)
            if report['blockers']: raise RuntimeError('Compatibility checks blocked IPA creation.')
            ipa = root/f'{base}-unsigned.ipa'
            with zipfile.ZipFile(ipa,'w',allowZip64=True,strict_timestamps=False) as z: add_tree(z, stage/'Payload')
            report['verdict'] = 'packaged'; report['output'] = {'name':ipa.name,'size':ipa.stat().st_size,'sha256':hashlib.sha256(ipa.read_bytes()).hexdigest(),'signed':False}
            with zipfile.ZipFile(output_path,'w',allowZip64=True) as z:
                z.writestr('compatibility-report.json',json.dumps(report,indent=2,default=str),compress_type=zipfile.ZIP_DEFLATED); z.writestr(ipa.name,ipa.read_bytes(),compress_type=zipfile.ZIP_STORED)
    except Exception as e:
        if not report['blockers']: report['blockers'].append(str(e))
        report['error'], report['verdict'] = str(e), 'blocked'
        with zipfile.ZipFile(output_path,'w',allowZip64=True) as z: z.writestr('compatibility-report.json',json.dumps(report,indent=2,default=str),compress_type=zipfile.ZIP_DEFLATED)
    return json.dumps({'verdict':report['verdict'],'artifactName':f'{base}-DebtoIPA-result.zip','blockers':report['blockers'],'warnings':report['warnings']},default=str)
