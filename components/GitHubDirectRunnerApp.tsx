'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

type Device = 'universal' | 'iphone' | 'ipad';
type JobStatus = 'uploading' | 'queued' | 'in_progress' | 'completed' | 'failed';
type Artifact = { id: number; name: string; size: number };
type Job = {
  id: string;
  fileName: string;
  createdAt: string;
  status: JobStatus;
  progress: number;
  stage: string;
  artifact?: Artifact | null;
  runUrl?: string;
  error?: string;
};

type GitHubRun = {
  id: number;
  status: string;
  conclusion: string | null;
  display_title: string;
  html_url: string;
};

type GitHubStep = { name: string; status: string; conclusion: string | null };

const OWNER = 'NightVibes33';
const REPO = 'DebtoIPA';
const API = `https://api.github.com/repos/${OWNER}/${REPO}`;
const CHUNK_SIZE = 16 * 1024 * 1024;
const MAX_SIZE = 750 * 1024 * 1024;
const JOB_STORAGE = 'debtoipa.github.jobs.v1';
const TOKEN_STORAGE = 'debtoipa.github.token.session';

const stageProgress: Record<string, number> = {
  'Set up job': 35,
  'Checkout DebToIPA': 40,
  'Acquire Debian package': 50,
  'Validate Debian archive': 56,
  'Audit package and choose build path': 62,
  'Build and validate IPA': 84,
  'Publish runner summary': 91,
  'Upload IPA, Port Project, and reports': 97,
  'Delete temporary upload branch': 99,
  'Complete job': 100,
};

const stageLabels: Record<string, string> = {
  'Set up job': 'Starting GitHub macOS runner',
  'Checkout DebToIPA': 'Loading DebToIPA source',
  'Acquire Debian package': 'Reconstructing package from GitHub chunks',
  'Validate Debian archive': 'Validating Debian archive',
  'Audit package and choose build path': 'Auditing apps, helpers, daemons, paths, and entitlements',
  'Build and validate IPA': 'Packaging direct IPA or compiling replacement host with Xcode',
  'Publish runner summary': 'Writing compatibility report',
  'Upload IPA, Port Project, and reports': 'Uploading IPA and reports',
  'Delete temporary upload branch': 'Removing temporary package upload',
  'Complete job': 'Artifact ready',
};

function makeId() {
  return `${Date.now().toString(36)}-${crypto.getRandomValues(new Uint32Array(1))[0].toString(36)}`;
}

function bytesToBase64(bytes: Uint8Array) {
  let binary = '';
  const stride = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += stride) {
    binary += String.fromCharCode(...bytes.subarray(offset, Math.min(offset + stride, bytes.length)));
  }
  return btoa(binary);
}

function safeFileName(name: string) {
  return name.replace(/[^A-Za-z0-9._-]+/g, '-').slice(0, 160) || 'package.deb';
}

