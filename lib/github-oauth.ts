const CONFIG_URL = 'https://raw.githubusercontent.com/NightVibes33/DebtoIPA/main/public/oauth-config.json';

function validateClientId(value: string): string {
  const clientId = value.trim();
  if (!/^[A-Za-z0-9._-]{8,100}$/.test(clientId)) {
    throw new Error('GitHub login has not been configured by the DebToIPA owner yet.');
  }
  return clientId;
}

export async function githubOAuthClientId(): Promise<string> {
  const configured = process.env.GITHUB_OAUTH_CLIENT_ID?.trim();
  if (configured) return validateClientId(configured);

  const response = await fetch(CONFIG_URL, { cache: 'no-store' });
  if (!response.ok) throw new Error('GitHub login configuration could not be loaded.');
  const data = await response.json() as { clientId?: string };
  return validateClientId(String(data.clientId || ''));
}
