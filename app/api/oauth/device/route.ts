import { NextResponse } from 'next/server';
import { githubOAuthClientId } from '@/lib/github-oauth';

export const runtime = 'nodejs';

export async function POST() {
  try {
    const clientId = await githubOAuthClientId();
    const response = await fetch('https://github.com/login/device/code', {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded',
        'User-Agent': 'DebToIPA-Public-Runner',
      },
      body: new URLSearchParams({
        client_id: clientId,
        scope: 'read:user public_repo',
      }),
      cache: 'no-store',
    });
    const data = await response.json();
    if (!response.ok || data.error) {
      throw new Error(data.error_description || data.error || `GitHub returned ${response.status}.`);
    }
    return NextResponse.json({
      deviceCode: data.device_code,
      userCode: data.user_code,
      verificationUri: data.verification_uri,
      expiresIn: data.expires_in,
      interval: data.interval,
    }, { headers: { 'Cache-Control': 'no-store' } });
  } catch (error) {
    return NextResponse.json({
      error: error instanceof Error ? error.message : 'GitHub login could not start.',
    }, { status: 503 });
  }
}
