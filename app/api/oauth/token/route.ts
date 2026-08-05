import { NextResponse } from 'next/server';
import { githubOAuthClientId } from '@/lib/github-oauth';

export const runtime = 'nodejs';

type RequestBody = { deviceCode?: string };

export async function POST(request: Request) {
  try {
    const body = await request.json() as RequestBody;
    const deviceCode = String(body.deviceCode || '').trim();
    if (!/^[A-Za-z0-9_-]{20,200}$/.test(deviceCode)) {
      return NextResponse.json({ error: 'Invalid device code.' }, { status: 400 });
    }
    const clientId = await githubOAuthClientId();
    const response = await fetch('https://github.com/login/oauth/access_token', {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded',
        'User-Agent': 'DebToIPA-Public-Runner',
      },
      body: new URLSearchParams({
        client_id: clientId,
        device_code: deviceCode,
        grant_type: 'urn:ietf:params:oauth:grant-type:device_code',
      }),
      cache: 'no-store',
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error_description || data.error || `GitHub returned ${response.status}.`);
    }
    if (data.error) {
      return NextResponse.json({
        pending: data.error === 'authorization_pending' || data.error === 'slow_down',
        slowDown: data.error === 'slow_down',
        error: data.error,
        errorDescription: data.error_description,
      }, { status: 202, headers: { 'Cache-Control': 'no-store' } });
    }
    if (!data.access_token) throw new Error('GitHub did not return an access token.');
    return NextResponse.json({
      accessToken: data.access_token,
      tokenType: data.token_type || 'bearer',
      scope: data.scope || '',
    }, { headers: { 'Cache-Control': 'no-store' } });
  } catch (error) {
    return NextResponse.json({
      error: error instanceof Error ? error.message : 'GitHub login could not be completed.',
    }, { status: 400 });
  }
}
