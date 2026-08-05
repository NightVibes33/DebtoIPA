'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import styles from '@/app/library/library.module.css';

type SourceSummary = {
  id: string;
  name: string;
  homepage: string;
  policy: string;
  notes: string;
  packageCount: number;
  status: string;
};

type LibraryPackage = {
  id: string;
  title: string;
  package: string;
  version: string;
  description: string;
  author: string;
  section: string;
  architecture: string;
  tags: string[];
  depends: string;
  homepage: string;
  sourceId: string;
  sourceName: string;
  sourceHomepage: string;
  sourcePolicy: string;
  downloadPolicy: 'direct' | 'source-only' | 'metadata-only' | 'purchase-required' | 'blocked';
  bundleEligible: boolean;
  commercial: boolean;
  riskFlags: string[];
  conversion: {
    class: string;
    score: number;
    reason: string;
  };
};

type LibraryIndex = {
  schemaVersion: number;
  generatedAt: string | null;
  packageCount: number;
  sourceCount: number;
  readySourceCount: number;
  directPackageCount: number;
  blockedPackageCount: number;
  bundleEligibleCount: number;
  notice: string;
  sources: SourceSummary[];
  packages: LibraryPackage[];
};

const PAGE_SIZE = 60;

function formatCount(value: number): string {
  return new Intl.NumberFormat().format(value || 0);
}

function policyLabel(policy: LibraryPackage['downloadPolicy']): string {
  return {
    direct: 'Ready to load',
    'source-only': 'Catalog only',
    'metadata-only': 'Metadata only',
    'purchase-required': 'Purchase required',
    blocked: 'Blocked',
  }[policy];
}

function safeFileName(item: LibraryPackage): string {
  const base = `${item.package}_${item.version}`.replace(/[^A-Za-z0-9._-]+/g, '-');
  return `${base || 'package'}.deb`;
}

