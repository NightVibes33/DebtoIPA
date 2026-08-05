'use client';

import { useEffect, useRef, useState } from 'react';

type Device = 'universal' | 'iphone' | 'ipad';
type Tab = 'convert' | 'jobs' | 'guide';
type Job = {
  id: string;
  name: string;
  createdAt: string;
  status: 'working' | 'completed' | 'failed';
  progress: number;
  stage: string;
  error?: string;
  artifactName?: string;
  artifact?: Blob;
};

const MAX_BYTES = 350 * 1024 * 1024;

function Glyph({ kind }: { kind: 'spark' | 'upload' | 'jobs' | 'guide' | 'shield' | 'bolt' | 'info' | 'check' }) {
  const paths = {
    spark: 'm12 2 1.4 5.6L19 9l-5.6 1.4L12 16l-1.4-5.6L5 9l5.6-1.4L12 2Z',
    upload: 'M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 15v3.5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5V15',
    jobs: 'M5 4h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Zm3 5h8M8 13h8M8 17h5',
    guide: 'M4 5.5A2.5 2.5 0 0 1 6.5 3H11v17H6.5A2.5 2.5 0 0 0 4 22V5.5Zm16 0A2.5 2.5 0 0 0 17.5 3H13v17h4.5A2.5 2.5 0 0 1 20 22V5.5Z',
    shield: 'M12 3 4.5 6v5.5c0 4.6 3.2 7.8 7.5 9.5 4.3-1.7 7.5-4.9 7.5-9.5V6L12 3Zm-3 9 2 2 4-4',
    bolt: 'm13 2-8 12h6l-1 8 8-12h-6l1-8Z',
    info: 'M12 11v6M12 7h.01M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Z',
    check: 'm5 12 4 4L19 6',
  } as const;
  return <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d={paths[kind]}/></svg>;
}

function id() {
  return `${Date.now().toString(36)}-${crypto.getRandomValues(new Uint32Array(1))[0].toString(36)}`;
}

