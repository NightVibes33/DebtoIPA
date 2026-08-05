'use client';

import { upload } from '@vercel/blob/client';
import { useCallback, useEffect, useRef, useState } from 'react';

type Device = 'universal' | 'iphone' | 'ipad';
type Status = 'uploading' | 'queued' | 'in_progress' | 'completed' | 'failed';
type Artifact = { id: number; name: string; size: number; downloadUrl: string };
type Job = {
  id: string;
  fileName: string;
  createdAt: string;
  status: Status;
  progress: number;
  stage: string;
  conclusion?: string | null;
  artifact?: Artifact | null;
  error?: string;
  htmlUrl?: string;
};

const STORAGE_KEY = 'debtoipa.runner.jobs.v2';
const MAX_BYTES = 750 * 1024 * 1024;

function makeId() {
  return `${Date.now().toString(36)}-${crypto.getRandomValues(new Uint32Array(1))[0].toString(36)}`;
}

export function RunnerDebToIpaApp() {
  const [file, setFile] = useState<File | null>(null);
  const [device, setDevice] = useState<Device>('universal');
  const [minimumIos, setMinimumIos] = useState('15.0');
  const [displayName, setDisplayName] = useState('');
  const [bundleId, setBundleId] = useState('');
  const [accessCode, setAccessCode] = useState('');
  const [jobs, setJobs] = useState<Job[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setAccessCode(localStorage.getItem('debtoipa.accessCode') || '');
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
      try { setJobs(JSON.parse(saved)); } catch { /* ignore invalid cache */ }
    }
  }, []);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(jobs.slice(0, 30)));
  }, [jobs]);

  const poll = useCallback(async (jobId: string) => {
    try {
      const response = await fetch(`/api/jobs/${jobId}`, {
        headers: accessCode ? { 'x-app-access-code': accessCode } : {},
        cache: 'no-store',
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Could not read runner status.');
      const status: Status = data.status === 'completed'
        ? (data.conclusion === 'success' ? 'completed' : 'failed')
        : data.status === 'in_progress' ? 'in_progress' : 'queued';
      const progress = status === 'queued' ? 34 : status === 'in_progress' ? Number(data.progress || 66) : 100;
      setJobs((current) => current.map((job) => job.id === jobId ? {
        ...job,
        status,
        progress,
        stage: String(data.stage || (status === 'completed' ? 'Artifact ready' : 'Queued on GitHub')),
        conclusion: data.conclusion,
        artifact: data.artifact || null,
        htmlUrl: data.htmlUrl,
        error: status === 'failed' ? String(data.error || 'The runner failed. The result artifact may contain a compatibility report.') : undefined,
      } : job));
    } catch (error) {
      setJobs((current) => current.map((job) => job.id === jobId ? {
        ...job,
        error: error instanceof Error ? error.message : 'Runner status check failed.',
      } : job));
    }
  }, [accessCode]);

  useEffect(() => {
    const active = jobs.filter((job) => job.status === 'queued' || job.status === 'in_progress');
    if (!active.length) return;
    const tick = () => active.forEach((job) => void poll(job.id));
    tick();
    const timer = window.setInterval(tick, 5000);
    return () => window.clearInterval(timer);
  }, [jobs.map((job) => `${job.id}:${job.status}`).join('|'), poll]);

  function choose(candidate?: File | null) {
    if (!candidate) return;
    if (!candidate.name.toLowerCase().endsWith('.deb')) {
      setNotice('Choose a file ending in .deb.');
      return;
    }
    if (candidate.size > MAX_BYTES) {
      setNotice('The package exceeds the 750 MB runner limit.');
      return;
    }
    setNotice('');
    setFile(candidate);
  }

  async function start() {
    if (!file || busy) return;
    const source = file;
    const id = makeId();
    setBusy(true);
    setNotice('');
    setJobs((current) => [{
      id,
      fileName: source.name,
      createdAt: new Date().toISOString(),
      status: 'uploading',
      progress: 4,
      stage: 'Uploading package to runner storage',
    }, ...current]);

    try {
      const blob = await upload(`deb-inputs/${id}/${source.name}`, source, {
        access: 'public',
        handleUploadUrl: '/api/upload',
        clientPayload: JSON.stringify({ jobId: id, accessCode }),
        multipart: source.size > 90 * 1024 * 1024,
        onUploadProgress: ({ percentage }) => {
          setJobs((current) => current.map((job) => job.id === id ? {
            ...job,
            progress: Math.max(4, Math.min(30, Math.round(percentage * 0.3))),
            stage: `Uploading package · ${Math.round(percentage)}%`,
          } : job));
        },
      });

      setJobs((current) => current.map((job) => job.id === id ? {
        ...job,
        status: 'queued',
        progress: 32,
        stage: 'Dispatching GitHub macOS runner',
      } : job));

      const response = await fetch('/api/jobs', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(accessCode ? { 'x-app-access-code': accessCode } : {}),
        },
        body: JSON.stringify({
          sourceUrl: blob.url,
          sourceName: source.name,
          targetDevice: device,
          minimumIos,
          bundleId,
          displayName,
          jobId: id,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'GitHub runner dispatch failed.');
      setFile(null);
    } catch (error) {
      setJobs((current) => current.map((job) => job.id === id ? {
        ...job,
        status: 'failed',
        progress: 100,
        stage: 'Could not start runner',
        error: error instanceof Error ? error.message : 'Conversion could not start.',
      } : job));
    } finally {
      setBusy(false);
    }
  }

  async function download(artifact: Artifact) {
    setNotice('');
    try {
      const response = await fetch(artifact.downloadUrl, {
        headers: accessCode ? { 'x-app-access-code': accessCode } : {},
        cache: 'no-store',
      });
      if (!response.ok) throw new Error(await response.text());
      const objectUrl = URL.createObjectURL(await response.blob());
      const anchor = document.createElement('a');
      anchor.href = objectUrl;
      anchor.download = `${artifact.name}.zip`;
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1500);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Artifact download failed.');
    }
  }

  return <main className="app-shell">
    <div className="noise"/><div className="ambient ambient-a"/><div className="ambient ambient-b"/>
    <header className="topbar">
      <div className="brand"><div className="brand-mark">✦</div><div><strong>DebToIPA</strong><span>GitHub runner Smart Auto</span></div></div>
      <div className="runner-pill"><span/>macOS runner</div>
    </header>

    <div className="content">
      <section className="view enter">
        <div className="hero-copy">
          <p className="eyebrow">RUNNER-BACKED CONVERSION</p>
          <h1>Build the compatible app. <span>Do not freeze in the browser.</span></h1>
          <p>The phone only uploads and tracks the job. GitHub analyzes the full package, packages a direct IPA when possible, or compiles a stock-iOS replacement host on a macOS runner.</p>
        </div>

        <button className={`upload-zone ${file ? 'has-file' : ''}`} onClick={() => inputRef.current?.click()}>
          <input ref={inputRef} type="file" hidden onChange={(event) => choose(event.target.files?.[0])}/>
          <div className="upload-icon">{file ? '✓' : '⇧'}</div>
          <strong>{file?.name || 'Choose a Debian package'}</strong>
          <span>{file ? `${(file.size / 1048576).toFixed(1)} MB · ready` : 'iPhone Files · up to 750 MB'}</span>
        </button>

        <div className="settings-card">
          <div className="section-title"><div><p className="eyebrow">TARGET</p><h2>Build settings</h2></div><span>⚙</span></div>
          <div className="segmented">{(['universal','iphone','ipad'] as Device[]).map((value) => <button key={value} className={device === value ? 'active' : ''} onClick={() => setDevice(value)}>{value === 'universal' ? 'Universal' : value === 'iphone' ? 'iPhone' : 'iPad'}</button>)}</div>
          <div className="field-grid">
            <label><span>Minimum iOS</span><input value={minimumIos} onChange={(event) => setMinimumIos(event.target.value)} inputMode="decimal"/></label>
            <label><span>Display name <em>optional</em></span><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="Keep original"/></label>
            <label className="full"><span>Bundle ID <em>optional</em></span><input value={bundleId} onChange={(event) => setBundleId(event.target.value)} placeholder="com.example.portedapp" autoCapitalize="none"/></label>
            <label className="full"><span>Access code <em>only when configured</em></span><input value={accessCode} onChange={(event) => { setAccessCode(event.target.value); localStorage.setItem('debtoipa.accessCode', event.target.value); }} type="password"/></label>
          </div>
        </div>

        {notice && <div className="notice">ⓘ <span>{notice}</span></div>}
        <button className="primary convert-button" disabled={!file || busy} onClick={start}>⚡ {busy ? 'Starting runner…' : 'Build with GitHub runner'}</button>
        <div className="truth-card">ⓘ <p><strong>Compatibility rule:</strong> a runner can compile generated replacement source, but it cannot infer every missing private API implementation from an opaque binary. Results identify whether the produced IPA is direct, feature-complete replacement, or partial replacement.</p></div>
      </section>

      <section className="view enter">
        <div className="view-heading"><div><p className="eyebrow">RUNNER ACTIVITY</p><h1>Build jobs</h1></div><span>{jobs.length}</span></div>
        {!jobs.length && <div className="empty-state"><div className="upload-icon">▤</div><h2>No runner jobs yet</h2><p>Your upload and every GitHub build stage will appear here.</p></div>}
        <div className="job-list">{jobs.map((job) => <article className="job-card" key={job.id}>
          <div className="job-top"><div className={`job-status ${job.status}`}>{job.status === 'completed' ? '✓' : job.status === 'failed' ? '!' : '▤'}</div><div className="job-name"><strong>{job.fileName}</strong><span>{new Date(job.createdAt).toLocaleString()}</span></div><span className={`status-label ${job.status}`}>{job.status.replace('_',' ')}</span></div>
          <div className="progress-track"><span style={{width: `${job.progress}%`}}/></div>
          <div className="job-meta"><span>{job.stage}</span><strong>{job.progress}%</strong></div>
          {job.error && <p className="job-error">{job.error}</p>}
          <div className="job-actions">{job.artifact && <button className="primary compact" onClick={() => void download(job.artifact!)}>⇩ Download IPA + report</button>}{job.htmlUrl && <a className="secondary compact" href={job.htmlUrl} target="_blank" rel="noreferrer">Open runner</a>}</div>
        </article>)}</div>
      </section>
    </div>
  </main>;
}
