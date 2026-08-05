const apiBase = 'https://api.github.com';

export function githubConfig() {
  const token = process.env.GITHUB_TOKEN;
  const owner = process.env.GITHUB_OWNER || 'NightVibes33';
  const repo = process.env.GITHUB_REPO || 'DebtoIPA';
  if (!token) throw new Error('GITHUB_TOKEN is not configured on Vercel.');
  return { token, owner, repo };
}

export async function githubFetch(path: string, init: RequestInit = {}) {
  const { token } = githubConfig();
  const response = await fetch(`${apiBase}${path}`, {
    ...init,
    cache: 'no-store',
    headers: {
      Accept: 'application/vnd.github+json',
      Authorization: `Bearer ${token}`,
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': 'DebtoIPA-Vercel',
      ...(init.headers || {}),
    },
  });
  return response;
}

export function assertAccessCode(request: Request) {
  const expected = process.env.APP_ACCESS_CODE;
  if (!expected) return;
  const actual = request.headers.get('x-app-access-code');
  if (!actual || actual !== expected) throw new Error('Invalid access code.');
}
