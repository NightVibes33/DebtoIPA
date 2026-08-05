import { NextResponse } from 'next/server';
import { assertAccessCode, githubConfig, githubFetch } from '@/lib/github';

type Device = 'universal' | 'iphone' | 'ipad';

type JobBody = {
  sourceUrl?: string;
  sourceName?: string;
  targetDevice?: Device;
  minimumIos?: string;
  bundleId?: string;
  displayName?: string;
  jobId?: string;
};

function cleanText(value: unknown, max: number) {
  return typeof value === 'string' ? value.trim().slice(0, max) : '';
}

function validBlobUrl(raw: string) {
  try {
    const url = new URL(raw);
    return url.protocol === 'https:' && (
      url.hostname.endsWith('.public.blob.vercel-storage.com') ||
      url.hostname === 'public.blob.vercel-storage.com'
    );
  } catch {
    return false;
  }
}

export async function POST(request: Request) {
  try {
    assertAccessCode(request);
    const body = (await request.json()) as JobBody;
    const sourceUrl = cleanText(body.sourceUrl, 2048);
    const sourceName = cleanText(body.sourceName, 180) || 'package.deb';
    const targetDevice: Device = ['universal', 'iphone', 'ipad'].includes(body.targetDevice || '')
      ? (body.targetDevice as Device)
      : 'universal';
    const minimumIos = /^\d{1,2}(\.\d{1,2}){0,2}$/.test(body.minimumIos || '') ? body.minimumIos! : '15.0';
    const bundleId = cleanText(body.bundleId, 120);
    const displayName = cleanText(body.displayName, 80);
    const jobId = cleanText(body.jobId, 64);

    if (!jobId || !/^[a-zA-Z0-9_-]+$/.test(jobId)) throw new Error('Invalid job id.');
    if (!validBlobUrl(sourceUrl)) throw new Error('The source must be a Vercel public Blob URL.');
    if (!sourceName.toLowerCase().endsWith('.deb')) throw new Error('The source file must end in .deb.');
    if (bundleId && !/^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$/.test(bundleId)) throw new Error('Bundle ID is invalid.');

    const { owner, repo } = githubConfig();
    const response = await githubFetch(`/repos/${owner}/${repo}/actions/workflows/convert.yml/dispatches`, {
      method: 'POST',
      body: JSON.stringify({
        ref: 'main',
        inputs: {
          source_url: sourceUrl,
          source_name: sourceName,
          target_device: targetDevice,
          minimum_ios: minimumIos,
          bundle_id: bundleId,
          display_name: displayName,
          job_id: jobId,
        },
      }),
    });

    if (!response.ok) {
      const detail = await response.text();
      throw new Error(`GitHub rejected the job (${response.status}): ${detail.slice(0, 240)}`);
    }

    return NextResponse.json({ ok: true, jobId, status: 'queued' }, { status: 202 });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : 'Could not queue conversion.' }, { status: 400 });
  }
}
