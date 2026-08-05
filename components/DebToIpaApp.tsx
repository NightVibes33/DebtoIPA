'use client';

import { upload } from '@vercel/blob/client';
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

type Tab = 'convert' | 'jobs' | 'guide';
type Device = 'universal' | 'iphone' | 'ipad';
type JobStatus = 'uploading' | 'queued' | 'in_progress' | 'completed' | 'failed';

type Job = {
  id: string;
  fileName: string;
  createdAt: string;
  status: JobStatus;
  conclusion?: string | null;
  progress: number;
  artifact?: { id: number; name: string; size: number; downloadUrl: string } | null;
  error?: string;
  htmlUrl?: string;
};

const storageKey = 'debtoipa.jobs.v1';

function Icon({ name, size = 22 }: { name: 'spark' | 'upload' | 'jobs' | 'book' | 'check' | 'shield' | 'bolt' | 'arrow' | 'package' | 'info'; size?: number }) {
  const paths: Record<string, ReactNode> = {
    spark: <path d="m12 2 1.45 5.55L19 9l-5.55 1.45L12 16l-1.45-5.55L5 9l5.55-1.45L12 2Zm6 12 .8 3.2L22 18l-3.2.8L18 22l-.8-3.2L14 18l3.2-.8L18 14Z" />,
    upload: <><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5"/><path d="M5 15v3.5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5V15"/></>,
    jobs: <><rect x="4" y="4" width="16" height="16" rx="4"/><path d="M8 9h8M8 13h8M8 17h5"/></>,
    book: <><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H11v17H6.5A2.5 2.5 0 0 0 4 22V5.5Z"/><path d="M20 5.5A2.5 2.5 0 0 0 17.5 3H13v17h4.5A2.5 2.5 0 0 1 20 22V5.5Z"/></>,
    check: <path d="m5 12 4 4L19 6"/>,
    shield: <path d="M12 3 4.5 6v5.5c0 4.6 3.2 7.8 7.5 9.5 4.3-1.7 7.5-4.9 7.5-9.5V6L12 3Zm-3 9 2 2 4-4"/>,
    bolt: <path d="m13 2-8 12h6l-1 8 8-12h-6l1-8Z"/>,
    arrow: <path d="M5 12h14m-5-5 5 5-5 5"/>,
    package: <><path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Z"/><path d="m4 7.5 8 4.5 8-4.5M12 12v9"/></>,
    info: <><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>{paths[name]}</svg>;
}

function randomId() {
  return `${Date.now().toString(36)}-${crypto.getRandomValues(new Uint32Array(1))[0].toString(36)}`;
}

export function DebToIpaApp() {
  const [booting, setBooting] = useState(true);
  const [onboarding, setOnboarding] = useState(false);
  const [onboardStep, setOnboardStep] = useState(0);
  const [tab, setTab] = useState<Tab>('convert');
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [device, setDevice] = useState<Device>('universal');
  const [minimumIos, setMinimumIos] = useState('15.0');
  const [bundleId, setBundleId] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [accessCode, setAccessCode] = useState('');
  const [jobs, setJobs] = useState<Job[]>([]);
  const [busy, setBusy] = useState(false);
  const [downloadingArtifactId, setDownloadingArtifactId] = useState<number | null>(null);
  const [notice, setNotice] = useState('');
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setBooting(false);
      setOnboarding(localStorage.getItem('debtoipa.onboarded') !== 'yes');
      const stored = localStorage.getItem(storageKey);
      if (stored) {
        try { setJobs(JSON.parse(stored)); } catch { /* ignore corrupt local state */ }
      }
      setAccessCode(localStorage.getItem('debtoipa.accessCode') || '');
    }, 1750);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (!booting) localStorage.setItem(storageKey, JSON.stringify(jobs.slice(0, 30)));
  }, [jobs, booting]);

  const apiHeaders = useMemo(() => ({
    'Content-Type': 'application/json',
    ...(accessCode ? { 'x-app-access-code': accessCode } : {}),
  }), [accessCode]);

  const pollJob = useCallback(async (jobId: string) => {
    try {
      const response = await fetch(`/api/jobs/${jobId}`, { headers: accessCode ? { 'x-app-access-code': accessCode } : {}, cache: 'no-store' });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Status check failed.');
      const status: JobStatus = data.status === 'completed'
        ? (data.conclusion === 'success' ? 'completed' : 'failed')
        : data.status === 'in_progress' ? 'in_progress' : 'queued';
      setJobs((current) => current.map((job) => job.id === jobId ? {
        ...job,
        status,
        conclusion: data.conclusion,
        progress: status === 'queued' ? 38 : status === 'in_progress' ? 72 : 100,
        artifact: data.artifact || null,
        htmlUrl: data.htmlUrl,
        error: status === 'failed' ? 'The package was rejected or conversion failed. Download the report artifact when available.' : undefined,
      } : job));
      return status;
    } catch (error) {
      setJobs((current) => current.map((job) => job.id === jobId ? { ...job, error: error instanceof Error ? error.message : 'Status check failed.' } : job));
      return 'queued' as JobStatus;
    }
  }, [accessCode]);

  useEffect(() => {
    const active = jobs.filter((job) => ['queued', 'in_progress'].includes(job.status));
    if (!active.length) return;
    const tick = () => active.forEach((job) => void pollJob(job.id));
    tick();
    const interval = window.setInterval(tick, 7000);
    return () => window.clearInterval(interval);
  }, [jobs.map((j) => `${j.id}:${j.status}`).join('|'), pollJob]);

  async function downloadArtifact(artifact: NonNullable<Job['artifact']>) {
    if (downloadingArtifactId !== null) return;
    setDownloadingArtifactId(artifact.id);
    setNotice('');
    try {
      const response = await fetch(artifact.downloadUrl, {
        headers: accessCode ? { 'x-app-access-code': accessCode } : {},
        cache: 'no-store',
      });
      if (!response.ok) throw new Error((await response.text()) || 'Download failed.');
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = objectUrl;
      anchor.download = `${artifact.name || `DebtoIPA-${artifact.id}`}.zip`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Download failed.');
      setTab('jobs');
    } finally {
      setDownloadingArtifactId(null);
    }
  }

  function acceptFile(candidate?: File | null) {
    if (!candidate) return;
    if (!candidate.name.toLowerCase().endsWith('.deb')) {
      setNotice('Choose a Debian package ending in .deb.');
      return;
    }
    setFile(candidate);
    setNotice('');
  }

  async function convert() {
    if (!file || busy) return;
    setBusy(true);
    setNotice('');
    const id = randomId();
    const newJob: Job = { id, fileName: file.name, createdAt: new Date().toISOString(), status: 'uploading', progress: 8 };
    setJobs((current) => [newJob, ...current]);
    setTab('jobs');

    try {
      const blob = await upload(`deb-inputs/${id}/${file.name}`, file, {
        access: 'public',
        handleUploadUrl: '/api/upload',
        clientPayload: JSON.stringify({ jobId: id, accessCode }),
        multipart: file.size > 100 * 1024 * 1024,
        onUploadProgress: ({ percentage }) => {
          setJobs((current) => current.map((job) => job.id === id ? { ...job, progress: Math.max(8, Math.round(percentage * 0.28)) } : job));
        },
      });
      setJobs((current) => current.map((job) => job.id === id ? { ...job, status: 'queued', progress: 32 } : job));

      const response = await fetch('/api/jobs', {
        method: 'POST',
        headers: apiHeaders,
        body: JSON.stringify({
          sourceUrl: blob.url,
          sourceName: file.name,
          targetDevice: device,
          minimumIos,
          bundleId,
          displayName,
          jobId: id,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Could not queue conversion.');
      setFile(null);
    } catch (error) {
      setJobs((current) => current.map((job) => job.id === id ? {
        ...job,
        status: 'failed',
        progress: 100,
        error: error instanceof Error ? error.message : 'Conversion could not start.',
      } : job));
    } finally {
      setBusy(false);
    }
  }

  const currentOnboard = [
    { icon: 'package' as const, kicker: 'DEB → IPA', title: 'Package the app, not the illusion.', body: 'DebtoIPA extracts real iOS app bundles, repairs IPA structure, and refuses packages that only contain jailbreak injection tweaks.' },
    { icon: 'shield' as const, kicker: 'STOCK CHECK', title: 'Know what can actually run.', body: 'The runner checks architecture, executable metadata, jailbreak paths, tweak loaders, and external library dependencies before producing an IPA.' },
    { icon: 'bolt' as const, kicker: 'CLOUD RUNNER', title: 'Vercel in front. GitHub underneath.', body: 'Your phone handles the polished upload flow. GitHub Actions performs deterministic conversion and returns the IPA plus a full compatibility report.' },
  ][onboardStep];

  if (booting) return (
    <main className="boot-screen">
      <div className="ambient ambient-a"/><div className="ambient ambient-b"/>
      <div className="boot-mark"><Icon name="spark" size={38}/><span className="boot-orbit"/></div>
      <h1>DebtoIPA</h1><p>Preparing the conversion engine</p>
      <div className="boot-loader"><span/></div>
    </main>
  );

  if (onboarding) return (
    <main className="onboarding-shell">
      <div className="noise"/><div className="ambient ambient-a"/><div className="ambient ambient-c"/>
      <button className="skip" onClick={() => { localStorage.setItem('debtoipa.onboarded', 'yes'); setOnboarding(false); }}>Skip</button>
      <section className="onboarding-card" key={onboardStep}>
        <div className="onboard-visual"><div className="visual-ring ring-one"/><div className="visual-ring ring-two"/><div className="visual-icon"><Icon name={currentOnboard.icon} size={50}/></div></div>
        <p className="eyebrow">{currentOnboard.kicker}</p>
        <h1>{currentOnboard.title}</h1>
        <p className="lead">{currentOnboard.body}</p>
        <div className="dots">{[0,1,2].map((dot) => <span className={dot === onboardStep ? 'active' : ''} key={dot}/>)}</div>
        <button className="primary wide" onClick={() => {
          if (onboardStep < 2) setOnboardStep(onboardStep + 1);
          else { localStorage.setItem('debtoipa.onboarded', 'yes'); setOnboarding(false); }
        }}>{onboardStep < 2 ? 'Continue' : 'Open DebtoIPA'} <Icon name="arrow"/></button>
      </section>
    </main>
  );

  return (
    <main className="app-shell">
      <div className="noise"/><div className="ambient ambient-a"/><div className="ambient ambient-b"/>
      <header className="topbar">
        <div className="brand"><div className="brand-mark"><Icon name="spark"/></div><div><strong>DebtoIPA</strong><span>Stock iOS packager</span></div></div>
        <div className="runner-pill"><span/>Runner ready</div>
      </header>

      <div className="content">
        {tab === 'convert' && <section className="view enter">
          <div className="hero-copy"><p className="eyebrow">CLOUD CONVERSION</p><h1>Turn a compatible <span>.deb</span> into a correctly packaged IPA.</h1><p>Upload an app-style Debian package. The GitHub runner extracts, checks, repairs, and packages it for sideloading.</p></div>

          <div className={`upload-zone ${dragging ? 'dragging' : ''} ${file ? 'has-file' : ''}`}
            onDragEnter={(e) => { e.preventDefault(); setDragging(true); }} onDragOver={(e) => e.preventDefault()} onDragLeave={() => setDragging(false)}
            onDrop={(e) => { e.preventDefault(); setDragging(false); acceptFile(e.dataTransfer.files?.[0]); }}
            onClick={() => fileInput.current?.click()}>
            <input ref={fileInput} type="file" accept=".deb,application/vnd.debian.binary-package,application/octet-stream" hidden onChange={(e) => acceptFile(e.target.files?.[0])}/>
            <div className="upload-icon"><Icon name={file ? 'check' : 'upload'} size={30}/></div>
            <strong>{file ? file.name : 'Drop your Debian package'}</strong>
            <span>{file ? `${(file.size / 1024 / 1024).toFixed(1)} MB · ready to inspect` : 'or tap to browse · up to 750 MB'}</span>
          </div>

          <div className="settings-card">
            <div className="section-title"><div><p className="eyebrow">TARGET</p><h2>Device compatibility</h2></div><Icon name="shield"/></div>
            <div className="segmented">{(['universal','iphone','ipad'] as Device[]).map((item) => <button key={item} className={device === item ? 'active' : ''} onClick={() => setDevice(item)}>{item === 'universal' ? 'Universal' : item === 'iphone' ? 'iPhone' : 'iPad'}</button>)}</div>
            <div className="field-grid">
              <label><span>Minimum iOS</span><input value={minimumIos} onChange={(e) => setMinimumIos(e.target.value)} inputMode="decimal" placeholder="15.0"/></label>
              <label><span>Display name <em>optional</em></span><input value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="Keep original"/></label>
              <label className="full"><span>Bundle ID <em>optional</em></span><input value={bundleId} onChange={(e) => setBundleId(e.target.value)} autoCapitalize="none" placeholder="com.example.repackedapp"/></label>
              <label className="full"><span>Private access code <em>optional</em></span><input value={accessCode} onChange={(e) => { setAccessCode(e.target.value); localStorage.setItem('debtoipa.accessCode', e.target.value); }} type="password" placeholder="Only needed when enabled by the owner"/></label>
            </div>
          </div>

          {notice && <div className="notice"><Icon name="info"/><span>{notice}</span></div>}
          <button className="primary convert-button" disabled={!file || busy} onClick={convert}><Icon name="bolt"/>{busy ? 'Starting conversion…' : 'Convert with GitHub Runner'}<Icon name="arrow"/></button>
          <div className="truth-card"><Icon name="info"/><p><strong>Important:</strong> An iOS tweak is not automatically an app. Packages that require MobileSubstrate, ElleKit, root filesystem access, daemons, or unavailable private dependencies are rejected with a report instead of producing a fake IPA.</p></div>
        </section>}

        {tab === 'jobs' && <section className="view enter">
          <div className="view-heading"><div><p className="eyebrow">ACTIVITY</p><h1>Conversion jobs</h1></div><span>{jobs.length}</span></div>
          {!jobs.length && <div className="empty-state"><div className="upload-icon"><Icon name="jobs" size={30}/></div><h2>No conversions yet</h2><p>Your uploaded packages and downloadable results will appear here.</p><button className="secondary" onClick={() => setTab('convert')}>Start a conversion</button></div>}
          <div className="job-list">{jobs.map((job) => <article className="job-card" key={job.id}>
            <div className="job-top"><div className={`job-status ${job.status}`}><Icon name={job.status === 'completed' ? 'check' : job.status === 'failed' ? 'info' : 'package'}/></div><div className="job-name"><strong>{job.fileName}</strong><span>{new Date(job.createdAt).toLocaleString()}</span></div><span className={`status-label ${job.status}`}>{job.status.replace('_', ' ')}</span></div>
            <div className="progress-track"><span style={{ width: `${job.progress}%` }}/></div>
            <div className="job-meta"><span>{job.status === 'uploading' ? 'Uploading directly' : job.status === 'queued' ? 'Waiting for runner' : job.status === 'in_progress' ? 'Inspecting and packaging' : job.status === 'completed' ? 'Artifact ready' : 'Needs review'}</span><strong>{job.progress}%</strong></div>
            {job.error && <p className="job-error">{job.error}</p>}
            <div className="job-actions">
              {job.artifact && <button className="primary compact" disabled={downloadingArtifactId !== null} onClick={() => void downloadArtifact(job.artifact!)}><Icon name="upload"/>{downloadingArtifactId === job.artifact.id ? 'Preparing download…' : 'Download result ZIP'}</button>}
              {job.htmlUrl && <a className="ghost-link" href={job.htmlUrl} target="_blank" rel="noreferrer">View runner logs <Icon name="arrow" size={17}/></a>}
              {['queued','in_progress'].includes(job.status) && <button className="ghost-link" onClick={() => void pollJob(job.id)}>Refresh status</button>}
            </div>
          </article>)}</div>
        </section>}

        {tab === 'guide' && <section className="view enter">
          <div className="hero-copy"><p className="eyebrow">HOW IT WORKS</p><h1>Real conversion has rules.</h1><p>DebtoIPA changes packaging and metadata. It cannot invent a stock-iOS implementation for code designed only for a jailbroken runtime.</p></div>
          <div className="guide-grid">
            <article><span>01</span><div><h3>Extract</h3><p>The runner opens the Debian archive and locates an actual <code>.app</code> bundle.</p></div></article>
            <article><span>02</span><div><h3>Analyze</h3><p>It checks ARM64 architecture, the executable, linked libraries, rootless paths, tweak loaders, and app metadata.</p></div></article>
            <article><span>03</span><div><h3>Repair</h3><p>It creates <code>Payload/App.app</code>, removes stale signatures, sets device family and minimum iOS, and applies optional naming overrides.</p></div></article>
            <article><span>04</span><div><h3>Package</h3><p>A deterministic unsigned IPA and JSON compatibility report are stored as a short-lived GitHub artifact.</p></div></article>
          </div>
          <div className="compatibility"><h2>What usually works</h2><ul><li><Icon name="check"/>Debs that already contain a standalone ARM64 iOS app</li><li><Icon name="check"/>Jailbreak-distributed apps that use only public or bundled frameworks</li><li><Icon name="check"/>iPad apps whose UI already supports iPhone layouts</li></ul></div>
          <div className="compatibility danger"><h2>What cannot be auto-converted</h2><ul><li><Icon name="info"/>SpringBoard or app-injection tweaks</li><li><Icon name="info"/>Packages requiring root, launch daemons, substrate, ElleKit, or libhooker</li><li><Icon name="info"/>32-bit binaries or apps linked to unavailable jailbreak libraries</li></ul></div>
        </section>}
      </div>

      <nav className="bottom-nav" aria-label="Primary navigation">
        <button className={tab === 'convert' ? 'active' : ''} onClick={() => setTab('convert')}><Icon name="spark"/><span>Convert</span></button>
        <button className={tab === 'jobs' ? 'active' : ''} onClick={() => setTab('jobs')}><Icon name="jobs"/><span>Jobs</span>{jobs.some((j) => ['queued','in_progress'].includes(j.status)) && <i/>}</button>
        <button className={tab === 'guide' ? 'active' : ''} onClick={() => setTab('guide')}><Icon name="book"/><span>Guide</span></button>
      </nav>
    </main>
  );
}
