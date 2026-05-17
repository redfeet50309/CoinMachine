// Data fetching: reads JSON from same origin; writes to repo via GitHub Contents API.

const REPO_OWNER = 'redfeet50309';
const REPO_NAME = 'CoinMachine';
const WATCHLIST_PATH = 'data/watchlist.json';
const PAT_KEY = 'coinmachine.pat';

export function getPat() {
  return localStorage.getItem(PAT_KEY) || '';
}

export function setPat(token) {
  if (token) localStorage.setItem(PAT_KEY, token);
  else localStorage.removeItem(PAT_KEY);
}

export async function fetchJSON(path) {
  const r = await fetch(`${path}?t=${Date.now()}`, { cache: 'no-store' });
  if (!r.ok) throw new Error(`fetch ${path}: HTTP ${r.status}`);
  return r.json();
}

export async function fetchWatchlist() {
  return fetchJSON('data/watchlist.json');
}

export async function fetchIndex() {
  try {
    return await fetchJSON('data/index.json');
  } catch {
    return { stocks: [] };
  }
}

export async function fetchMeta() {
  try {
    return await fetchJSON('data/meta.json');
  } catch {
    return null;
  }
}

export async function fetchStock(id) {
  try {
    return await fetchJSON(`data/stocks/${id}.json`);
  } catch {
    return null;
  }
}

async function ghContents(method, body = null) {
  const pat = getPat();
  if (!pat) throw new Error('未設定 GitHub PAT，無法同步到 repo');
  const url = `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/contents/${WATCHLIST_PATH}`;
  const opts = {
    method,
    headers: {
      Authorization: `Bearer ${pat}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
    },
  };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(url, opts);
  if (!r.ok) {
    const text = await r.text();
    throw new Error(`GitHub API ${r.status}: ${text}`);
  }
  return r.json();
}

export async function writeWatchlist(newWatchlist, commitMessage) {
  const current = await ghContents('GET');
  const content = btoa(unescape(encodeURIComponent(JSON.stringify(newWatchlist, null, 2) + '\n')));
  return ghContents('PUT', {
    message: commitMessage,
    content,
    sha: current.sha,
    branch: 'main',
  });
}

export function localWatchlistKey() {
  return 'coinmachine.watchlist.v1';
}

export function readLocalWatchlist() {
  try {
    return JSON.parse(localStorage.getItem(localWatchlistKey()) || 'null');
  } catch {
    return null;
  }
}

export function writeLocalWatchlist(wl) {
  localStorage.setItem(localWatchlistKey(), JSON.stringify(wl));
}
