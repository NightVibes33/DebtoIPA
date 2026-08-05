import { NextResponse } from 'next/server';
import { assertAccessCode, githubConfig, githubFetch } from '@/lib/github';

export async function GET(request: Request, context: { params: Promise<{ jobId: string }> }) {
  try {
    assertAccessCode(request);
    const { jobId } = await context.params;
    if (!/^[a-zA-Z0-9_-]{1,64}$/.test(jobId)) throw new Error('Invalid job id.');
    const { owner, repo } = githubConfig();

    const runsResponse = await githubFetch(
      `/repos/${owner}/${repo}/actions/workflows/convert.yml/runs?event=workflow_dispatch&per_page=50`,
    );
    if (!runsResponse.ok) throw new Error(`Could not read workflow runs (${runsResponse.status}).`);
    const runsJson = await runsResponse.json() as { workflow_runs?: Array<Record<string, unknown>> };
    const run = (runsJson.workflow_runs || []).find((item) =>
      String(item.display_title || '').includes(jobId),
    );

    if (!run) return NextResponse.json({ jobId, status: 'queued', conclusion: null });

    let artifact = null as null | { id: number; name: string; size: number; downloadUrl: string };
    if (run.id && (run.status === 'completed' || run.status === 'in_progress')) {
      const artifactsResponse = await githubFetch(`/repos/${owner}/${repo}/actions/runs/${run.id}/artifacts`);
      if (artifactsResponse.ok) {
        const data = await artifactsResponse.json() as { artifacts?: Array<{ id: number; name: string; size_in_bytes: number; expired: boolean }> };
        const found = (data.artifacts || []).find((item) => !item.expired && item.name.startsWith('DebtoIPA-'));
        if (found) artifact = {
          id: found.id,
          name: found.name,
          size: found.size_in_bytes,
          downloadUrl: `/api/artifacts/${found.id}`,
        };
      }
    }

    return NextResponse.json({
      jobId,
      runId: run.id,
      status: run.status,
      conclusion: run.conclusion,
      createdAt: run.created_at,
      updatedAt: run.updated_at,
      htmlUrl: run.html_url,
      artifact,
    });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : 'Could not read job.' }, { status: 400 });
  }
}
