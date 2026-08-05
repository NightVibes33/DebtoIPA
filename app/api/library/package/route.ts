import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const MAX_PACKAGE_BYTES = 250 * 1024 * 1024;

type LibraryPackage = {
  id: string;
  title: string;
  package: string;
  version: string;
  sourceId: string;
  sourceName: string;
  sourceHomepage: string;
  downloadPolicy: string;
  downloadUrl: string | null;
  size: number;
  sha256: string;
};

type LibraryIndex = {
  packages: LibraryPackage[];
};

function safeFileName(value: string): string {
  const cleaned = value.replace(/[^A-Za-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '');
  return `${cleaned || 'package'}.deb`;
}

async function readIndex(): Promise<LibraryIndex> {
  const indexPath = path.join(process.cwd(), 'public', 'library', 'index.json');
  const raw = await readFile(indexPath, 'utf8');
  return JSON.parse(raw) as LibraryIndex;
}

export async function GET(request: NextRequest) {
  const id = request.nextUrl.searchParams.get('id')?.trim() ?? '';
  if (!/^[a-f0-9]{24}$/.test(id)) {
    return NextResponse.json({ error: 'Invalid package identifier.' }, { status: 400 });
  }

  const index = await readIndex();
  const item = index.packages.find((candidate) => candidate.id === id);
  if (!item) {
    return NextResponse.json({ error: 'Package was not found in the current library snapshot.' }, { status: 404 });
  }
  if (item.downloadPolicy !== 'direct' || !item.downloadUrl) {
    return NextResponse.json(
      {
        error:
          item.downloadPolicy === 'purchase-required'
            ? 'This package requires a legitimate purchase or repository authentication.'
            : item.downloadPolicy === 'blocked'
              ? 'This package is blocked from direct loading by the library policy.'
              : 'This source is catalog-only. Open the original repository for package access.',
        source: item.sourceHomepage,
      },
      { status: 403 },
    );
  }

  let target: URL;
  try {
    target = new URL(item.downloadUrl);
  } catch {
    return NextResponse.json({ error: 'The catalog contains an invalid package URL.' }, { status: 502 });
  }
  if (target.protocol !== 'https:') {
    return NextResponse.json({ error: 'Only HTTPS package downloads are accepted.' }, { status: 502 });
  }

  const upstream = await fetch(target, {
    cache: 'no-store',
    redirect: 'follow',
    headers: {
      'User-Agent': 'DebToIPA-Library/1.0 (+https://github.com/NightVibes33/DebtoIPA)',
      Accept: 'application/vnd.debian.binary-package,application/octet-stream,*/*',
    },
  });
  if (!upstream.ok || !upstream.body) {
    return NextResponse.json(
      { error: `The original repository returned HTTP ${upstream.status}.` },
      { status: 502 },
    );
  }

  const finalUrl = new URL(upstream.url);
  const blockedHost = /^(?:localhost|0\.0\.0\.0|127(?:\.\d{1,3}){3}|10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|169\.254(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}|::1)$/i;
  if (finalUrl.protocol !== 'https:' || blockedHost.test(finalUrl.hostname) || finalUrl.hostname.endsWith('.local')) {
    await upstream.body.cancel();
    return NextResponse.json({ error: 'The package redirected to an unsafe host.' }, { status: 502 });
  }

  const contentLength = Number(upstream.headers.get('content-length') || item.size || 0);
  if (Number.isFinite(contentLength) && contentLength > MAX_PACKAGE_BYTES) {
    await upstream.body.cancel();
    return NextResponse.json({ error: 'The package exceeds the 250 MB limit.' }, { status: 413 });
  }

  let received = 0;
  const limiter = new TransformStream<Uint8Array, Uint8Array>({
    transform(chunk, controller) {
      received += chunk.byteLength;
      if (received > MAX_PACKAGE_BYTES) {
        controller.error(new Error('Package exceeded the 250 MB limit.'));
        return;
      }
      controller.enqueue(chunk);
    },
  });
  const limitedBody = upstream.body.pipeThrough(limiter);
  const fileName = safeFileName(`${item.package}_${item.version}`);
  const headers: Record<string, string> = {
      'Content-Type': 'application/vnd.debian.binary-package',
      'Content-Disposition': `attachment; filename=\"${fileName}\"`,
      'Cache-Control': 'private, no-store, max-age=0',
      'X-Content-Type-Options': 'nosniff',
      'X-DebToIPA-Source': item.sourceId,
      'X-DebToIPA-SHA256': item.sha256 || 'unknown',
  };
  if (contentLength > 0) headers['Content-Length'] = String(contentLength);
  return new NextResponse(limitedBody, {
    status: 200,
    headers,
  });
}