export function GitHubDirectRunnerApp() {
  const [token, setToken] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [device, setDevice] = useState<Device>('universal');
  const [minimumIos, setMinimumIos] = useState('15.0');
  const [displayName, setDisplayName] = useState('');
  const [bundleId, setBundleId] = useState('');
  const [jobs, setJobs] = useState<Job[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setToken(sessionStorage.getItem(TOKEN_STORAGE) || '');
    const saved = localStorage.getItem(JOB_STORAGE);
    if (saved) {
      try { setJobs(JSON.parse(saved)); } catch { /* ignore */ }
    }
  }, []);

  useEffect(() => {
    localStorage.setItem(JOB_STORAGE, JSON.stringify(jobs.slice(0, 20)));
  }, [jobs]);

  function saveToken(value: string) {
    setToken(value);
    if (value) sessionStorage.setItem(TOKEN_STORAGE, value);
    else sessionStorage.removeItem(TOKEN_STORAGE);
  }

  const github = useCallback(async (path: string, init: RequestInit = {}) => {
    if (!token) throw new Error('Enter a GitHub token first.');
    const response = await fetch(path.startsWith('http') ? path : `${API}${path}`, {
      ...init,
      cache: 'no-store',
      redirect: 'follow',
      headers: {
        Accept: 'application/vnd.github+json',
        Authorization: `Bearer ${token}`,
        'X-GitHub-Api-Version': '2022-11-28',
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...(init.headers || {}),
      },
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(`GitHub ${response.status}: ${detail.slice(0, 300)}`);
    }
    return response;
  }, [token]);

  const pollJob = useCallback(async (jobId: string) => {
    if (!token) return;
    try {
      const runsResponse = await github(`/actions/workflows/convert.yml/runs?event=workflow_dispatch&per_page=50`);
      const runsJson = await runsResponse.json() as { workflow_runs?: GitHubRun[] };
      const run = (runsJson.workflow_runs || []).find((item) => item.display_title.includes(jobId));
      if (!run) {
        setJobs((current) => current.map((job) => job.id === jobId ? {
          ...job,
          status: 'queued',
          progress: Math.max(job.progress, 33),
          stage: 'Waiting for GitHub to create the macOS job',
        } : job));
        return;
      }

      let progress = run.status === 'completed' ? 100 : 34;
      let stage = run.status === 'queued' ? 'GitHub macOS runner queued' : 'GitHub macOS runner working';
      let failedStep = '';
      const jobsResponse = await github(`/actions/runs/${run.id}/jobs?filter=latest`);
      const jobsJson = await jobsResponse.json() as { jobs?: Array<{ steps?: GitHubStep[] }> };
      const steps = (jobsJson.jobs || [])[0]?.steps || [];
      const active = steps.find((step) => step.status === 'in_progress')
        || steps.find((step) => step.status === 'queued')
        || [...steps].reverse().find((step) => step.status === 'completed');
      if (active) {
        progress = stageProgress[active.name] || progress;
        stage = stageLabels[active.name] || active.name;
      }
      const failed = steps.find((step) => step.conclusion === 'failure');
      if (failed) failedStep = failed.name;

      let artifact: Artifact | null = null;
      const artifactsResponse = await github(`/actions/runs/${run.id}/artifacts`);
      const artifactsJson = await artifactsResponse.json() as { artifacts?: Array<{ id: number; name: string; size_in_bytes: number; expired: boolean }> };
      const found = (artifactsJson.artifacts || []).find((item) => !item.expired && item.name.startsWith('DebtoIPA-'));
      if (found) artifact = { id: found.id, name: found.name, size: found.size_in_bytes };

      const status: JobStatus = run.status === 'completed'
        ? (run.conclusion === 'success' ? 'completed' : 'failed')
        : run.status === 'in_progress' ? 'in_progress' : 'queued';
      if (status === 'completed') stage = artifact ? 'IPA and reports ready' : 'Build passed; artifact is indexing';
      if (status === 'failed') stage = failedStep ? `${failedStep} failed` : 'GitHub build failed';

      setJobs((current) => current.map((job) => job.id === jobId ? {
        ...job,
        status,
        progress: status === 'completed' || status === 'failed' ? 100 : progress,
        stage,
        artifact,
        runUrl: run.html_url,
        error: status === 'failed' ? `${failedStep || 'The runner'} failed. Open the runner for logs; the artifact may contain a report.` : undefined,
      } : job));
    } catch (error) {
      setJobs((current) => current.map((job) => job.id === jobId ? {
        ...job,
        error: error instanceof Error ? error.message : 'Could not read runner status.',
      } : job));
    }
  }, [github, token]);

  useEffect(() => {
    const active = jobs.filter((job) => job.status === 'queued' || job.status === 'in_progress');
    if (!active.length || !token) return;
    const tick = () => active.forEach((job) => void pollJob(job.id));
    tick();
    const timer = window.setInterval(tick, 5000);
    return () => window.clearInterval(timer);
  }, [jobs.map((job) => `${job.id}:${job.status}`).join('|'), pollJob, token]);

  function choose(candidate?: File | null) {
    if (!candidate) return;
    if (!candidate.name.toLowerCase().endsWith('.deb')) {
      setNotice('Choose a file ending in .deb.');
      return;
    }
    if (candidate.size <= 0 || candidate.size > MAX_SIZE) {
      setNotice('The package must be between 1 byte and 750 MB.');
      return;
    }
    setNotice('');
    setFile(candidate);
  }

  async function deleteTemporaryBranch(branch: string) {
    try { await github(`/git/refs/heads/${branch}`, { method: 'DELETE' }); } catch { /* workflow also cleans up */ }
  }

  async function start() {
    if (!file || !token || busy) return;
    const source = file;
    const id = makeId();
    const branch = `debtoipa-upload-${id}`;
    const prefix = `uploads/${id}`;
    setBusy(true);
    setNotice('');
    setJobs((current) => [{
      id,
      fileName: source.name,
      createdAt: new Date().toISOString(),
      status: 'uploading',
      progress: 2,
      stage: 'Checking GitHub token permissions',
    }, ...current]);

    try {
      await github('https://api.github.com/user');
      const mainRefResponse = await github('/git/ref/heads/main');
      const mainRef = await mainRefResponse.json() as { object: { sha: string } };
      const mainCommitResponse = await github(`/git/commits/${mainRef.object.sha}`);
      const mainCommit = await mainCommitResponse.json() as { tree: { sha: string } };

      const partCount = Math.ceil(source.size / CHUNK_SIZE);
      if (partCount > 64) throw new Error('The package requires too many GitHub upload chunks.');
      const tree: Array<{ path: string; mode: string; type: string; sha: string }> = [];
      const parts: Array<{ path: string; size: number }> = [];

      for (let index = 0; index < partCount; index += 1) {
        const start = index * CHUNK_SIZE;
        const end = Math.min(source.size, start + CHUNK_SIZE);
        const bytes = new Uint8Array(await source.slice(start, end).arrayBuffer());
        const blobResponse = await github('/git/blobs', {
          method: 'POST',
          body: JSON.stringify({ content: bytesToBase64(bytes), encoding: 'base64' }),
        });
        const blob = await blobResponse.json() as { sha: string };
        const path = `${prefix}/parts/${index.toString().padStart(4, '0')}.bin`;
        tree.push({ path, mode: '100644', type: 'blob', sha: blob.sha });
        parts.push({ path, size: bytes.length });
        setJobs((current) => current.map((job) => job.id === id ? {
          ...job,
          progress: Math.min(28, 4 + Math.round(((index + 1) / partCount) * 24)),
          stage: `Uploading package to temporary GitHub objects · ${index + 1}/${partCount}`,
        } : job));
      }

      const metadata = {
        schemaVersion: 1,
        sourceName: safeFileName(source.name),
        size: source.size,
        chunkSize: CHUNK_SIZE,
        parts,
      };
      const manifestResponse = await github('/git/blobs', {
        method: 'POST',
        body: JSON.stringify({ content: JSON.stringify(metadata, null, 2), encoding: 'utf-8' }),
      });
      const manifest = await manifestResponse.json() as { sha: string };
      tree.push({ path: `${prefix}/manifest.json`, mode: '100644', type: 'blob', sha: manifest.sha });

      const treeResponse = await github('/git/trees', {
        method: 'POST',
        body: JSON.stringify({ base_tree: mainCommit.tree.sha, tree }),
      });
      const newTree = await treeResponse.json() as { sha: string };
      const commitResponse = await github('/git/commits', {
        method: 'POST',
        body: JSON.stringify({
          message: `Temporary DebToIPA upload ${id}`,
          tree: newTree.sha,
          parents: [mainRef.object.sha],
        }),
      });
      const commit = await commitResponse.json() as { sha: string };
      await github('/git/refs', {
        method: 'POST',
        body: JSON.stringify({ ref: `refs/heads/${branch}`, sha: commit.sha }),
      });

      setJobs((current) => current.map((job) => job.id === id ? {
        ...job,
        status: 'queued',
        progress: 31,
        stage: 'Dispatching GitHub macOS runner',
      } : job));

      try {
        await github('/actions/workflows/convert.yml/dispatches', {
          method: 'POST',
          body: JSON.stringify({
            ref: 'main',
            inputs: {
              source_kind: 'git_chunks',
              source_url: '',
              upload_ref: branch,
              upload_prefix: prefix,
              source_name: safeFileName(source.name),
              target_device: device,
              minimum_ios: minimumIos,
              bundle_id: bundleId,
              display_name: displayName,
              job_id: id,
            },
          }),
        });
      } catch (error) {
        await deleteTemporaryBranch(branch);
        throw error;
      }
      setFile(null);
    } catch (error) {
      setJobs((current) => current.map((job) => job.id === id ? {
        ...job,
        status: 'failed',
        progress: 100,
        stage: 'Could not start GitHub build',
        error: error instanceof Error ? error.message : 'Could not start GitHub build.',
      } : job));
    } finally {
      setBusy(false);
    }
  }

  async function downloadArtifact(artifact: Artifact) {
    setNotice('');
    try {
      const response = await github(`/actions/artifacts/${artifact.id}/zip`);
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
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
      <div className="brand"><div className="brand-mark">✦</div><div><strong>DebToIPA</strong><span>Direct GitHub macOS builds</span></div></div>
      <div className="runner-pill"><span/>Runner mode</div>
    </header>
    <div className="content">
      <section className="view">
        <div className="hero-copy"><p className="eyebrow">NO BROWSER CONVERSION</p><h1>Upload to GitHub. <span>Build on macOS.</span></h1><p>The package is split into temporary Git objects, rebuilt by GitHub Actions, then deleted. Direct-compatible apps keep their original binary; blocked apps compile a stock-iOS replacement host.</p></div>
        <div className="settings-card">
          <div className="section-title"><div><p className="eyebrow">GITHUB ACCESS</p><h2>Runner authorization</h2></div><span>⌘</span></div>
          <div className="field-grid"><label className="full"><span>Fine-grained GitHub token</span><input value={token} onChange={(event) => saveToken(event.target.value.trim())} type="password" autoCapitalize="none" autoCorrect="off" placeholder="Contents + Actions read/write"/></label></div>
          <p className="helper-text">Stored only in this browser tab. It is sent directly to api.github.com, not saved by DebToIPA.</p>
        </div>
        <button className={`upload-zone ${file ? 'has-file' : ''}`} onClick={() => inputRef.current?.click()}>
          <input ref={inputRef} type="file" hidden onChange={(event) => choose(event.target.files?.[0])}/>
          <div className="upload-icon">{file ? '✓' : '⇧'}</div><strong>{file?.name || 'Choose a Debian package'}</strong><span>{file ? `${(file.size / 1048576).toFixed(1)} MB · ready` : 'iPhone Files · up to 750 MB'}</span>
        </button>
        <div className="settings-card"><div className="section-title"><div><p className="eyebrow">TARGET</p><h2>Build settings</h2></div><span>⚙</span></div><div className="segmented">{(['universal','iphone','ipad'] as Device[]).map((value) => <button key={value} className={device === value ? 'active' : ''} onClick={() => setDevice(value)}>{value === 'universal' ? 'Universal' : value === 'iphone' ? 'iPhone' : 'iPad'}</button>)}</div><div className="field-grid"><label><span>Minimum iOS</span><input value={minimumIos} onChange={(event) => setMinimumIos(event.target.value)} inputMode="decimal"/></label><label><span>Display name <em>optional</em></span><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="Keep original"/></label><label className="full"><span>Bundle ID <em>optional</em></span><input value={bundleId} onChange={(event) => setBundleId(event.target.value)} placeholder="com.example.portedapp" autoCapitalize="none"/></label></div></div>
        {notice && <div className="notice">ⓘ <span>{notice}</span></div>}
        <button className="primary convert-button" disabled={!file || !token || busy} onClick={start}>⚡ {busy ? 'Uploading to GitHub…' : 'Build on GitHub macOS'}</button>
        <div className="truth-card"><p><strong>Technical boundary:</strong> runners compile replacement source; they cannot recover a missing private entitlement or recreate arbitrary system hooks from machine code. The result report marks direct, feature-complete replacement, or partial replacement.</p></div>
      </section>
      <section className="view"><div className="view-heading"><div><p className="eyebrow">RUNNER ACTIVITY</p><h1>Build jobs</h1></div><span>{jobs.length}</span></div>{!jobs.length && <div className="empty-state"><div className="upload-icon">▤</div><h2>No builds yet</h2><p>Upload progress and every GitHub runner stage appear here.</p></div>}<div className="job-list">{jobs.map((job) => <article className="job-card" key={job.id}><div className="job-top"><div className={`job-status ${job.status}`}>{job.status === 'completed' ? '✓' : job.status === 'failed' ? '!' : '▤'}</div><div className="job-name"><strong>{job.fileName}</strong><span>{new Date(job.createdAt).toLocaleString()}</span></div><span className={`status-label ${job.status}`}>{job.status.replace('_',' ')}</span></div><div className="progress-track"><span style={{width: `${job.progress}%`}}/></div><div className="job-meta"><span>{job.stage}</span><strong>{job.progress}%</strong></div>{job.error && <p className="job-error">{job.error}</p>}<div className="job-actions">{job.artifact && <button className="primary compact" onClick={() => void downloadArtifact(job.artifact!)}>⇩ Download IPA + reports</button>}{job.runUrl && <a className="secondary compact" href={job.runUrl} target="_blank" rel="noreferrer">Open runner</a>}</div></article>)}</div></section>
    </div>
  </main>;
}
