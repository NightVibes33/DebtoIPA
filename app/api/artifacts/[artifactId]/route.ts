import { assertAccessCode, githubConfig, githubFetch } from '@/lib/github';

export const runtime = 'nodejs';

export async function GET(request: Request, context: { params: Promise<{ artifactId: string }> }) {
  try {
    assertAccessCode(request);
    const { artifactId } = await context.params;
    if (!/^\d+$/.test(artifactId)) return new Response('Invalid artifact id.', { status: 400 });
    const { owner, repo } = githubConfig();
    const response = await githubFetch(`/repos/${owner}/${repo}/actions/artifacts/${artifactId}/zip`);
    if (!response.ok || !response.body) return new Response('Artifact not found or expired.', { status: response.status || 404 });
    return new Response(response.body, {
      status: 200,
      headers: {
        'Content-Type': 'application/zip',
        'Content-Disposition': `attachment; filename="DebtoIPA-${artifactId}.zip"`,
        'Cache-Control': 'private, no-store',
      },
    });
  } catch (error) {
    return new Response(error instanceof Error ? error.message : 'Download failed.', { status: 400 });
  }
}
