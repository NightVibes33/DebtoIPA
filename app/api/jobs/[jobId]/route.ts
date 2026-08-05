import { NextResponse } from 'next/server';
import { assertAccessCode, githubConfig, githubFetch } from '@/lib/github';

type WorkflowStep = { name?: string; status?: string; conclusion?: string | null; number?: number };
type WorkflowJob = { status?: string; conclusion?: string | null; steps?: WorkflowStep[] };

const stageProgress: Record<string, number> = {
  'Set up job': 35,
  'Checkout DebToIPA': 40,
  'Validate upload URL': 44,
  'Download Debian package': 50,
  'Audit package and choose build path': 57,
  'Build and validate IPA': 82,
  'Publish runner summary': 90,
  'Upload IPA, Port Project, and reports': 97,
  'Fail unusable build': 100,
  'Complete job': 100,
};

function stageLabel(name: string, status: string) {
  const labels: Record<string, string> = {
    'Set up job': 'Starting GitHub macOS runner',
    'Checkout DebToIPA': 'Loading converter and compatibility runtime',
    'Validate upload URL': 'Validating uploaded package location',
    'Download Debian package': 'Downloading package to macOS runner',
    'Audit package and choose build path': 'Auditing every app, helper, daemon, and entitlement',
    'Build and validate IPA': 'Packaging direct IPA or compiling stock-iOS replacement host',
    'Publish runner summary': 'Writing compatibility and feature-completeness report',
    'Upload IPA, Port Project, and reports': 'Uploading IPA and reports',
    'Fail unusable build': 'Build rejected as unusable',
    'Complete job': 'Artifact ready',
  };
  const label = labels[name] || name || 'GitHub runner working';
  return status === 'completed' ? `${label} · complete` : label;
}

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
    const run = (runsJson.workflow_runs || []).find((item) => String(item.display_title || '').includes(jobId));

    if (!run) return NextResponse.json({
      jobId,
      status: 'queued',
      conclusion: null,
      progress: 33,
      stage: 'Waiting for GitHub to create the macOS runner job',
    });

    let stage = run.status === 'completed' ? 'Runner finished' : 'GitHub runner queued';
    let progress = run.status === 'completed' ? 100 : 34;
    let failedStep = '';

    if (run.id) {
      const jobsResponse = await githubFetch(`/repos/${owner}/${repo}/actions/runs/${run.id}/jobs?filter=latest`);
      if (jobsResponse.ok) {
        const jobsData = await jobsResponse.json() as { jobs?: WorkflowJob[] };
        const job = (jobsData.jobs || [])[0];
        const steps = job?.steps || [];
        const active = steps.find((item) => item.status === 'in_progress')
          || steps.find((item) => item.status === 'queued')
          || [...steps].reverse().find((item) => item.status === 'completed');
        if (active) {
          const name = String(active.name || 'GitHub runner working');
          stage = stageLabel(name, String(active.status || ''));
          progress = stageProgress[name] || progress;
        }
        const failed = steps.find((item) => item.conclusion === 'failure');
        if (failed) failedStep = String(failed.name || 'Runner step');
      }
    }

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

    if (run.status === 'completed' && run.conclusion === 'success') {
      stage = artifact ? 'IPA and compatibility report ready' : 'Runner succeeded; artifact is still indexing';
      progress = 100;
    } else if (run.status === 'completed' && run.conclusion !== 'success') {
      stage = failedStep ? `${failedStep} failed` : 'GitHub runner failed';
      progress = 100;
    }

    return NextResponse.json({
      jobId,
      runId: run.id,
      status: run.status,
      conclusion: run.conclusion,
      progress,
      stage,
      error: run.status === 'completed' && run.conclusion !== 'success'
        ? `${failedStep || 'The runner'} failed. Download the artifact for runner-summary.json when available.`
        : undefined,
      createdAt: run.created_at,
      updatedAt: run.updated_at,
      htmlUrl: run.html_url,
      artifact,
    });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : 'Could not read job.' }, { status: 400 });
  }
}
