import { handleUpload, type HandleUploadBody } from '@vercel/blob/client';
import { NextResponse } from 'next/server';

export const runtime = 'nodejs';

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as HandleUploadBody;
    const result = await handleUpload({
      body,
      request,
      onBeforeGenerateToken: async (pathname, clientPayload) => {
        const expected = process.env.APP_ACCESS_CODE;
        if (expected) {
          let supplied = '';
          try { supplied = String(JSON.parse(clientPayload || '{}').accessCode || ''); } catch { /* invalid payload */ }
          if (supplied !== expected) throw new Error('Invalid access code.');
        }
        if (!pathname.toLowerCase().endsWith('.deb')) {
          throw new Error('Only .deb packages are accepted.');
        }
        return {
          allowedContentTypes: [
            'application/vnd.debian.binary-package',
            'application/x-debian-package',
            'application/octet-stream',
          ],
          maximumSizeInBytes: 750 * 1024 * 1024,
          addRandomSuffix: true,
          tokenPayload: JSON.stringify({ kind: 'deb-source' }),
        };
      },
      onUploadCompleted: async ({ blob }) => {
        console.info('Deb upload completed', blob.pathname);
      },
    });
    return NextResponse.json(result);
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : 'Upload failed.' }, { status: 400 });
  }
}