export default function DebLibraryApp() {
  const [index, setIndex] = useState<LibraryIndex | null>(null);
  const [loadError, setLoadError] = useState('');
  const [query, setQuery] = useState('');
  const [source, setSource] = useState('all');
  const [section, setSection] = useState('all');
  const [loadableOnly, setLoadableOnly] = useState(false);
  const [page, setPage] = useState(0);
  const [tab, setTab] = useState<'library' | 'builder'>('library');
  const [selected, setSelected] = useState<LibraryPackage | null>(null);
  const [loadingId, setLoadingId] = useState('');
  const [actionError, setActionError] = useState('');
  const [injectedName, setInjectedName] = useState('');
  const iframeRef = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    let cancelled = false;
    fetch('/library/index.json', { cache: 'no-store' })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Library returned HTTP ${response.status}`);
        return (await response.json()) as LibraryIndex;
      })
      .then((value) => {
        if (!cancelled) setIndex(value);
      })
      .catch((error: unknown) => {
        if (!cancelled) setLoadError(error instanceof Error ? error.message : String(error));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const sections = useMemo(() => {
    const values = new Set<string>();
    for (const item of index?.packages ?? []) values.add(item.section || 'Other');
    return [...values].sort((a, b) => a.localeCompare(b)).slice(0, 120);
  }, [index]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (index?.packages ?? []).filter((item) => {
      if (source !== 'all' && item.sourceId !== source) return false;
      if (section !== 'all' && item.section !== section) return false;
      if (loadableOnly && item.downloadPolicy !== 'direct') return false;
      if (!needle) return true;
      return [
        item.title,
        item.package,
        item.description,
        item.author,
        item.section,
        item.sourceName,
        item.version,
      ]
        .join(' ')
        .toLowerCase()
        .includes(needle);
    });
  }, [index, loadableOnly, query, section, source]);

  useEffect(() => setPage(0), [query, source, section, loadableOnly]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const visible = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  async function waitForBuilderInput(): Promise<HTMLInputElement> {
    for (let attempt = 0; attempt < 100; attempt += 1) {
      const input = iframeRef.current?.contentDocument?.getElementById('file');
      if (input instanceof HTMLInputElement) return input;
      await new Promise((resolve) => window.setTimeout(resolve, 100));
    }
    throw new Error('The converter did not finish loading.');
  }

  async function loadIntoBuilder(item: LibraryPackage) {
    setActionError('');
    setLoadingId(item.id);
    try {
      const response = await fetch(`/api/library/package?id=${encodeURIComponent(item.id)}`, {
        cache: 'no-store',
      });
      if (!response.ok) {
        const payload = (await response.json().catch(() => ({}))) as { error?: string };
        throw new Error(payload.error || `Package download returned HTTP ${response.status}`);
      }
      const blob = await response.blob();
      const file = new File([blob], safeFileName(item), {
        type: 'application/vnd.debian.binary-package',
        lastModified: Date.now(),
      });
      setTab('builder');
      const input = await waitForBuilderInput();
      const transfer = new DataTransfer();
      transfer.items.add(file);
      input.files = transfer.files;
      input.dispatchEvent(new Event('change', { bubbles: true }));
      setInjectedName(file.name);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoadingId('');
    }
  }

  function openSource(item: LibraryPackage) {
    const target = item.homepage || item.sourceHomepage;
    window.open(target, '_blank', 'noopener,noreferrer');
  }

  return (
    <main className={styles.shell}>
      <header className={styles.header}>
        <div className={styles.brand}>
          <div className={styles.mark}>✦</div>
          <div>
            <strong>DebToIPA Library</strong>
            <span>Thousands of public DEBs, one conversion builder</span>
          </div>
        </div>
        <nav className={styles.tabs} aria-label="App sections">
          <button className={tab === 'library' ? styles.activeTab : ''} onClick={() => setTab('library')}>
            Library
          </button>
          <button className={tab === 'builder' ? styles.activeTab : ''} onClick={() => setTab('builder')}>
            Builder {injectedName ? <i>1</i> : null}
          </button>
        </nav>
      </header>

      <section className={`${styles.libraryPanel} ${tab === 'library' ? styles.visible : ''}`}>
        <div className={styles.hero}>
          <p>PUBLIC APT CATALOG</p>
          <h1>
            Find a DEB. <span>Choose how to turn it into an IPA.</span>
          </h1>
          <div className={styles.statGrid}>
            <div><strong>{formatCount(index?.packageCount ?? 0)}</strong><span>packages indexed</span></div>
            <div><strong>{formatCount(index?.directPackageCount ?? 0)}</strong><span>loadable from source</span></div>
            <div><strong>{formatCount(index?.readySourceCount ?? 0)}</strong><span>repositories online</span></div>
            <div><strong>{formatCount(index?.bundleEligibleCount ?? 0)}</strong><span>open-license candidates</span></div>
          </div>
        </div>

        <div className={styles.notice}>
          <strong>CyPwn is included.</strong> Its metadata appears in search, but CyPwn and other mixed repositories stay catalog-only because they advertise cracks or packages with unclear redistribution rights. Paid packages still require a legitimate purchase.
        </div>

        <div className={styles.toolbar}>
          <label className={styles.search}>
            <span>⌕</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search package, tweak, app, author, or bundle ID"
            />
          </label>
          <select value={source} onChange={(event) => setSource(event.target.value)} aria-label="Repository">
            <option value="all">All repositories</option>
            {(index?.sources ?? []).map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} ({formatCount(item.packageCount)})
              </option>
            ))}
          </select>
          <select value={section} onChange={(event) => setSection(event.target.value)} aria-label="Section">
            <option value="all">All sections</option>
            {sections.map((item) => <option key={item}>{item}</option>)}
          </select>
          <label className={styles.check}>
            <input
              type="checkbox"
              checked={loadableOnly}
              onChange={(event) => setLoadableOnly(event.target.checked)}
            />
            Loadable only
          </label>
        </div>

        <div className={styles.resultsHeading}>
          <div>
            <strong>{formatCount(filtered.length)} results</strong>
            <span>{index?.generatedAt ? `Snapshot ${new Date(index.generatedAt).toLocaleString()}` : 'Initial sync pending'}</span>
          </div>
          <div className={styles.pager}>
            <button disabled={page <= 0} onClick={() => setPage((value) => Math.max(0, value - 1))}>←</button>
            <span>{page + 1} / {pageCount}</span>
            <button disabled={page + 1 >= pageCount} onClick={() => setPage((value) => Math.min(pageCount - 1, value + 1))}>→</button>
          </div>
        </div>

        {loadError ? <div className={styles.error}>{loadError}</div> : null}
        {!index ? <div className={styles.loading}>Loading the repository snapshot…</div> : null}
        {index && index.packageCount === 0 ? (
          <div className={styles.loading}>The first repository sync is being generated. The source registry is installed, but its package snapshot has not been committed yet.</div>
        ) : null}
        {actionError ? <div className={styles.error}>{actionError}</div> : null}

        <div className={styles.grid}>
          {visible.map((item) => (
            <article key={item.id} className={styles.card}>
              <button className={styles.cardMain} onClick={() => setSelected(item)}>
                <div className={styles.cardTop}>
                  <span className={styles.packageIcon}>{item.title.slice(0, 1).toUpperCase()}</span>
                  <div>
                    <strong>{item.title}</strong>
                    <small>{item.package}</small>
                  </div>
                  <b className={`${styles.score} ${item.conversion.score >= 60 ? styles.good : item.conversion.score >= 30 ? styles.maybe : styles.low}`}>
                    {item.conversion.score}%
                  </b>
                </div>
                <p>{item.description || item.conversion.reason}</p>
                <div className={styles.badges}>
                  <span>{item.sourceName}</span>
                  <span>{item.section}</span>
                  <span>{item.architecture}</span>
                  {item.bundleEligible ? <span className={styles.openBadge}>Open license</span> : null}
                </div>
              </button>
              <div className={styles.cardActions}>
                <button
                  className={item.downloadPolicy === 'direct' ? styles.primary : styles.secondary}
                  disabled={loadingId === item.id || item.downloadPolicy === 'blocked'}
                  onClick={() => item.downloadPolicy === 'direct' ? loadIntoBuilder(item) : openSource(item)}
                >
                  {loadingId === item.id ? 'Loading DEB…' : item.downloadPolicy === 'direct' ? 'Load in builder' : policyLabel(item.downloadPolicy)}
                </button>
                <button className={styles.iconButton} onClick={() => setSelected(item)} aria-label={`Details for ${item.title}`}>ⓘ</button>
              </div>
            </article>
          ))}
        </div>

        <div className={styles.footerPager}>
          <button disabled={page <= 0} onClick={() => { setPage((value) => Math.max(0, value - 1)); window.scrollTo({ top: 350, behavior: 'smooth' }); }}>Previous</button>
          <span>Showing {filtered.length ? page * PAGE_SIZE + 1 : 0}–{Math.min((page + 1) * PAGE_SIZE, filtered.length)} of {formatCount(filtered.length)}</span>
          <button disabled={page + 1 >= pageCount} onClick={() => { setPage((value) => Math.min(pageCount - 1, value + 1)); window.scrollTo({ top: 350, behavior: 'smooth' }); }}>Next</button>
        </div>
      </section>

      <section className={`${styles.builderPanel} ${tab === 'builder' ? styles.visible : ''}`}>
        <div className={styles.builderBar}>
          <div>
            <strong>{injectedName ? `${injectedName} is loaded` : 'Conversion builder'}</strong>
            <span>{injectedName ? 'Sign in, select the conversion profile, and start the build.' : 'Choose a package from the library or upload your own DEB.'}</span>
          </div>
          <button onClick={() => setTab('library')}>Browse library</button>
        </div>
        <iframe ref={iframeRef} className={styles.builderFrame} src="/public-runner.html?embedded=1" title="DebToIPA conversion builder" />
      </section>

      {selected ? (
        <div className={styles.modalBackdrop} onClick={() => setSelected(null)}>
          <article className={styles.modal} onClick={(event) => event.stopPropagation()}>
            <button className={styles.close} onClick={() => setSelected(null)}>×</button>
            <p className={styles.eyebrow}>{selected.sourceName} · {selected.section}</p>
            <h2>{selected.title}</h2>
            <code>{selected.package}</code>
            <p>{selected.description || 'No package description was supplied by the repository.'}</p>
            <dl>
              <div><dt>Version</dt><dd>{selected.version}</dd></div>
              <div><dt>Architecture</dt><dd>{selected.architecture}</dd></div>
              <div><dt>Author</dt><dd>{selected.author}</dd></div>
              <div><dt>Preflight score</dt><dd>{selected.conversion.score}%</dd></div>
              <div><dt>Prediction</dt><dd>{selected.conversion.class.replaceAll('-', ' ')}</dd></div>
              <div><dt>Access</dt><dd>{policyLabel(selected.downloadPolicy)}</dd></div>
            </dl>
            <div className={styles.reason}>{selected.conversion.reason}</div>
            {selected.riskFlags.length ? <div className={styles.risks}>Flags: {selected.riskFlags.join(', ')}</div> : null}
            <div className={styles.modalActions}>
              <button
                className={selected.downloadPolicy === 'direct' ? styles.primary : styles.secondary}
                disabled={loadingId === selected.id || selected.downloadPolicy === 'blocked'}
                onClick={() => selected.downloadPolicy === 'direct' ? loadIntoBuilder(selected) : openSource(selected)}
              >
                {selected.downloadPolicy === 'direct' ? 'Load this DEB in builder' : policyLabel(selected.downloadPolicy)}
              </button>
              <button className={styles.secondary} onClick={() => openSource(selected)}>Open repository</button>
            </div>
          </article>
        </div>
      ) : null}
    </main>
  );
}
