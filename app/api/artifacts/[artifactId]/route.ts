import { assertAccessCode, githubConfig, githubFetch } from '@/lib/github';

export const runtime = 'nodejs';

type ArtifactMetadata = {
  name?: string;
  expired?: boolean;
};

export async function GET(request: Request, context: { params: Promise<{ artifactId: string }> }) {
  try {
    assertAccessCode(request);
    const { artifactId } = await context.params;
    if (!/^\d+$/.test(artifactId)) return new Response('Invalid artifact id.', { status: 400 });

    const { owner, repo } = githubConfig();
    const metadataResponse = await githubFetch(`/repos/${owner}/${repo}/actions/artifacts/${artifactId}`);
    if (!metadataResponse.ok) return new Response('Artifact not found.', { status: metadataResponse.status || 404 });

    const metadata = (await metadataResponse.json()) as ArtifactMetadata;
    if (metadata.expired) return new Response('Artifact has expired.', { status: 410 });
    if (!metadata.name?.startsWith('DebtoIPA-')) {
      return new Response('Artifact is not a DebtoIPA conversion result.', { status: 403 });
    }

    const response = await githubFetch(`/repos/${owner}/${repo}/actions/artifacts/${artifactId}/zip`);
    if (!response.ok || !response.body) return new Response('Artifact not found or expired.', { status: response.status || 404 });

    const safeName = metadata.name.replace(/[^a-zA-Z0-9._-]/g, '-');
    return new Response(response.body, {
      status: 200,
      headers: {
        'Content-Type': 'application/zip',
        'Content-Disposition': `attachment; filename="${safeName}.zip"`,
        'Cache-Control': 'private, no-store',
        'X-Content-Type-Options': 'nosniff',
      },
    });
  } catch (error) {
    return new Response(error instanceof Error ? error.message : 'Download failed.', { status: 400 });
  }
}