export function LocalDebToIpaApp() {
  const [booting, setBooting] = useState(true);
  const [tab, setTab] = useState<Tab>('convert');
  const [file, setFile] = useState<File | null>(null);
  const [device, setDevice] = useState<Device>('universal');
  const [minimumIos, setMinimumIos] = useState('15.0');
  const [bundleId, setBundleId] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [jobs, setJobs] = useState<Job[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const input = useRef<HTMLInputElement | null>(null);
  const workerRef = useRef<Worker | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => setBooting(false), 1250);
    return () => window.clearTimeout(timer);
  }, []);
  useEffect(() => () => workerRef.current?.terminate(), []);

  function choose(candidate?: File | null) {
    if (!candidate) return;
    if (!candidate.name.toLowerCase().endsWith('.deb')) return setNotice('Choose a file ending in .deb.');
    if (candidate.size > MAX_BYTES) return setNotice('This package is over 350 MB and may exhaust mobile browser memory.');
    setNotice('');
    setFile(candidate);
  }

  function download(job: Job) {
    if (!job.artifact || !job.artifactName) return;
    const url = URL.createObjectURL(job.artifact);
    const link = document.createElement('a');
    link.href = url;
    link.download = job.artifactName;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1500);
  }

  async function convert() {
    if (!file || busy) return;
    const source = file;
    const jobId = id();
    setBusy(true);
    setTab('jobs');
    setJobs((current) => [{ id: jobId, name: source.name, createdAt: new Date().toISOString(), status: 'working', progress: 5, stage: 'Reading package on this device' }, ...current]);

    try {
      const buffer = await source.arrayBuffer();
      const worker = new Worker('/converter-worker.js', { type: 'module' });
      workerRef.current = worker;
      worker.onmessage = (event: MessageEvent) => {
        const message = event.data || {};
        if (message.type === 'engine' || message.type === 'progress') {
          setJobs((current) => current.map((job) => job.id === jobId ? { ...job, progress: Math.max(job.progress, Number(message.progress) || 10), stage: String(message.message || 'Inspecting package') } : job));
          return;
        }
        if (message.type === 'complete') {
          const packaged = message.result?.verdict === 'packaged';
          const artifact = new Blob([message.buffer], { type: 'application/zip' });
          setJobs((current) => current.map((job) => job.id === jobId ? {
            ...job,
            status: packaged ? 'completed' : 'failed',
            progress: 100,
            stage: packaged ? 'IPA and compatibility report ready' : 'Compatibility report ready',
            error: packaged ? undefined : (message.result?.blockers?.join(' ') || 'This package cannot run as a stock iOS app.'),
            artifact,
            artifactName: message.result?.artifactName || `${source.name}-DebtoIPA-result.zip`,
          } : job));
          setFile(null);
          setBusy(false);
          worker.terminate();
          workerRef.current = null;
          return;
        }
        if (message.type === 'error') {
          setJobs((current) => current.map((job) => job.id === jobId ? { ...job, status: 'failed', progress: 100, stage: 'Conversion failed', error: String(message.message || 'The private engine failed.') } : job));
          setBusy(false);
          worker.terminate();
          workerRef.current = null;
        }
      };
      worker.onerror = (event) => {
        setJobs((current) => current.map((job) => job.id === jobId ? { ...job, status: 'failed', progress: 100, stage: 'Engine failed to start', error: event.message || 'The browser could not start the converter.' } : job));
        setBusy(false);
        worker.terminate();
        workerRef.current = null;
      };
      worker.postMessage({ id: jobId, buffer, options: { sourceName: source.name, device, minimumIos, bundleId, displayName } }, [buffer]);
    } catch (error) {
      setJobs((current) => current.map((job) => job.id === jobId ? { ...job, status: 'failed', progress: 100, stage: 'Conversion failed', error: error instanceof Error ? error.message : 'Conversion could not start.' } : job));
      setBusy(false);
    }
  }

  if (booting) return <main className="boot-screen"><div className="ambient ambient-a"/><div className="ambient ambient-b"/><div className="boot-mark"><Glyph kind="spark"/><span className="boot-orbit"/></div><h1>DebtoIPA</h1><p>Preparing the private conversion engine</p><div className="boot-loader"><span/></div></main>;

  return <main className="app-shell">
    <div className="noise"/><div className="ambient ambient-a"/><div className="ambient ambient-b"/>
    <header className="topbar"><div className="brand"><div className="brand-mark"><Glyph kind="spark"/></div><div><strong>DebtoIPA</strong><span>Private stock-iOS packager</span></div></div><div className="runner-pill"><span/>No setup</div></header>

    <div className="content">
      {tab === 'convert' && <section className="view enter">
        <div className="hero-copy"><p className="eyebrow">ON-DEVICE CONVERSION</p><h1>Turn a compatible <span>.deb</span> into a correctly packaged IPA.</h1><p>The file stays on your device. No GitHub token, Vercel Blob store, access code, or account configuration is required.</p></div>
        <div className={`upload-zone ${file ? 'has-file' : ''}`} onClick={() => input.current?.click()} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); choose(event.dataTransfer.files?.[0]); }}>
          <input ref={input} hidden type="file" accept=".deb,application/vnd.debian.binary-package" onChange={(event) => choose(event.target.files?.[0])}/>
          <div className="upload-icon"><Glyph kind={file ? 'check' : 'upload'}/></div><strong>{file?.name || 'Drop your Debian package'}</strong><span>{file ? `${(file.size / 1048576).toFixed(1)} MB · ready to inspect privately` : 'or tap to browse · up to 350 MB'}</span>
        </div>
        <div className="settings-card"><div className="section-title"><div><p className="eyebrow">TARGET</p><h2>Device compatibility</h2></div><Glyph kind="shield"/></div>
          <div className="segmented">{(['universal','iphone','ipad'] as Device[]).map((value) => <button key={value} className={device === value ? 'active' : ''} onClick={() => setDevice(value)}>{value === 'universal' ? 'Universal' : value === 'iphone' ? 'iPhone' : 'iPad'}</button>)}</div>
          <div className="field-grid"><label><span>Minimum iOS</span><input value={minimumIos} onChange={(event) => setMinimumIos(event.target.value)} inputMode="decimal"/></label><label><span>Display name <em>optional</em></span><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="Keep original"/></label><label className="full"><span>Bundle ID <em>optional</em></span><input value={bundleId} onChange={(event) => setBundleId(event.target.value)} autoCapitalize="none" placeholder="com.example.repackedapp"/></label></div>
        </div>
        {notice && <div className="notice"><Glyph kind="info"/><span>{notice}</span></div>}
        <button className="primary convert-button" disabled={!file || busy} onClick={convert}><Glyph kind="bolt"/>{busy ? 'Converting privately…' : 'Convert on this device'}</button>
        <div className="truth-card"><Glyph kind="info"/><p><strong>Important:</strong> This packages a standalone ARM64 app already contained in a DEB. SpringBoard tweaks, daemons, root-only packages, substrate hooks, and 32-bit binaries cannot be made stock-iOS compatible by repackaging.</p></div>
      </section>}

      {tab === 'jobs' && <section className="view enter"><div className="view-heading"><div><p className="eyebrow">ACTIVITY</p><h1>Local jobs</h1></div><span>{jobs.length}</span></div>
        {!jobs.length && <div className="empty-state"><div className="upload-icon"><Glyph kind="jobs"/></div><h2>No conversions yet</h2><p>Results appear here without leaving this browser.</p><button className="secondary" onClick={() => setTab('convert')}>Start a conversion</button></div>}
        <div className="job-list">{jobs.map((job) => <article className="job-card" key={job.id}><div className="job-top"><div className={`job-status ${job.status === 'working' ? 'in_progress' : job.status}`}><Glyph kind={job.status === 'completed' ? 'check' : job.status === 'failed' ? 'info' : 'jobs'}/></div><div className="job-name"><strong>{job.name}</strong><span>{new Date(job.createdAt).toLocaleString()}</span></div><span className={`status-label ${job.status === 'working' ? 'in_progress' : job.status}`}>{job.status}</span></div><div className="progress-track"><span style={{ width: `${job.progress}%` }}/></div><div className="job-meta"><span>{job.stage}</span><strong>{job.progress}%</strong></div>{job.error && <p className="job-error">{job.error}</p>}<div className="job-actions">{job.artifact && <button className="primary compact" onClick={() => download(job)}><Glyph kind="upload"/>Download result ZIP</button>}</div></article>)}</div>
      </section>}

      {tab === 'guide' && <section className="view enter"><div className="hero-copy"><p className="eyebrow">HOW IT WORKS</p><h1>Private conversion, real checks.</h1><p>Pyodide runs Python inside a Web Worker, opens the Debian archive, validates the app, rewrites its plist, and creates the unsigned IPA locally.</p></div><div className="guide-grid"><article><span>01</span><div><h3>Extract</h3><p>Open gzip, bzip2, xz, or zstd Debian payloads in the browser.</p></div></article><article><span>02</span><div><h3>Inspect</h3><p>Check ARM64, Mach-O libraries, jailbreak paths, app metadata, and tweak markers.</p></div></article><article><span>03</span><div><h3>Repair</h3><p>Remove stale signing files and build the correct <code>Payload/App.app</code> layout.</p></div></article><article><span>04</span><div><h3>Download</h3><p>Receive a ZIP containing the unsigned IPA and full JSON compatibility report.</p></div></article></div></section>}
    </div>

    <nav className="bottom-nav"><button className={tab === 'convert' ? 'active' : ''} onClick={() => setTab('convert')}><Glyph kind="spark"/><span>Convert</span></button><button className={tab === 'jobs' ? 'active' : ''} onClick={() => setTab('jobs')}><Glyph kind="jobs"/><span>Jobs</span>{jobs.some((job) => job.status === 'working') && <i/>}</button><button className={tab === 'guide' ? 'active' : ''} onClick={() => setTab('guide')}><Glyph kind="guide"/><span>Guide</span></button></nav>
  </main>;
}
